"""Resolve legacy public preview URLs to referenced, previewable asset objects."""
from fastapi import HTTPException
from sqlalchemy import or_

from app.asset.models import Asset, AssetPermission, AssetVersion
from app.core.storage import transfers
from app.core.storage.cos import validate_key


def preview(db, key):
    try:
        validate_key(key)
    except ValueError:
        raise HTTPException(404, '文件不存在') from None
    # Existing /uploads/assets URLs are public previews, also used by shared
    # folders. Preserve that contract, but never turn them into a bucket gateway.
    asset = (db.query(Asset).outerjoin(AssetPermission, AssetPermission.asset_id == Asset.id)
             .filter(Asset.status != 'offline',
                     or_(AssetPermission.asset_id.is_(None), AssetPermission.allow_preview == 1),
                     or_(Asset.storage_path == key, Asset.thumbnail_path == key,
                         Asset.id.in_(db.query(AssetVersion.asset_id).filter(AssetVersion.storage_path == key))))
             .first())
    if asset is None:
        raise HTTPException(404, '文件不存在或不允许预览')
    record = transfers.snapshot(db, 'asset', key)
    db.rollback()
    return transfers.response('asset', key, record)
