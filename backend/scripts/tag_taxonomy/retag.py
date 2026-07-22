"""存量素材重打标签：旧体系 → taxonomy v2（第1层确定性映射 + 第2层规则计算）

用法（backend/ 目录下）：
    python scripts/tag_taxonomy/retag.py                      # dry-run（默认，只出报告不写库）
    python scripts/tag_taxonomy/retag.py --execute            # 执行（自动先备份 ark_asset_tags）
    python scripts/tag_taxonomy/retag.py --execute --skip-files   # 跳过 orientation 文件读取

行为要点（方案 docs/requirements/2026-07-22-asset-tag-taxonomy.md 第五节）：
- 以库内实时数据为准，不用快照
- 只写新维度行，旧维度一行不动；INSERT IGNORE 幂等可重跑
- 单选维度按 priority 裁决，同优先级不同值 → 冲突清单不写入
- year 缺失用 created_at 回填；content_category 无法映射 → 待审清单
- 色系(color_family)由最终色号推导；orientation 读文件宽高（缺文件跳过并计数）
- 报告落 tmp/tag_retag_report.txt
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionLocal

settings = get_settings()
from app.asset.color_rules import derive_family  # noqa: E402 — 色系规则唯一实现
from scripts.tag_taxonomy.mapping_def import MAPPING, normalize_color

OLD_DIMS = ("asset_type", "asset_type_2", "color", "others")
NEW_DIMS = ("content_category", "content_type", "product_type", "color_code",
            "color_family", "texture", "shoot_style", "process_step", "theme", "media_trait")
BACKUP_TABLE = "ark_asset_tags_bak_taxv2"
BATCH = 500


# ── 主流程 ───────────────────────────────────────────────

def load_dims(db):
    dims = {}
    rows = db.execute(text(
        "SELECT id, name, is_single_select FROM ark_tag_dimensions")).fetchall()
    for r in rows:
        dims[r.name] = {"id": r.id, "single": bool(r.is_single_select)}
    missing = [n for n in NEW_DIMS if n not in dims]
    if missing:
        raise SystemExit(f"新维度缺失 {missing}，先跑 setup_dimensions.py")
    if "year" not in dims:
        raise SystemExit("year 维度缺失")
    return dims


def load_values(db, dims) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(dict)
    id2name = {v["id"]: k for k, v in dims.items()}
    for r in db.execute(text("SELECT id, dimension_id, value FROM ark_tag_values")).fetchall():
        dim_name = id2name.get(r.dimension_id)
        if dim_name:
            out[dim_name][r.value] = r.id
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--skip-files", action="store_true", help="跳过 orientation 文件读取")
    args = ap.parse_args()

    db = SessionLocal()
    report: list[str] = [f"# 存量重打标报告  {datetime.now():%Y-%m-%d %H:%M:%S}  mode={'EXECUTE' if args.execute else 'DRY-RUN'}"]

    dims = load_dims(db)
    values = load_values(db, dims)

    # 1. 校验映射目标存在；收集需新建的色号
    missing_targets = []
    for (_od, _ov), targets in MAPPING.items():
        for dim_name, val, _p in targets:
            if val not in values.get(dim_name, {}):
                missing_targets.append((dim_name, val))
    if missing_targets:
        raise SystemExit(f"映射目标在标签库不存在（taxonomy 定义与 mapping 不一致）: {sorted(set(missing_targets))}")

    old_color_values = [v for v in values.get("color", {})]
    color_to_create: set[str] = set()
    for ov in old_color_values:
        for dim_name, val, _p in normalize_color(ov):
            if dim_name == "color_code" and val not in values["color_code"]:
                color_to_create.add(val)
    report.append(f"需新建规范化色号 {len(color_to_create)} 个: {sorted(color_to_create)}")

    if color_to_create:
        if args.execute:
            dim_id = dims["color_code"]["id"]
            for i, code in enumerate(sorted(color_to_create)):
                db.execute(text(
                    "INSERT IGNORE INTO ark_tag_values (dimension_id, value, sort_order, is_active, created_at)"
                    " VALUES (:d, :v, :s, 1, NOW())"), {"d": dim_id, "v": code, "s": 1000 + i})
            db.commit()
            values = load_values(db, dims)  # 重载拿新 id
        else:
            # dry-run：给待建色号分配虚拟负数 id，让映射统计口径与执行时一致
            for i, code in enumerate(sorted(color_to_create)):
                values["color_code"][code] = -(i + 1)

    # 2. 拉取素材与旧标签（实时）
    assets = {r.id: r for r in db.execute(text(
        "SELECT id, current_version_id, created_at, file_type, storage_path, orientation FROM ark_assets")).fetchall()}
    old_dim_ids = {dims[n]["id"]: n for n in OLD_DIMS if n in dims}
    year_dim_id = dims["year"]["id"]

    asset_old: dict[int, list[tuple[str, str]]] = defaultdict(list)   # asset_id -> [(old_dim, value)]
    asset_has_year: set[int] = set()
    existing_new: set[tuple[int, int, int]] = set()                   # (asset_id, dim_id, value_id)
    new_dim_ids = {dims[n]["id"] for n in NEW_DIMS}
    id2value = {vid: (dn, v) for dn, m in values.items() for v, vid in m.items()}

    for r in db.execute(text(
            "SELECT at.asset_id, at.dimension_id, at.tag_value_id FROM ark_asset_tags at")).fetchall():
        if r.dimension_id in old_dim_ids:
            dn_v = id2value.get(r.tag_value_id)
            if dn_v:
                asset_old[r.asset_id].append((old_dim_ids[r.dimension_id], dn_v[1]))
        elif r.dimension_id == year_dim_id:
            asset_has_year.add(r.asset_id)
        elif r.dimension_id in new_dim_ids:
            existing_new.add((r.asset_id, r.dimension_id, r.tag_value_id))

    # 3. 逐素材计算目标标签
    to_insert: list[tuple[int, int | None, int, int]] = []
    conflicts: list[str] = []
    no_category: list[int] = []
    year_backfill = 0
    unmapped_used: dict[tuple[str, str], int] = defaultdict(int)

    for asset_id, olds in asset_old.items():
        a = assets.get(asset_id)
        if a is None:
            continue
        # 收集映射目标
        targets: list[tuple[str, str, int]] = []
        for old_dim, old_val in olds:
            if old_dim == "color":
                targets.extend(normalize_color(old_val))
            elif (old_dim, old_val) in MAPPING:
                targets.extend(MAPPING[(old_dim, old_val)])
            else:
                unmapped_used[(old_dim, old_val)] += 1

        # 色系推导（第2层，基于最终色号）
        families = {derive_family(v) for d, v, _p in targets if d == "color_code"}
        targets.extend(("color_family", f, 5) for f in families)

        # 按维度分组裁决
        by_dim: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for dim_name, val, prio in targets:
            by_dim[dim_name].append((val, prio))

        chosen: list[tuple[str, str]] = []
        for dim_name, cands in by_dim.items():
            if dims[dim_name]["single"]:
                best = max(p for _v, p in cands)
                top = {v for v, p in cands if p == best}
                if len(top) > 1:
                    conflicts.append(f"asset={asset_id} dim={dim_name} 同优先级冲突: {sorted(top)}")
                    continue
                chosen.append((dim_name, top.pop()))
            else:
                chosen.extend((dim_name, v) for v in {v for v, _p in cands})

        if not any(d == "content_category" for d, _v in chosen):
            no_category.append(asset_id)

        for dim_name, val in chosen:
            vid = values[dim_name].get(val)
            if vid is None:
                conflicts.append(f"asset={asset_id} 值缺失 {dim_name}={val}")
                continue
            row = (asset_id, dims[dim_name]["id"], vid)
            if row not in existing_new:
                to_insert.append((asset_id, a.current_version_id, dims[dim_name]["id"], vid))

    # 3.5 必填兜底遍历全量素材（零旧标签的素材也要兜住，不能只看 asset_old）
    year_missing_value: list[int] = []
    for asset_id, a in assets.items():
        if asset_id in asset_has_year:
            continue
        if not a.created_at:
            year_missing_value.append(asset_id)
            continue
        ylabel = f"{a.created_at.year}年"
        vid = values.get("year", {}).get(ylabel)
        if vid is None:
            year_missing_value.append(asset_id)
            continue
        if (asset_id, year_dim_id, vid) not in existing_new:
            to_insert.append((asset_id, a.current_version_id, year_dim_id, vid))
            year_backfill += 1
    no_old_tags = [aid for aid in assets if aid not in asset_old]
    no_category.extend(no_old_tags)

    # 4. 报告主体
    report.append(f"素材总数 {len(assets)}，携带旧标签素材 {len(asset_old)}，零旧标签素材 {len(no_old_tags)}")
    report.append(f"待写入新标签行 {len(to_insert)}（已存在的自动跳过）")
    report.append(f"year 兜底回填 {year_backfill} 条；年份值缺失待审 {len(year_missing_value)} 个: {year_missing_value[:20]}")
    report.append(f"单选冲突 {len(conflicts)} 条")
    report.extend("  " + c for c in conflicts[:50])
    if len(conflicts) > 50:
        report.append(f"  ...（其余 {len(conflicts) - 50} 条见执行日志）")
    report.append(f"content_category 无法映射素材 {len(no_category)} 个: {no_category[:30]}")
    if unmapped_used:
        report.append("有使用但未映射的旧值（确认是否放弃）：")
        report.extend(f"  ({d},{v}) × {c}" for (d, v), c in sorted(unmapped_used.items(), key=lambda x: -x[1]))

    # 5. 执行写入
    if args.execute:
        existed = db.execute(text(f"SHOW TABLES LIKE '{BACKUP_TABLE}'")).fetchone()
        if existed:
            report.append(f"备份表 {BACKUP_TABLE} 已存在（保留首次快照，本次未刷新——如需新快照先手动改名旧表）")
        else:
            db.execute(text(f"CREATE TABLE {BACKUP_TABLE} AS SELECT * FROM ark_asset_tags"))
            db.commit()
            report.append(f"备份表 {BACKUP_TABLE} 已创建（本次全新快照）")

        insert_sql = text(
            "INSERT IGNORE INTO ark_asset_tags (asset_id, version_id, dimension_id, tag_value_id)"
            " VALUES (:a, :ver, :d, :v)")
        inserted, failed_rows = 0, 0
        for i in range(0, len(to_insert), BATCH):
            batch = to_insert[i:i + BATCH]
            try:
                db.execute(insert_sql, [{"a": a, "ver": ver, "d": d, "v": v} for a, ver, d, v in batch])
                db.commit()
                inserted += len(batch)
            except Exception as e:
                db.rollback()
                print(f"批次 {i} 整批失败，降级逐行重试: {e}", flush=True)
                # 单条隔离：整批失败不废 500 行，逐行找出坏行
                for a, ver, d, v in batch:
                    try:
                        db.execute(insert_sql, {"a": a, "ver": ver, "d": d, "v": v})
                        db.commit()
                        inserted += 1
                    except Exception as row_e:
                        db.rollback()
                        failed_rows += 1
                        print(f"  行失败 asset={a} dim={d} val={v}: {row_e}", flush=True)
        report.append(f"写入完成 {inserted} 行，失败行 {failed_rows}")

    # 6. orientation 回填（第2层）
    if not args.skip_files:
        todo = [a for a in assets.values() if not a.orientation]
        ok_cnt, miss_cnt, fail_cnt = 0, 0, 0
        updates: list[tuple[int, str]] = []
        for a in todo:
            path = os.path.join(settings.ASSET_STORAGE_ROOT, a.storage_path)
            if not os.path.exists(path):
                miss_cnt += 1
                continue
            try:
                w = h = None
                if a.file_type == "image":
                    from PIL import Image
                    with Image.open(path) as im:
                        w, h = im.size
                elif a.file_type == "video":
                    import cv2
                    cap = cv2.VideoCapture(path)
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                if not w or not h:
                    fail_cnt += 1
                    continue
                ori = "landscape" if w > h * 1.05 else ("portrait" if h > w * 1.05 else "square")
                updates.append((a.id, ori))
                ok_cnt += 1
            except Exception:
                fail_cnt += 1
        report.append(f"orientation: 待回填 {len(todo)}，可计算 {ok_cnt}，文件缺失 {miss_cnt}，读取失败 {fail_cnt}")
        if args.execute and updates:
            for i in range(0, len(updates), BATCH):
                batch = updates[i:i + BATCH]
                db.execute(text("UPDATE ark_assets SET orientation = :o WHERE id = :i"),
                           [{"i": aid, "o": o} for aid, o in batch])
                db.commit()
            report.append(f"orientation 已写入 {len(updates)} 条")

    # 7. 执行后校验：单选维度多值必须为 0
    if args.execute:
        single_ids = [str(dims[n]["id"]) for n in NEW_DIMS if dims[n]["single"]]
        row = db.execute(text(f"""
            SELECT COUNT(*) FROM (
                SELECT asset_id, dimension_id FROM ark_asset_tags
                WHERE dimension_id IN ({','.join(single_ids)})
                GROUP BY asset_id, dimension_id HAVING COUNT(*) > 1) x
        """)).fetchone()
        report.append(f"校验-单选维度多值素材数: {row[0]}（必须为 0）")
        cov = db.execute(text("""
            SELECT d.name, COUNT(DISTINCT at.asset_id)
            FROM ark_asset_tags at JOIN ark_tag_dimensions d ON d.id = at.dimension_id
            GROUP BY d.id ORDER BY d.sort_order
        """)).fetchall()
        report.append("覆盖率（各维度已打标素材数）:")
        report.extend(f"  {r[0]}: {r[1]}" for r in cov)

    db.close()

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "tmp", "tag_retag_report.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\n".join(report[:40]), flush=True)
    print(f"\n完整报告: {out}", flush=True)


if __name__ == "__main__":
    main()
