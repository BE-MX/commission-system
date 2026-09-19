"""Per-instance transfer worker; independent of the single business scheduler."""
from datetime import timedelta
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import and_, or_

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.storage.cos import CosObjectStore, ObjectMissing, StorageError, file_digest
from app.core.storage.models import StorageTransfer
from app.core.storage.transfers import source_path
from app.core.time import beijing_now

logger = logging.getLogger('commission')


def claim(db, owner):
    now = beijing_now()
    row = db.query(StorageTransfer).filter(
        StorageTransfer.source_instance == owner,
        StorageTransfer.next_attempt_at <= now,
        or_(StorageTransfer.status == 'pending',
            and_(StorageTransfer.status.in_(['running', 'deleted']),
                 or_(StorageTransfer.lease_until.is_(None), StorageTransfer.lease_until <= now))),
    ).order_by(StorageTransfer.next_attempt_at).with_for_update(skip_locked=True).first()
    if not row:
        return None
    row.lease_token = uuid4().hex
    row.lease_until = now + timedelta(minutes=15)
    row.attempts += 1
    if row.status != 'deleted':
        row.status = 'running'
    data = {c.name: getattr(row, c.name) for c in StorageTransfer.__table__.columns}
    db.commit()
    return data


def transfer(job, store):
    if job['status'] == 'deleted':
        store.delete(job['object_key'])
        if job['domain'] != 'colorwork':
            source_path(job['domain'], job['object_key']).unlink(missing_ok=True)
        return
    path = source_path(job['domain'], job['object_key'])
    if file_digest(path) != (job['file_size'], job['sha256']):
        raise StorageError('Local source differs from durable registration')
    try:
        store.head(job['object_key'])
    except ObjectMissing:
        store.put_file(job['object_key'], path, job['content_type'])
    cache = Path(get_settings().COS_CACHE_ROOT)
    cache.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='transfer-check-', dir=cache) as temporary:
        store.download(job['object_key'], Path(temporary) / 'object',
                       max_bytes=max(1, job['file_size']), expected_sha256=job['sha256'])


def finalize(db, job, error=None):
    row = db.query(StorageTransfer).filter_by(id=job['id']).with_for_update().populate_existing().first()
    if row is None or row.lease_token != job['lease_token']:
        db.rollback()
        return False
    row.lease_token = None
    row.lease_until = None
    row.last_error = type(error).__name__ if error else None
    if row.status == 'deleted':
        # Retain the tombstone and recheck forever: a crashed/stale uploader may
        # complete AFTER an earlier cleanup. The immutable key is never reused.
        row.next_attempt_at = beijing_now() + timedelta(minutes=5)
    elif error:
        row.status = 'pending'
        row.next_attempt_at = beijing_now() + timedelta(seconds=min(3600, 10 * 2 ** min(row.attempts, 8)))
    else:
        row.status = 'ready'
    db.commit()
    return True


def run_once(session_factory=SessionLocal, store_factory=CosObjectStore):
    owner = get_settings().COS_INSTANCE_ID
    if not owner:
        raise StorageError('Worker needs a stable storage instance identity')
    with session_factory() as db:
        job = claim(db, owner)
    if job is None:
        return False
    error = None
    try:
        transfer(job, store_factory(job['domain']))
    except Exception as exc:
        error = exc
        logger.warning('Storage transfer failed id=%s type=%s', job['id'], type(exc).__name__)
        print(f"[storage] transfer failed id={job['id']} type={type(exc).__name__}", flush=True)
    with session_factory() as db:
        finalize(db, job, error)
    return True


def start_worker():
    settings = get_settings()
    if not settings.COS_WORKER_ENABLED:
        return None
    if not settings.COS_INSTANCE_ID:
        raise StorageError('COS_INSTANCE_ID must be set before starting storage worker')
    stop = Event()
    def loop():
        while not stop.is_set():
            try:
                did_work = run_once()
            except Exception as exc:
                logger.warning('Storage worker failed type=%s', type(exc).__name__)
                print(f'[storage] worker failed type={type(exc).__name__}', flush=True)
                did_work = False
            if not did_work:
                stop.wait(3)
    thread = Thread(target=loop, name='storage-transfer', daemon=True)
    thread.start()
    return stop, thread


def stop_worker(worker):
    if worker:
        stop, thread = worker
        stop.set()
        thread.join(timeout=5)
