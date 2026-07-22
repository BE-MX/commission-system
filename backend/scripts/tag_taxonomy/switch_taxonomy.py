"""标签体系切换日脚本：新维度启用 / 旧维度停用 / 必填生效

用法（backend/ 目录下，切换前先重跑一遍 retag.py --execute 兜增量）：
    python scripts/tag_taxonomy/switch_taxonomy.py            # 执行切换
    python scripts/tag_taxonomy/switch_taxonomy.py --rollback # 回退到并存态

共库操作，一次生效；线上实例 list_dimensions_cached 60 秒 TTL 自然过期，无需重启。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import bindparam, text
from app.core.database import SessionLocal

NEW_DIMS = ("content_category", "content_type", "product_type", "color_code",
            "color_family", "texture", "shoot_style", "process_step", "theme", "media_trait")
OLD_DIMS = ("asset_type", "asset_type_2", "color", "others")
REQUIRED_DIMS = ("content_category", "content_type", "year")


def _exec_in(db, sql: str, names) -> None:
    db.execute(text(sql).bindparams(bindparam("n", expanding=True)), {"n": list(names)})


def _dump_state(db, title):
    print(f"--- {title} ---", flush=True)
    for r in db.execute(text(
            "SELECT name, label, is_visible, is_required FROM ark_tag_dimensions ORDER BY sort_order")):
        print(f"  {r.name:18s} [{r.label}] visible={r.is_visible} required={r.is_required}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollback", action="store_true", help="回退：新维度隐藏、旧维度恢复可见")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        _dump_state(db, "切换前")
        if args.rollback:
            _exec_in(db, "UPDATE ark_tag_dimensions SET is_visible=0, is_required=0 WHERE name IN :n", NEW_DIMS)
            _exec_in(db, "UPDATE ark_tag_dimensions SET is_visible=1 WHERE name IN :n", OLD_DIMS)
        else:
            _exec_in(db, "UPDATE ark_tag_dimensions SET is_visible=1 WHERE name IN :n", NEW_DIMS)
            _exec_in(db, "UPDATE ark_tag_dimensions SET is_visible=0, is_required=0 WHERE name IN :n", OLD_DIMS)
            _exec_in(db, "UPDATE ark_tag_dimensions SET is_required=1 WHERE name IN :n", REQUIRED_DIMS)
        db.commit()
        _dump_state(db, "切换后")

        # 顺带验证 orientation 覆盖（应接近素材总数）
        r = db.execute(text(
            "SELECT COUNT(*) total, SUM(orientation IS NOT NULL) filled FROM ark_assets")).fetchone()
        print(f"orientation 覆盖: {r.filled}/{r.total}", flush=True)
        print("完成。线上实例缓存 60 秒内自动过期生效。", flush=True)
    except Exception as e:
        db.rollback()
        print(f"失败已回滚: {e}", flush=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
