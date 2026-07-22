"""存量库创建 taxonomy v2 新维度（并存期不可见）

用法（backend/ 目录下）：
    python scripts/tag_taxonomy/setup_dimensions.py

行为：
- 按 app/asset/taxonomy_def.py 创建新维度，is_visible=0（前端/folder_upload 均不参与），
  is_required 强制 0（必填在前端切换日由 flip_visibility.py 生效）
- 按 name 幂等：已存在的维度跳过（year 沿用存量维度，天然跳过）
- 回填 parent_value_id（content_type→content_category / product_type 族挂靠）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.database import SessionLocal
from app.asset.models import TagDimension
from app.asset.tag_service import create_taxonomy_dimension, link_taxonomy_parents, invalidate_dim_cache
from app.asset.taxonomy_def import TAXONOMY_V2


def main():
    db = SessionLocal()
    try:
        existing = {d.name for d in db.query(TagDimension).all()}
        created, skipped = [], []
        for dim_def in TAXONOMY_V2:
            if dim_def["name"] in existing:
                skipped.append(dim_def["name"])
                continue
            create_taxonomy_dimension(db, dim_def, is_visible=0, force_optional=True)
            created.append(dim_def["name"])
        link_taxonomy_parents(db)
        db.commit()
        invalidate_dim_cache()
        print(f"创建维度: {created}", flush=True)
        print(f"已存在跳过: {skipped}", flush=True)
    except Exception as e:
        db.rollback()
        print(f"失败已回滚: {e}", flush=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
