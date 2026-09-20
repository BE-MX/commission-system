"""Copy on the source host; full-byte verification on a same-region COS host.

Staging receipts are deliberately not verification receipts. Neither operation
changes business references or deletes source files.
"""
import json
import mimetypes
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from app.core.storage.cos import ObjectMissing, StorageError, file_digest, validate_key
from app.core.time import beijing_now

_JOURNAL_LOCK = Lock()


def validate_manifest(manifest, store):
    if manifest.get('version') != 1 or not store.prefix.endswith('/' + manifest['domain']):
        raise ValueError('Manifest destination mismatch')
    names = [validate_key(row['relative_path']) for row in manifest['files']]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate manifest keys')
    for row in manifest['files']:
        if row['size'] < 0 or len(row['sha256']) != 64:
            raise ValueError('Invalid manifest digest/size')


def append_receipt(manifest, row, store, journal, *, verified):
    receipt = {name: manifest[name] for name in ('source_instance', 'domain')}
    receipt.update(relative_path=row['relative_path'], target_bucket=store.bucket,
                   target_key=store.key(row['relative_path']), size=row['size'], sha256=row['sha256'])
    receipt['verified_at' if verified else 'staged_at'] = beijing_now().isoformat()
    with _JOURNAL_LOCK, Path(journal).open('a', encoding='utf-8') as output:
        output.write(json.dumps(receipt, ensure_ascii=False) + '\n')
        output.flush()
        os.fsync(output.fileno())


def stage_one(manifest, row, store, journal):
    validate_manifest({**manifest, 'files': [row]}, store)
    root = Path(manifest['root']).resolve(strict=True)
    key = validate_key(row['relative_path'])
    path = root / key
    if Path(journal).resolve().is_relative_to(root):
        raise ValueError('Journal must be outside source')
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Source escaped root')
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Linked source is not allowed')
    before = path.stat()
    if file_digest(path) != (row['size'], row['sha256']):
        raise StorageError('Source differs from immutable manifest')
    try:
        metadata = store.head(key)
    except ObjectMissing:
        store.put_file(key, path, mimetypes.guess_type(key)[0] or 'application/octet-stream')
        metadata = store.head(key)
    if (int(metadata.get('Content-Length', -1)), metadata.get('x-cos-meta-sha256')) != (row['size'], row['sha256']):
        raise StorageError('Existing destination does not match manifest')
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise StorageError('Source changed while staging')
    append_receipt(manifest, row, store, journal, verified=False)


def verify_one(manifest, row, store, journal, cache_root):
    validate_manifest({**manifest, 'files': [row]}, store)
    source_root = Path(manifest['root']).resolve()
    if Path(journal).resolve().is_relative_to(source_root) or Path(cache_root).resolve().is_relative_to(source_root):
        raise ValueError('Verification output must be outside source')
    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='migration-verify-', dir=cache_root) as directory:
        result = store.download(validate_key(row['relative_path']), Path(directory) / 'object',
                                max_bytes=max(1, row['size']), expected_sha256=row['sha256'])
        if result.size != row['size']:
            raise StorageError('Destination size differs from manifest')
    append_receipt(manifest, row, store, journal, verified=True)
