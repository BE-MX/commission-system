"""摸底脚本：打印 lsordertest.okki_outbound_records / okki_outbound_record_items 的全部列与 3 行样例。

这两张表是 OKKI 同步作业维护的只读镜像，真实字段名本仓库无人知晓；
app/shipping_inspection/outbound_service.py 的候选字段名映射以本脚本输出为准校准。

用法（在能连生产库的服务器上跑）：
    cd backend && .venv/Scripts/python.exe -m scripts.show_okki_outbound_columns
"""

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal

TABLES = ("okki_outbound_records", "okki_outbound_record_items")


def main() -> None:
    schema = get_settings().BUSINESS_DB_NAME
    db = SessionLocal()
    try:
        for table in TABLES:
            print(f"== {schema}.{table} ==")
            columns = db.execute(text(f"SHOW COLUMNS FROM `{schema}`.`{table}`")).mappings().all()
            for col in columns:
                print(
                    f"  {col['Field']:<32} {col['Type']:<24}"
                    f" null={col['Null']} key={col['Key']} default={col['Default']}"
                )
            rows = db.execute(text(f"SELECT * FROM `{schema}`.`{table}` LIMIT 3")).mappings().all()
            print(f"  -- 样例 {len(rows)} 行 --")
            for row in rows:
                print(" ", dict(row))
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
