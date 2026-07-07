"""
数据修复脚本：修复客户归属快照中的业务员属性和比例

修复内容：
1. 业务员属性为"分配"时比例应为1%（之前错误地写入了2%）
2. 按员工属性变动时间点（首次回款日期）重新判定业务员属性

执行方式：
  cd backend
  python -m scripts.fix_snapshot_rates
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.customer import CustomerCommissionSnapshot
from app.services.customer_reset_service import refresh_snapshots_by_employees


def main():
    db = SessionLocal()
    try:
        # 先统计当前状态
        all_current = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.is_current == True,
        ).all()

        distribute_wrong = [
            s for s in all_current
            if s.salesperson_attribute == "distribute"
            and s.salesperson_rate is not None
            and float(s.salesperson_rate) == 0.02
        ]

        print(f"当前有效快照总数: {len(all_current)}")
        print(f"  其中已完整: {sum(1 for s in all_current if s.is_complete)}")
        print(f"  其中待补充: {sum(1 for s in all_current if not s.is_complete)}")
        print(f"  分配属性但比例=2%（需修复）: {len(distribute_wrong)}")
        print()

        # 收集所有涉及的业务员 ID
        employee_ids = list(set(s.salesperson_id for s in all_current if s.is_complete))
        print(f"将对 {len(employee_ids)} 位业务员的快照重新计算属性和比例...")
        print()

        # 执行修复
        result = refresh_snapshots_by_employees(db, employee_ids, operator="data_fix_20260701")
        db.commit()

        print(f"修复完成:")
        print(f"  处理快照数: {result.total}")
        print(f"  成功更新: {result.updated}")
        print(f"  跳过(无属性记录): {result.skipped}")
        print()

        # 验证修复结果
        still_wrong = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.is_current == True,
            CustomerCommissionSnapshot.salesperson_attribute == "distribute",
            CustomerCommissionSnapshot.salesperson_rate == 0.02,
        ).count()
        print(f"验证: 分配属性但比例仍为2%的记录数: {still_wrong}")

        if still_wrong == 0:
            print("数据修复成功，所有分配属性的业务员比例已修正为1%")
        else:
            print(f"警告: 仍有 {still_wrong} 条记录未修复，请检查")

    except Exception as e:
        db.rollback()
        print(f"修复失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
