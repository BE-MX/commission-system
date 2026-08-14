"""旧标签维度退役：物理删除 4 个旧维度及其值与关联行

用法（backend/ 目录下）：
    python scripts/tag_taxonomy/retire_old_dims.py            # dry-run（默认，只报数量）
    python scripts/tag_taxonomy/retire_old_dims.py --execute  # 执行

退役对象：asset_type / asset_type_2 / color / others（year 沿用不删）。
删前把 维度/值/关联 三表的旧体系行备份到 *_bak_retire 表（恢复所需的完整闭包；
ark_asset_tags_bak_taxv2 回灌前全量快照另存不动）。
删除顺序受 FK 约束：ark_asset_tags → ark_tag_values → ark_tag_dimensions。
共库操作一次生效；数据删除属 DML 走脚本不走 Alembic（方案原文写迁移，
因三实例共库、迁移会跑多次，成套脚本更合适——2026-07-22 实施时定）。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import bindparam, text
from app.core.database import SessionLocal

OLD_DIMS = ("asset_type", "asset_type_2", "color", "others")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        dim_ids = [r.id for r in db.execute(
            text("SELECT id FROM ark_tag_dimensions WHERE name IN :n")
            .bindparams(bindparam("n", expanding=True)), {"n": list(OLD_DIMS)})]
        if not dim_ids:
            print("旧维度不存在，可能已退役。", flush=True)
            return

        in_ids = ",".join(str(i) for i in dim_ids)
        cnt_tags = db.execute(text(f"SELECT COUNT(*) FROM ark_asset_tags WHERE dimension_id IN ({in_ids})")).scalar()
        cnt_vals = db.execute(text(f"SELECT COUNT(*) FROM ark_tag_values WHERE dimension_id IN ({in_ids})")).scalar()
        print(f"旧维度 {len(dim_ids)} 个 (id={dim_ids})，值 {cnt_vals} 个，标签关联行 {cnt_tags} 条", flush=True)

        if not args.execute:
            print("dry-run 结束。--execute 执行退役。", flush=True)
            return

        # 备份（恢复闭包：维度定义 + 值定义 + 关联行）
        for src, bak in [("ark_tag_dimensions", "ark_tag_dimensions_bak_retire"),
                         ("ark_tag_values", "ark_tag_values_bak_retire"),
                         ("ark_asset_tags", "ark_asset_tags_bak_retire")]:
            if db.execute(text(f"SHOW TABLES LIKE '{bak}'")).fetchone():
                raise SystemExit(f"备份表 {bak} 已存在，为防覆盖旧快照中止；确认后手动改名旧表再跑")
            db.execute(text(f"CREATE TABLE {bak} AS SELECT * FROM {src} WHERE dimension_id IN ({in_ids})"
                            if src != "ark_tag_dimensions"
                            else f"CREATE TABLE {bak} AS SELECT * FROM {src} WHERE id IN ({in_ids})"))
        db.commit()
        print("三表备份完成 (*_bak_retire)", flush=True)

        # FK 顺序删除
        d1 = db.execute(text(f"DELETE FROM ark_asset_tags WHERE dimension_id IN ({in_ids})")).rowcount
        d2 = db.execute(text(f"DELETE FROM ark_tag_values WHERE dimension_id IN ({in_ids})")).rowcount
        d3 = db.execute(text(f"DELETE FROM ark_tag_dimensions WHERE id IN ({in_ids})")).rowcount
        db.commit()
        print(f"已删除：关联行 {d1} / 值 {d2} / 维度 {d3}", flush=True)

        # 验证
        left = db.execute(text("SELECT COUNT(*) FROM ark_tag_dimensions")).scalar()
        untagged = db.execute(text("""
            SELECT COUNT(*) FROM ark_assets a
            WHERE NOT EXISTS (SELECT 1 FROM ark_asset_tags t WHERE t.asset_id = a.id)
        """)).scalar()
        print(f"验证：剩余维度 {left} 个；完全无标签素材 {untagged} 个（应为 0）", flush=True)
    except Exception as e:
        db.rollback()
        print(f"失败已回滚: {e}", flush=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
