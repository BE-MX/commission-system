"""Object access for legacy domains whose immutable relative keys stay in the DB."""
from contextlib import contextmanager
import hashlib
import mimetypes
import logging
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import uuid4
from threading import RLock
import time

from app.core.config import get_settings
from app.core.storage.cos import CosObjectStore, ObjectMissing, StorageError, enabled, validate_key, file_digest
from app.core.storage.cache_lock import process_lock, lease, pinned

_cache_lock = RLock()
logger = logging.getLogger('commission')


def managed(domain):
    return enabled(domain) or domain in get_settings().COS_MANAGED_DOMAINS


def local_path(root, key):
    validate_key(key)
    root = Path(root).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError('File path escaped storage root')
    return path


def put_bytes(domain, key, content, content_type=None):
    """False means domain not enabled, never a fallback after cloud failure."""
    if not enabled(domain):
        if managed(domain):
            raise StorageError('New cloud uploads are paused for this domain')
        return False
    cache = Path(get_settings().COS_CACHE_ROOT)
    cache.mkdir(parents=True, exist_ok=True)
    with reserve_processing_bytes(len(content)), TemporaryDirectory(prefix='upload-', dir=cache) as temporary:
        path = Path(temporary) / 'object'
        path.write_bytes(content)
        CosObjectStore(domain).put_file(key, path, content_type or mimetypes.guess_type(key)[0] or 'application/octet-stream')
    return True


def publish_local(domain, key, path):
    if enabled(domain):
        store = CosObjectStore(domain)
        path = Path(path)
        size, sha = file_digest(path)
        try:
            head = store.head(key)
        except ObjectMissing:
            store.put_file(key, path, mimetypes.guess_type(key)[0] or 'application/octet-stream')
        else:
            if (int(head.get('Content-Length', -1)), head.get('x-cos-meta-sha256')) != (size, sha):
                raise StorageError('Immutable object differs from local publication')
    elif managed(domain):
        raise StorageError('New cloud uploads are paused for this domain')


def read_path(domain, key, root):
    if not managed(domain):
        return local_path(root, key)
    return cached_path(domain, key)


def cached_path(domain, key):
    """Private, bounded read-through cache; a missing object never uses old originals."""
    key = validate_key(key)
    store = CosObjectStore(domain)
    head = store.head(key)
    size = int(head.get('Content-Length', -1))
    sha = head.get('x-cos-meta-sha256', '')
    if size < 0 or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise StorageError('Cloud object lacks verified migration metadata')
    cache = Path(get_settings().COS_CACHE_ROOT) / 'objects'
    cache.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256((domain + '\0' + key + '\0' + sha).encode()).hexdigest()
    suffix = Path(key).suffix
    if not re.fullmatch(r'\.[A-Za-z0-9]{1,12}', suffix):
        suffix = '.bin'
    destination = cache / (identity + suffix)
    with _cache_lock, process_lock(cache):
        if destination.is_file() and file_digest(destination) == (size, sha):
            os.utime(destination, None)
            return lease(destination)
        limit = get_settings().COS_CACHE_MAX_BYTES
        if size > limit:
            raise StorageError('Object exceeds private cache capacity')
        _make_room(cache, size, limit)
        store.download(key, destination, max_bytes=max(1, size), expected_sha256=sha)
        return lease(destination)


def delete(domain, key, root):
    if managed(domain):
        CosObjectStore(domain).delete(key)
    else:
        local_path(root, key).unlink(missing_ok=True)


def _make_room(cache, size, limit):
    existing = [(p, p.stat()) for p in cache.iterdir() if p.is_file() and p.name != '.cache.lock']
    sizes = {p: int(p.read_text(encoding='ascii')) if p.suffix == '.reservation' else s.st_size for p, s in existing}
    used = sum(sizes.values())
    for path, stat in sorted(existing, key=lambda item: item[1].st_mtime):
        if used + size <= limit:
            break
        if pinned(path):
            continue
        try:
            path.unlink()
            used -= sizes[path]
        except PermissionError:
            # Windows open handles pin active responses. Keep the hard bound.
            logger.warning('Private cache file is pinned by an active reader')
            print('[storage] private cache file is pinned by an active reader', flush=True)
            continue
    if used + size > limit:
        raise StorageError('Private cache is busy; retry after active downloads complete')


@contextmanager
def reserve_processing_bytes(size):
    """Account temporary exports against the same cross-process disk budget."""
    cache = Path(get_settings().COS_CACHE_ROOT) / 'objects'
    cache.mkdir(parents=True, exist_ok=True)
    reservation = cache / (uuid4().hex + '.reservation')
    with _cache_lock, process_lock(cache):
        _make_room(cache, size, get_settings().COS_CACHE_MAX_BYTES)
        with reservation.open('x', encoding='ascii') as stream:
            stream.write(str(size))
        holder = lease(reservation)
    try:
        yield
    finally:
        with _cache_lock, process_lock(cache):
            holder._lease_finalizer()
            pinned(reservation)
            reservation.unlink(missing_ok=True)
