"""Manifest based retention; timestamps are epoch protocol values, never file mtimes."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import uuid

GRACE_SECONDS = 7 * 24 * 60 * 60
ROLLBACK_COUNT = 2


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_relative(name):
    if not isinstance(name, str):
        raise ValueError('Unsafe artifact path')
    path = PurePosixPath(name)
    if (not name or str(path) != name or path.is_absolute() or '..' in path.parts
            or '\\' in name or ':' in name or any(part.startswith('.') for part in path.parts)
            or name == 'release.json'):
        raise ValueError('Unsafe artifact path')
    return path


def validate_manifest(files):
    if not isinstance(files, dict) or 'index.html' not in files:
        raise ValueError('Static artifact must include index.html')
    for name, digest in files.items():
        safe_relative(name)
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid artifact digest')


def artifact_id(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def no_links(path):
    for item in (path, *path.parents):
        try:
            observed = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(observed.st_mode) or (getattr(observed, 'st_file_attributes', 0)
                                             & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Unexpected symlink/reparse point: ' + str(item))


def matching(base, name, digest):
    path = base / name
    no_links(path)
    return path.is_file() and sha(path) == digest


def verify(base, files):
    validate_manifest(files)
    if not all(matching(base, name, digest) for name, digest in files.items()):
        raise ValueError('Missing/corrupt retained release: ' + str(base))


def atomic_json(path, data):
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.next-' + uuid.uuid4().hex)
    temporary.write_text(json.dumps(data, sort_keys=True), encoding='utf-8')
    os.replace(temporary, path)


def read_history(path):
    no_links(path)
    if not path.exists():
        return {'schema': 1, 'releases': {}}
    result = json.loads(path.read_text(encoding='utf-8'))
    if result.get('schema') != 1 or not isinstance(result.get('releases'), dict):
        raise ValueError('Unknown static retention history')
    for row in result['releases'].values():
        validate_manifest(row['files'])
        retired = row['retired_at']
        if retired is not None and (type(retired) not in {int, float} or retired <= 0):
            raise ValueError('Invalid release retirement time')
    return result


def asset_union(manifests):
    assets = {}
    for files in manifests:
        validate_manifest(files)
        for name, digest in files.items():
            if name.startswith('assets/'):
                if name in assets and assets[name] != digest:
                    raise ValueError('Asset name reused with different bytes: ' + name)
                assets[name] = digest
    return assets


def walk_files(root):
    no_links(root)
    if not root.exists():
        return
    for folder, dirs, names in os.walk(root, followlinks=False):
        # The root and every ancestor directory have already been checked.
        with os.scandir(folder) as entries:
            for entry in entries:
                observed = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(observed.st_mode) or (getattr(observed, 'st_file_attributes', 0)
                                                     & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                    raise ValueError('Unexpected symlink/reparse point: ' + entry.path)
                if stat.S_ISREG(observed.st_mode):
                    yield Path(entry.path), observed.st_size
                elif not stat.S_ISDIR(observed.st_mode):
                    raise ValueError('Unexpected static file type: ' + entry.path)


def plan_cleanup(kept, removed, assets, asset_sources=()):
    """Validate everything first, including all deletion paths and protected bytes."""
    copies, deletes, size = [], [], 0
    sources = {}
    for folder, files in kept:
        verify(folder, files)
    for name, digest in assets.items():
        sources[name] = next((folder / name for folder in [*(p for p, _ in kept), *asset_sources]
                              if matching(folder, name, digest)), None)
        if sources[name] is None:
            raise ValueError('Protected browser asset missing: ' + name)
    for folder, _ in kept:
        for name, digest in assets.items():
            destination = folder / name
            no_links(destination)
            if destination.exists():
                if sha(destination) != digest:
                    raise ValueError('Retained asset checksum mismatch: ' + name)
            else:
                copies.append((sources[name], destination))
        for path, length in walk_files(folder / 'assets'):
            if path.relative_to(folder).as_posix() not in assets:
                deletes.append(path)
                size += length
    for folder in removed:
        for _, length in walk_files(folder):
            size += length
        deletes.append(folder)
    return {'copies': copies, 'deletes': deletes, 'bytes': size,
            'copy_bytes': sum(source.stat().st_size for source, _ in copies),
            'kept': [str(folder) for folder, _ in kept],
            'removed': [str(folder) for folder in removed], 'assets': len(assets)}


def apply_cleanup(plan, allowed_roots):
    """Paths are prevalidated, strictly bounded, and never passed to another shell."""
    for path in plan['deletes']:
        no_links(path)
        resolved = path.resolve()
        if not any(resolved != root.resolve() and resolved.is_relative_to(root.resolve())
                   for root in allowed_roots):
            raise ValueError('Cleanup escaped allowed root: ' + str(path))
    for source, destination in plan['copies']:
        no_links(source)
        no_links(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.next-' + uuid.uuid4().hex)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    # Windows uses native LiteralPath deletion end-to-end. No cmd expansion.
    if os.name == 'nt' and plan['deletes']:
        command = ('$ErrorActionPreference="Stop"; '
                   '$targets=[Console]::In.ReadToEnd() | ConvertFrom-Json; '
                   'foreach ($target in $targets) { '
                   'if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force } }')
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                       input=json.dumps([str(p.resolve()) for p in plan['deletes']]),
                       text=True, check=True, timeout=1200)
    else:
        for path in plan['deletes']:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
    return summary(plan)


def summary(plan):
    return {key: plan[key] for key in ('bytes', 'kept', 'removed', 'assets')} | {
        'delete_paths': len(plan['deletes']), 'copy_files': len(plan['copies']),
        'copy_bytes': plan['copy_bytes']}
