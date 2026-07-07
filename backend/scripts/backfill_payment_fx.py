"""
数据回填脚本：为已同步的回款记录补填 exchange_rate 和 real_amount_rmb

原因：040 迁移新增这两列后，已同步的旧数据为 NULL。
本脚本从业务库 okki_receipts 读取源数据，批量回填到 synced_payment。

执行方式：
  cd backend
  python -m scripts.backfill_payment_fx
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from sqlalchemy import text
from app.core.database import SessionLocal
from app.core.config import get_settings


def main():
    db = SessionLocal()
    settings = get_settings()
    schema = settings.BUSINESS_DB_NAME

    try:
        # 找出需要回填的记录
        null_count = db.execute(text(
            "SELECT COUNT(*) FROM synced_payment "
            "WHERE exchange_rate IS NULL OR real_amount_rmb IS NULL"
        )).scalar()
        total_count = db.execute(text("SELECT COUNT(*) FROM synced_payment")).scalar()

        print(f"synced_payment 总记录数: {total_count}")
        print(f"需要回填(exchange_rate 或 real_amount_rmb 为 NULL): {null_count}")

        if null_count == 0:
            print("无需回填，所有记录已有数据。")
            return

        # 批量回填：从业务库 JOIN 更新（显式 COLLATE 解决跨库字符集冲突）
        update_sql = text(f"""
            UPDATE synced_payment sp
            INNER JOIN `{schema}`.okki_receipts r
                ON sp.payment_id COLLATE utf8mb4_unicode_ci = CAST(r.cash_collection_id AS CHAR) COLLATE utf8mb4_unicode_ci
            SET sp.exchange_rate = r.exchange_rate,
                sp.real_amount_rmb = r.real_amount_rmb
            WHERE sp.exchange_rate IS NULL OR sp.real_amount_rmb IS NULL
        """)

        result = db.execute(update_sql)
        affected = result.rowcount
        db.commit()

        print(f"回填完成，更新了 {affected} 条记录。")

        # 验证
        still_null = db.execute(text(
            "SELECT COUNT(*) FROM synced_payment "
            "WHERE exchange_rate IS NULL OR real_amount_rmb IS NULL"
        )).scalar()
        print(f"验证: 仍为 NULL 的记录数: {still_null}")

        if still_null > 0:
            print(f"注意: {still_null} 条记录在业务库源数据中也无汇率/RMB金额（源数据本身为NULL）")
        else:
            print("全部回填成功。")

    except Exception as e:
        db.rollback()
        print(f"回填失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
