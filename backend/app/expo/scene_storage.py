"""Versioned scene illustrations: publish bytes before switching the SQL alias."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import shutil

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.storage import files, transfers
from app.core.storage.models import StorageAlias


def alias_id(key):
    return transfers.transfer_id('expo', 'scenes/' + key)


def url(db, key):
    row = db.get(StorageAlias, alias_id(key))
    if row is None:
        return False, None
    return True, '/uploads/expo/' + row.target_key if row.target_key else None


def switch(db, key, target):
    try:
        row = db.query(StorageAlias).filter_by(id=alias_id(key)).with_for_update().one_or_none()
        old = row.target_key if row else None
        if row is None:
            row = StorageAlias(id=alias_id(key), domain='expo', logical_key='scenes/' + key)
            db.add(row)
            from app.expo.ai_pipeline import _SCENE_IMAGE_EXTS
            for suffix in _SCENE_IMAGE_EXTS:
                transfers.tombstone(db, 'expo', f'scenes/{key}{suffix}')
        row.target_key = target
        if old and old != target:
            transfers.tombstone(db, 'expo', old)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '场景图正在被其他人修改，请刷新后重试') from None
    except Exception:
        db.rollback()
        raise


def save(db, key, upload, suffix):
    from app.expo.ai_pipeline import downscale_inplace, _SCENE_IMG_MAX_EDGE
    root = Path(get_settings().COS_CACHE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='scene-', dir=root) as directory:
        path = Path(directory) / ('image' + suffix)
        with path.open('wb') as output:
            shutil.copyfileobj(upload.file, output)
        downscale_inplace(path, _SCENE_IMG_MAX_EDGE)
        target = f'scenes/versions/{key}-{uuid4().hex}{suffix}'
        files.publish_local('expo', target, path)
    # Failed/uncertain commit preserves new and old bytes for reconciliation.
    switch(db, key, target)
    return '/uploads/expo/' + target


def delete(db, key):
    from app.expo.ai_pipeline import scene_image_url
    existed = scene_image_url(key, db=db) is not None
    switch(db, key, None)
    return existed
