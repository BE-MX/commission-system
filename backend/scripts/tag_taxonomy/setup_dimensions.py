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
from app.asset.models import TagDimension, TagValue
from app.asset.tag_service import create_taxonomy_dimension, link_taxonomy_parents, invalidate_dim_cache
from app.asset.taxonomy_def import TAXONOMY_V2, iter_values


def _backfill_missing_values(db, dim_def: dict, dim: TagDimension) -> list[str]:
    """已存在的维度补齐 taxonomy 定义中缺失的值（重跑收敛）。year 不动。"""
    if dim_def["name"] == "year":
        return []
    existing_vals = {v.value for v in db.query(TagValue).filter(TagValue.dimension_id == dim.id)}
    added = []
    for i, v in iter_values(dim_def):
        if v["value"] in existing_vals:
            continue
        db.add(TagValue(dimension_id=dim.id, value=v["value"], name_en=v["name_en"],
                        aliases=v["aliases"], sort_order=i, is_active=1))
        added.append(v["value"])
    db.flush()
    return added


def main():
    db = SessionLocal()
    try:
        existing = {d.name: d for d in db.query(TagDimension).all()}
        created, skipped, backfilled = [], [], {}
        for dim_def in TAXONOMY_V2:
            if dim_def["name"] in existing:
                added = _backfill_missing_values(db, dim_def, existing[dim_def["name"]])
                if added:
                    backfilled[dim_def["name"]] = added
                skipped.append(dim_def["name"])
                continue
            create_taxonomy_dimension(db, dim_def, is_visible=0, force_optional=True)
            created.append(dim_def["name"])
        link_taxonomy_parents(db)
        db.commit()
        invalidate_dim_cache()
        print(f"创建维度: {created}", flush=True)
        print(f"已存在跳过: {skipped}", flush=True)
        if backfilled:
            print(f"补齐缺失值: {backfilled}", flush=True)
    except Exception as e:
        db.rollback()
        print(f"失败已回滚: {e}", flush=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
