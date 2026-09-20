"""Transactional registration and owner-bound reads for durable local uploads."""
from contextlib import contextmanager
import hashlib
import mimetypes
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.config import get_settings
from app.core.storage.cos import CosObjectStore, StorageError, enabled, file_digest, validate_key
from app.core.storage.models import StorageTransfer
from app.core.storage.files import cached_path
from app.core.time import beijing_now

logger = logging.getLogger('commission')


def managed(domain):
    return enabled(domain) or domain in get_settings().COS_MANAGED_DOMAINS


def transfer_id(domain, key):
    return hashlib.sha256((domain + '\0' + validate_key(key)).encode()).hexdigest()


def source_path(domain, key):
    if domain == 'shipping-inspection':
        from app.shipping_inspection.file_service import resolve_path
        return resolve_path(validate_key(key))
    if domain == 'asset':
        from app.core.storage.files import local_path
        return local_path(get_settings().ASSET_STORAGE_ROOT, key)
    if domain == 'expo':
        from app.expo.ai_pipeline import UPLOAD_ROOT
        from app.core.storage.files import local_path
        return local_path(UPLOAD_ROOT, key)
    raise ValueError('Unsupported local transfer domain')


def register(db, domain, key):
    if not enabled(domain):
        if managed(domain):
            raise StorageError('New cloud uploads are paused for this domain')
        return None
    owner = get_settings().COS_INSTANCE_ID
    if not owner:
        raise StorageError('Storage instance identity is required')
    local = source_path(domain, key)
    # Receipt must never become durable before the bytes it acknowledges.
    with local.open('r+b') as stream:
        os.fsync(stream.fileno())
    size, digest = file_digest(local)
    identity = transfer_id(domain, key)
    row = db.get(StorageTransfer, identity)
    if row is not None:
        if (row.sha256, row.file_size, row.source_instance, row.status) != (digest, size, owner, 'pending'):
            raise StorageError('Immutable upload key already registered')
        return row
    row = StorageTransfer(id=identity, domain=domain, object_key=key, source_instance=owner,
                          file_size=size, sha256=digest, content_type=mimetypes.guess_type(key)[0] or 'application/octet-stream',
                          status='pending', next_attempt_at=beijing_now())
    db.add(row)
    return row


def tombstone(db, domain, key):
    if not managed(domain):
        return
    row = db.query(StorageTransfer).filter_by(id=transfer_id(domain, key)).with_for_update().first()
    if row is None:
        row = StorageTransfer(id=transfer_id(domain, key), domain=domain, object_key=key,
                              source_instance=get_settings().COS_LOCAL_OWNER, file_size=0, sha256='',
                              content_type='application/octet-stream', status='deleted')
        db.add(row)
    if row:
        row.status = 'deleted'
        row.lease_token = None
        row.lease_until = None
        row.next_attempt_at = beijing_now()


def snapshot(db, domain, key):
    """Caller must authorize the business reference before requesting this snapshot."""
    if not managed(domain):
        return None
    row = db.get(StorageTransfer, transfer_id(domain, key))
    if row is None:
        # Legacy keys remain readable only on their declared authoritative host.
        if get_settings().COS_INSTANCE_ID == get_settings().COS_LOCAL_OWNER:
            return None
        raise HTTPException(503, '原件尚未完成云同步，请稍后重试', headers={'Retry-After': '10'})
    if row.status == 'deleted':
        raise HTTPException(404, '文件已删除')
    return {name: getattr(row, name) for name in ('domain', 'object_key', 'source_instance', 'status', 'file_size', 'sha256', 'content_type')}


def local_read_path(domain, key, record):
    if record is None or record['source_instance'] == get_settings().COS_INSTANCE_ID:
        path = source_path(domain, key)
        if path.is_file():
            return path
    if record is None:
        raise HTTPException(404, '文件不存在')
    if record['status'] != 'ready':
        raise HTTPException(503, '文件已在本地接收，正在同步到云端', headers={'Retry-After': '10'})
    return None


@contextmanager
def materialize(domain, key, record):
    path = local_read_path(domain, key, record)
    if path is not None:
        yield path
        return
    path = cached_path(domain, key)
    if file_digest(path) != (record['file_size'], record['sha256']):
        raise StorageError('Cloud object differs from registered original')
    yield path


def response(domain, key, record):
    # FileResponse supports same-origin fetch/blob and Range, with no bucket CORS.
    path = local_read_path(domain, key, record)
    headers = {'Cache-Control': 'private, no-store'}
    if path is not None:
        return FileResponse(path, headers=headers)
    try:
        path = cached_path(domain, key)
        if file_digest(path) != (record['file_size'], record['sha256']):
            raise StorageError('Cloud object differs from registered original')
    except Exception as exc:
        logger.warning('Cloud response failed type=%s', type(exc).__name__)
        print(f'[storage] cloud response failed type={type(exc).__name__}', flush=True)
        raise HTTPException(503, '云端文件暂时无法读取，请稍后重试', headers={'Retry-After': '10'}) from None
    headers['X-Ark-Storage'] = 'cos'
    return FileResponse(path, media_type=record['content_type'], headers=headers)
