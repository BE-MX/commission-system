"""批量为所有素材打标签：dimension_id=5, tag_value_id=2026

用法（在 backend/ 目录下）：
    python scripts/bulk_tag_asset.py

逻辑：
1. 遍历 ark_assets 所有记录
2. 跳过已有 (asset_id, 5, 2026) 的素材
3. version_id 取 current_version_id（可为 NULL）
4. 每 100 条 commit 一次
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import SessionLocal


def main():
    db = SessionLocal()
    try:
        # 查找所有素材及其当前版本
        rows = db.execute(text("""
            SELECT a.id, a.current_version_id
            FROM ark_assets a
            WHERE NOT EXISTS (
                SELECT 1 FROM ark_asset_tags t
                WHERE t.asset_id = a.id
                  AND t.dimension_id = 5
                  AND t.tag_value_id = 2026
            )
        """)).fetchall()

        if not rows:
            print("所有素材已包含该标签，无需插入。")
            return

        inserted = 0
        for asset_id, version_id in rows:
            db.execute(text("""
                INSERT INTO ark_asset_tags (asset_id, version_id, dimension_id, tag_value_id)
                VALUES (:asset_id, :version_id, 5, 2026)
            """), {
                "asset_id": asset_id,
                "version_id": version_id,
            })
            inserted += 1
            if inserted % 100 == 0:
                db.commit()
                print(f"  已插入 {inserted}/{len(rows)} ...")

        db.commit()
        print(f"完成：共插入 {inserted} 条记录（跳过已有标签的素材）。")

    except Exception as e:
        db.rollback()
        print(f"失败：{e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
