"""
一次性脚本：为 5 位业务员补录属性历史记录，并刷新其名下客户快照。

用法：
    cd backend
    python -m scripts.fix_employee_history_20260423
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.core.database import SessionLocal
from app.models.employee import EmployeeAttributeHistory
from app.services.customer_reset_service import refresh_snapshots_by_employees

# 历史记录数据
HISTORY_DATA = [
    # (employee_id, employee_name, [(effective_start, attribute_type), ...])
    ("55497300", "刘源", [
        (date(2024, 1, 1), "distribute"),
        (date(2025, 1, 1), "develop"),
        (date(2026, 4, 1), "distribute"),
    ]),
    ("55278725", "代晴玉", [
        (date(2024, 1, 1), "distribute"),
        (date(2025, 1, 1), "develop"),
    ]),
    ("56653054", "曲冉", [
        (date(2025, 1, 1), "develop"),
        (date(2026, 4, 1), "distribute"),
    ]),
    ("55296478", "潘康衡", [
        (date(2024, 1, 1), "distribute"),
        (date(2025, 1, 1), "develop"),
        (date(2026, 4, 1), "distribute"),
    ]),
    ("56158751", "张砚斐", [
        (date(2024, 1, 1), "distribute"),
        (date(2025, 1, 1), "develop"),
        (date(2026, 4, 1), "distribute"),
    ]),
]


def main():
    db = SessionLocal()
    try:
        employee_ids = []

        for emp_id, emp_name, records in HISTORY_DATA:
            # 清除现有记录
            deleted = db.query(EmployeeAttributeHistory).filter(
                EmployeeAttributeHistory.employee_id == emp_id,
            ).delete(synchronize_session="fetch")
            print(f"{emp_name}({emp_id}): 删除 {deleted} 条旧记录")

            # 写入新记录
            sorted_records = sorted(records, key=lambda r: r[0])
            for idx, (eff_start, attr_type) in enumerate(sorted_records):
                is_last = idx == len(sorted_records) - 1
                effective_end = sorted_records[idx + 1][0] if not is_last else None

                new_record = EmployeeAttributeHistory(
                    employee_id=emp_id,
                    attribute_type=attr_type,
                    effective_start=eff_start,
                    effective_end=effective_end,
                    is_current=is_last,
                )
                db.add(new_record)
                print(f"  + {attr_type} | {eff_start} ~ {effective_end or '至今'} | current={is_last}")

            employee_ids.append(emp_id)

        db.flush()
        print(f"\n属性历史已写入，开始刷新客户快照...")

        result = refresh_snapshots_by_employees(db, employee_ids, operator="script")
        print(f"快照刷新完成: 共 {result.total}, 更新 {result.updated}, 跳过 {result.skipped}")

        db.commit()
        print("\n全部完成，已提交。")

    except Exception as e:
        db.rollback()
        print(f"\n执行失败，已回滚: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
