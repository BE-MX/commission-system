"""
数据修复脚本：统一业务员提成比例为 2%

背景（2026-07-08）：
  客户归属规则调整——业务员属性无论开发/分配，提成比例统一 2%。
  规则层已改 app/services/rate_utils.py（calc_commission_rates 恒返回 2%）。
  本脚本把「已有的当前有效归属快照」里业务员比例不是 2% 的记录（历史上分配=1%）
  刷成 2%。

范围（与需求确认一致）：
  ✔ 仅当前有效快照 is_current=True
  ✘ 历史快照 is_current=False 不动（保留审计痕迹）
  ✘ 已算出的提成明细 commission_detail 不动（已冻结账本，未来批次自然用 2%）

幂等：重复执行安全，第二次 updated=0。

执行方式：
  cd backend
  python -m scripts.unify_salesperson_rate_2pct
"""

import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.customer import CustomerCommissionSnapshot

TARGET_RATE = Decimal("0.0200")


def main():
    db = SessionLocal()
    try:
        # ---- 前置统计 ----
        current = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.is_current == True,
        ).all()

        need_fix = [
            s for s in current
            if s.salesperson_rate is not None
            and Decimal(str(s.salesperson_rate)) != TARGET_RATE
        ]

        print(f"当前有效快照总数: {len(current)}")
        print(f"  其中已完整(有比例): {sum(1 for s in current if s.salesperson_rate is not None)}")
        print(f"  业务员比例 != 2%（需刷成 2%）: {len(need_fix)}")
        if need_fix:
            print("  示例（最多 10 条）:")
            for s in need_fix[:10]:
                print(f"    客户 {s.customer_id} 业务员 {s.salesperson_id} "
                      f"属性 {s.salesperson_attribute} 当前比例 {s.salesperson_rate}")
        print()

        # ---- 执行更新（单条 UPDATE，走 is_current + 比例条件）----
        updated = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.is_current == True,
            CustomerCommissionSnapshot.salesperson_rate.isnot(None),
            CustomerCommissionSnapshot.salesperson_rate != TARGET_RATE,
        ).update(
            {"salesperson_rate": TARGET_RATE},
            synchronize_session=False,
        )
        db.commit()

        print(f"更新完成: {updated} 条业务员比例已刷成 2%")
        print()

        # ---- 验证 ----
        still_wrong = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.is_current == True,
            CustomerCommissionSnapshot.salesperson_rate.isnot(None),
            CustomerCommissionSnapshot.salesperson_rate != TARGET_RATE,
        ).count()
        print(f"验证: 当前有效快照中业务员比例仍 != 2% 的记录数: {still_wrong}")
        if still_wrong == 0:
            print("数据修复成功，所有当前有效快照的业务员比例已统一为 2%")
        else:
            print(f"警告: 仍有 {still_wrong} 条未修复，请检查")

    except Exception as e:
        db.rollback()
        print(f"修复失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
