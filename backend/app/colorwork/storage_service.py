"""R2-compatible object semantics over private COS, behind the local worker."""
import base64
import hashlib
import hmac
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.storage.cos import CosObjectStore, ObjectMissing, validate_key
from app.core.storage.models import StorageAlias, StoragePublication
from app.core.storage import transfers

DOMAIN = 'colorwork'
MAX_BYTES = 256 * 1024 * 1024


def secret():
    return hmac.new(get_settings().JWT_SECRET_KEY.encode(), b'ark-colorwork-storage', hashlib.sha256).hexdigest()


def identity(key):
    return transfers.transfer_id(DOMAIN, validate_key(key))


def target(db, key):
    row = db.get(StorageAlias, identity(key))
    return row.target_key if row is not None else key


def metadata(key, head):
    return {'key': key, 'size': int(head['Content-Length']),
            'etag': head.get('ETag', '').strip('"'),
            'httpMetadata': {'contentType': head.get('Content-Type', 'application/octet-stream')},
            'customMetadata': {k[len('x-cos-meta-'):]: str(v) for k, v in head.items() if k.startswith('x-cos-meta-')}}


def head(db, key, store=None):
    store = store or CosObjectStore(DOMAIN)
    physical = target(db, key)
    db.rollback()
    if physical is None:
        return None, None
    try:
        return physical, metadata(key, store.head(physical))
    except ObjectMissing:
        return None, None


def publish(db, key, path, content_type, custom, only_create, store=None, operation_id=None):
    store = store or CosObjectStore(DOMAIN)
    validate_key(key)
    receipt_id = hashlib.sha256((DOMAIN + '\0' + key + '\0' + operation_id).encode()).hexdigest() if operation_id else None
    if receipt_id:
        receipt = db.get(StoragePublication, receipt_id)
        if receipt is not None:
            result = dict(receipt.response_json)
            db.rollback()
            return result
    db.rollback()
    # Network I/O precedes the alias transaction. A failed upload preserves the old reference.
    physical = 'objects/' + uuid4().hex
    store.put_file(physical, path, content_type, custom_metadata=custom)
    published = metadata(key, store.head(physical))
    try:
        row = db.query(StorageAlias).filter_by(id=identity(key)).with_for_update().one_or_none()
        if receipt_id:
            receipt = db.query(StoragePublication).filter_by(id=receipt_id).with_for_update().one_or_none()
            if receipt is not None:
                result = dict(receipt.response_json)
                db.rollback()
                return result
        if only_create:
            old = row.target_key if row is not None else key
            if old is not None:
                try:
                    store.head(old)
                except ObjectMissing:
                    pass  # An absent object satisfies R2 If-None-Match: *.
                else:
                    raise HTTPException(412, 'Object already exists')
        if row is None:
            row = StorageAlias(id=identity(key), domain=DOMAIN, logical_key=key)
            db.add(row)
            old = key
        else:
            old = row.target_key
        row.target_key = physical
        if old and old != physical:
            transfers.tombstone(db, DOMAIN, old)
        if receipt_id:
            db.add(StoragePublication(id=receipt_id, response_json=published))
        db.commit()
    except IntegrityError:
        db.rollback()
        if receipt_id:
            receipt = db.get(StoragePublication, receipt_id)
            if receipt is not None:
                result = dict(receipt.response_json)
                db.rollback()
                return result
        # A concurrent first publication won. Preserve unreferenced bytes for reconciliation.
        raise HTTPException(412 if only_create else 409, 'Concurrent object publication; retry') from None
    except Exception:
        db.rollback()
        raise
    return published


def delete(db, key):
    try:
        row = db.query(StorageAlias).filter_by(id=identity(key)).with_for_update().one_or_none()
        old = row.target_key if row is not None else key
        if row is None:
            row = StorageAlias(id=identity(key), domain=DOMAIN, logical_key=key)
            db.add(row)
        row.target_key = None
        if old:
            transfers.tombstone(db, DOMAIN, old)
        db.commit()
    except Exception:
        db.rollback()
        raise


def decode_metadata(value):
    try:
        if len(value) > 4096:
            raise ValueError()
        result = json.loads(base64.b64decode(value, validate=True))
        if not isinstance(result, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in result.items()):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise HTTPException(400, 'Invalid object metadata') from None
