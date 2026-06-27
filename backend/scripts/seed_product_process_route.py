"""
一次性脚本：根据 okki_products.model 关键字批量插入 product_process_route 绑定。

规则：
- model 包含"天才" → route_id=2
- model 包含"棒棒" → route_id=3
- model 包含"平型" → route_id=5
- model 包含"铁丝" → route_id=6
- 其余未匹配   → route_id=2

用法: cd backend && python -m scripts.seed_product_process_route
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.core.config import get_settings

settings = get_settings()
business_db = settings.BUSINESS_DB_NAME


def main():
    db = SessionLocal()
    try:
        sql = text(f"""
            INSERT INTO product_process_route (product_id, route_id, created_at, updated_at)
            SELECT
                p.product_id,
                CASE
                    WHEN p.model LIKE '%天才%' THEN 2
                    WHEN p.model LIKE '%棒棒%' THEN 3
                    WHEN p.model LIKE '%平型%' THEN 5
                    WHEN p.model LIKE '%铁丝%' THEN 6
                    ELSE 2
                END AS route_id,
                NOW(),
                NOW()
            FROM `{business_db}`.okki_products p
            WHERE p.product_id NOT IN (SELECT product_id FROM product_process_route)
        """)
        result = db.execute(sql)
        db.commit()
        print(f"Done. Inserted {result.rowcount} rows into product_process_route.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
