"""素材管理 — 批量操作服务"""

from __future__ import annotations
from app.core.time import beijing_now

import logging
import os
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from sqlalchemy.orm import Session

from app.asset.models import Asset

logger = logging.getLogger("asset")

# 文件存储根目录
from app.core.config import get_settings

ASSET_STORAGE_ROOT = Path(get_settings().ASSET_STORAGE_ROOT)


def batch_download(
    db: Session,
    asset_ids: list[int],
) -> tuple[bytes, str]:
    """批量打包下载素材。返回 (zip_bytes, zip_filename)。"""
    assets = db.query(Asset).filter(Asset.id.in_(asset_ids), Asset.status != "offline").all()
    if not assets:
        raise ValueError("未找到可下载的素材")

    # 创建临时 ZIP 文件
    with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for asset in assets:
                abs_path = ASSET_STORAGE_ROOT / asset.storage_path
                if not abs_path.exists():
                    continue
                # ZIP 内使用原始文件名
                arcname = asset.file_name
                # 处理重名
                counter = 1
                original_arcname = arcname
                while arcname in zf.namelist():
                    name, ext = os.path.splitext(original_arcname)
                    arcname = f"{name}_{counter}{ext}"
                    counter += 1
                zf.write(abs_path, arcname)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        data = f.read()
    os.unlink(tmp_path)

    timestamp = beijing_now().strftime("%Y%m%d_%H%M%S")
    return data, f"leshine_assets_{timestamp}.zip"


def batch_add_tags(
    db: Session,
    asset_ids: list[int],
    tags: list,  # list[AssetTagItem]，延迟标注避免循环依赖
) -> dict:
    """批量追加标签。多选维度取并集（已有标签保留）；单选维度替换为唯一新值。

    托管维度（色系等）由派生逻辑独占写入，请求中的托管维度跳过并留痕
    （与 asset_service._apply_tags 同一约定）。返回 {"updated": [...], "missing": [...]}。
    """
    from app.asset.asset_service import _clear_tags, _validate_single_select
    from app.asset.color_rules import sync_color_family
    from app.asset.models import TagDimension, asset_tag_association

    _validate_single_select(db, tags)

    dims = {
        d.id: d
        for d in db.query(TagDimension).filter(
            TagDimension.id.in_({t.dimension_id for t in tags} or {0})
        )
    }
    items: list[tuple[TagDimension, list[int]]] = []
    for t in tags:
        dim = dims.get(t.dimension_id)
        if dim is None:
            continue
        if dim.is_managed == 1:
            logger.warning("skip managed dimension in batch add: dim=%s", dim.id)
            print(f"[asset] skip managed dim in batch add dim={dim.id}", flush=True)
            continue
        if t.tag_value_ids:
            items.append((dim, t.tag_value_ids))

    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).all()
    found_ids = {a.id for a in assets}
    missing = [aid for aid in asset_ids if aid not in found_ids]

    for asset in assets:
        version_id = asset.current_version_id
        for dim, tv_ids in items:
            if dim.is_single_select == 1:
                # 单选维度：替换为新值（先清后写）
                _clear_tags(db, asset.id, version_id, dimension_ids=[dim.id])
                for tv_id in tv_ids:
                    db.execute(
                        asset_tag_association.insert().values(
                            asset_id=asset.id,
                            version_id=version_id,
                            dimension_id=dim.id,
                            tag_value_id=tv_id,
                        )
                    )
            else:
                # 多选维度：并集追加，已有关联不重复写
                existing = {
                    row.tag_value_id
                    for row in db.execute(
                        asset_tag_association.select().where(
                            asset_tag_association.c.asset_id == asset.id,
                            asset_tag_association.c.dimension_id == dim.id,
                        )
                    ).fetchall()
                }
                for tv_id in tv_ids:
                    if tv_id not in existing:
                        db.execute(
                            asset_tag_association.insert().values(
                                asset_id=asset.id,
                                version_id=version_id,
                                dimension_id=dim.id,
                                tag_value_id=tv_id,
                            )
                        )
        sync_color_family(db, asset.id, version_id)

    db.commit()
    return {"updated": sorted(found_ids), "missing": missing}


def batch_delete_assets(db: Session, asset_ids: list[int]) -> dict:
    """批量删除素材（含物理文件）。返回 {"deleted": n, "deleted_ids": [...], "failed_ids": [...]}。"""
    from app.asset.asset_service import delete_asset

    deleted: list[int] = []
    failed: list[int] = []
    for asset_id in asset_ids:
        try:
            if delete_asset(db, asset_id):
                deleted.append(asset_id)
            else:
                failed.append(asset_id)
        except Exception as exc:
            db.rollback()
            logger.warning("batch delete asset failed: id=%s err=%s", asset_id, exc)
            print(f"[asset] batch delete failed id={asset_id} err={exc}", flush=True)
            failed.append(asset_id)
    return {"deleted": len(deleted), "deleted_ids": deleted, "failed_ids": failed}
