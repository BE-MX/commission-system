"""Resumable copy-only migration; no DB updates, source deletes or cloud overwrite."""
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.storage.cos import ObjectMissing, StorageError, file_digest, validate_key
from app.core.time import beijing_now

logger = logging.getLogger('commission')


def inventory(root: Path, *, domain: str, source_instance: str) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir() or not source_instance:
        raise ValueError('An existing directory and source instance are required')
    files = []
    # walk reports inaccessible directories instead of silently omitting them.
    import os
    def fail(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('Links/junctions require explicit source resolution')
        for name in names:
            path = Path(directory) / name
            relative = validate_key(path.relative_to(root).as_posix())
            before = path.stat()
            size, sha256 = file_digest(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise StorageError('Source changed during inventory; retry after quiescing writers')
            files.append({'relative_path': relative, 'size': size,
                          'mtime_ns': after.st_mtime_ns, 'sha256': sha256})
    return {'version': 1, 'domain': domain, 'source_instance': source_instance,
            'root': str(root), 'created_at': beijing_now().isoformat(),
            'files': sorted(files, key=lambda row: row['relative_path'])}


def write_manifest(manifest: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A manifest is evidence. Never silently replace an older migration snapshot.
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def copy_manifest(manifest: dict, store, journal: Path, *, cache_root: Path) -> dict:
    import mimetypes
    if manifest.get('version') != 1:
        raise ValueError('Unsupported manifest')
    if not store.prefix.endswith('/' + manifest['domain']):
        raise ValueError('Manifest domain does not match target store')
    root = Path(manifest['root']).resolve(strict=True)
    journal = Path(journal).resolve()
    cache_root = Path(cache_root).resolve()
    if journal.is_relative_to(root) or cache_root.is_relative_to(root):
        raise ValueError('Migration journal and cache must be outside the source root')
    rows = manifest['files']
    names = [validate_key(row['relative_path']) for row in rows]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate object keys in manifest')
    cache_root.mkdir(parents=True, exist_ok=True)
    journal.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    total = 0
    for row in rows:
        name = validate_key(row['relative_path'])
        path = root / name
        if (path.is_symlink() or not path.resolve(strict=True).is_relative_to(root)
                or any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                       for p in [path, *path.parents] if p != root and p.is_relative_to(root))):
            raise ValueError('Source escaped the inventory root')
        if file_digest(path) != (row['size'], row['sha256']):
            raise StorageError('Source differs from manifest; regenerate final inventory')
        exists = True
        try:
            store.head(name)
        except ObjectMissing:
            exists = False
        # Never overwrite a pre-existing object, including different source copies.
        if not exists:
            extra = {'custom_metadata': row['custom_metadata']} if row.get('custom_metadata') else {}
            store.put_file(name, path, row.get('content_type') or mimetypes.guess_type(name)[0] or 'application/octet-stream', **extra)
        if row.get('custom_metadata'):
            head = store.head(name)
            if any(head.get('x-cos-meta-' + key) != value for key, value in row['custom_metadata'].items()):
                raise StorageError('Destination custom metadata mismatch')
        with TemporaryDirectory(prefix='migration-verify-', dir=cache_root) as temporary:
            result = store.download(name, Path(temporary) / 'object',
                                    max_bytes=max(1, row['size']), expected_sha256=row['sha256'])
            if result.size != row['size']:
                raise StorageError('Destination size mismatch')
        receipt = {'source_instance': manifest['source_instance'], 'domain': manifest['domain'],
                   'relative_path': name, 'target_bucket': store.bucket, 'target_key': store.key(name),
                   'size': row['size'], 'sha256': row['sha256'], 'verified_at': beijing_now().isoformat()}
        with journal.open('a', encoding='utf-8') as output:
            output.write(json.dumps(receipt, ensure_ascii=False) + '\n')
            output.flush()
            import os
            os.fsync(output.fileno())
        count += 1
        total += result.size
    return {'verified_files': count, 'verified_bytes': total, 'source_deleted': False,
            'database_changed': False}
