"""Verified, differential static releases; executed on Linux over SSH."""

from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

ROOTS = {
    "/var/www/ark/dist", "/var/www/ark-dist", "/var/www/pm/dist",
    "/var/www/pm-dist", "/var/www/hair-styles", "/var/www/video.leshine.work",
    "/var/www/video-styles", "/var/www/ark-static/customer-media",
    "/var/www/ark-static/customer-orders",
}


from static_retention import (sha, safe_relative, validate_manifest, artifact_id,
    no_links, matching)
import static_retention as retention


def release_history(state, base, now):
    path = state / 'retention-history.json'
    history = retention.read_history(path)
    rows = history['releases']
    for ident, row in rows.items():
        if not re.fullmatch(r'[0-9a-f]{64}', ident) or artifact_id(row['files']) != ident:
            raise ValueError('Retention history artifact mismatch')
        if type(row.get('activated')) is not bool:
            raise ValueError('Invalid activation state')
    # Existing release manifests prove bytes, but not retirement time. Preserve
    # all legacy versions for a full grace window from this one-time bootstrap.
    for folder in (state / 'versions').iterdir():
        if not re.fullmatch(r'[0-9a-f]{64}', folder.name):
            continue
        no_links(folder)
        if folder.name in rows:
            continue
        record = folder / 'release.json'
        no_links(record)
        data = json.loads(record.read_text())
        validate_manifest(data['files'])
        if artifact_id(data['files']) != folder.name or data['artifact'] != folder.name:
            raise ValueError('Corrupt historical release manifest')
        rows[folder.name] = {'files': data['files'], 'retired_at': now,
                             'activated': True, 'legacy_grace': True}
    if base.name in rows:
        rows[base.name]['retired_at'] = None
        rows[base.name]['activated'] = True
    return history


def record_activation(state, base, candidate, files):
    now = time.time()
    history = release_history(state, base, now)
    rows = history['releases']
    if base != candidate and base.name in rows:
        rows[base.name]['retired_at'] = now
        rows[base.name].pop('legacy_grace', None)
    rows[candidate.name] = {'files': files, 'retired_at': None, 'activated': True}
    retention.atomic_json(state / 'retention-history.json', history)


def record_prepared(state, base, ident, files, new=False):
    history = release_history(state, base, time.time())
    if new:
        history['releases'][ident] = {'files': files, 'retired_at': None, 'activated': False}
    row = history['releases'].setdefault(ident, {'files': files, 'retired_at': None, 'activated': False})
    row['prepared'] = True
    retention.atomic_json(state / 'retention-history.json', history)


def cleanup(root, host, prepare_only=False, rollback_hints=()):
    state, current, base = layout(root)
    if not root.is_symlink() or not current.is_symlink():
        raise ValueError('Retention requires an initialized static release')
    now = time.time()
    history = release_history(state, base, now)
    rows = history['releases']
    current_files = rows[base.name]['files']
    retention.verify(base, current_files)
    verify_http(current_files, host)
    previous = state / 'previous'
    rollback = []
    if previous.is_symlink():
        target = Path(os.readlink(previous))
        if target.parent != state / 'versions' or target.name not in rows or not target.is_dir():
            raise ValueError('Invalid previous release pointer')
        no_links(target)
        if target != base:
            rollback.append(target.name)
    elif previous.exists():
        raise ValueError('Previous must be a managed pointer')
    retired = sorted((ident for ident, row in rows.items() if row.get('activated')
                      and row['retired_at'] is not None),
                     key=lambda ident: (rows[ident]['retired_at'], ident), reverse=True)
    recorded = [ident for ident in retired if not rows[ident].get('legacy_grace')]
    hints = list(rollback_hints) + history.get('rollback', [])
    if any(not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{64}', ident) for ident in hints):
        raise ValueError('Invalid rollback artifact hint')
    # Office retirement order resolves legacy ties for the shared frontend.
    # Hints only fill gaps; genuine cloud retirement history takes precedence.
    for ident in [*recorded, *hints, *retired]:
        if len(rollback) >= retention.ROLLBACK_COUNT:
            break
        if ident not in rollback and ident != base.name and (state / 'versions' / ident).is_dir():
            if ident not in rows:
                raise ValueError('Rollback hint has no verified manifest')
            rollback.append(ident)
    history['rollback'] = rollback
    grace = [row['files'] for row in rows.values() if row.get('activated')
             and row['retired_at'] is not None and row['retired_at'] >= now - retention.GRACE_SECONDS]
    protected = [base.name, *rollback]
    assets = retention.asset_union([rows[ident]['files'] for ident in protected] + grace)
    removed, extra_kept = [], []
    for folder in (state / 'versions').iterdir():
        if folder.name in protected or not re.fullmatch(r'[0-9a-f]{64}', folder.name):
            continue
        row = rows[folder.name]
        if (row.get('prepared') or not row.get('activated')
                or row.get('legacy_grace') and row['retired_at'] >= now - retention.GRACE_SECONDS):
            extra_kept.append(str(folder))
        else:
            removed.append(folder)
    kept = [(state / 'versions' / ident, rows[ident]['files']) for ident in protected]
    plan = retention.plan_cleanup(kept, removed, assets,
                                  [state / 'versions' / ident for ident in rows
                                   if (state / 'versions' / ident).is_dir()])
    # Unknown legacy/candidate lifecycles get a conservative grace period, but
    # their inherited assets need not duplicate the entire active asset history.
    for name in extra_kept:
        folder = Path(name)
        own = rows[folder.name]['files']
        extra = retention.plan_cleanup([(folder, own)], [], retention.asset_union([own]))
        plan['deletes'].extend(extra['deletes'])
        plan['bytes'] += extra['bytes']
    result = retention.summary(plan) | {'legacy_grace_versions': sum(bool(row.get('legacy_grace'))
             and row['retired_at'] is not None and row['retired_at'] >= now - retention.GRACE_SECONDS
             for row in rows.values()), 'additional_protected': extra_kept}
    if not prepare_only:
        # Persist metadata before deletion; a retry can still rebuild the union.
        retention.atomic_json(state / 'retention-history.json', history)
        retention.atomic_json(state / 'retention-current.json', {'status': 'cleaning', **result})
        retention.apply_cleanup(plan, [state / 'versions'])
        for folder, files in kept:
            retention.verify(folder, files)
        verify_http(current_files, host)
        history['releases'] = {ident: row for ident, row in rows.items()
                               if (state / 'versions' / ident).is_dir()
                               or row['retired_at'] is not None
                               and row['retired_at'] >= now - retention.GRACE_SECONDS}
        retention.atomic_json(state / 'retention-history.json', history)
        retention.atomic_json(state / 'retention-current.json', {'status': 'succeeded', **result})
    return result


def layout(root):
    state = root.parent / ("." + root.name + "-releases")
    no_links(state)
    no_links(state / "versions")
    current = state / "current"
    if current.is_symlink():
        target = Path(os.readlink(current))
        if target.parent != state / "versions" or not re.fullmatch(r"[0-9a-f]{64}", target.name):
            raise ValueError("Release pointer escaped state directory")
        no_links(target)
        if not target.is_dir():
            raise ValueError("Broken release pointer")
    elif current.exists():
        raise ValueError("Current must be a managed symlink")
    else:
        target = root
    if root.is_symlink():
        if os.readlink(root) != str(current) or not current.exists():
            raise ValueError("Root is not a managed release pointer")
    else:
        no_links(root)
    return state, current, target


def plan(root, manifest):
    validate_manifest(manifest)
    state, current, base = layout(root)
    active = current.resolve().name if current.exists() else None
    candidate = state / "versions" / artifact_id(manifest)
    no_links(candidate)
    staged = candidate.is_dir() and all(matching(candidate, n, h) for n, h in manifest.items())
    if candidate.exists() and not staged:
        raise ValueError("Existing release is corrupt")
    return {"missing": [n for n, h in manifest.items() if not matching(base, n, h)],
            "artifact": artifact_id(manifest), "active_artifact": active,
            "initialized": root.is_symlink(), "staged": staged}


def retain_assets(base, candidate):
    assets = base / "assets"
    no_links(assets)
    if not assets.exists():
        return
    for old in assets.rglob("*"):
        no_links(old)
        if old.is_file():
            destination = candidate / old.relative_to(base)
            no_links(destination)
            if destination.exists():
                if sha(old) != sha(destination):
                    raise ValueError("Asset name reused with different bytes: " + old.name)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(old, destination)
                destination.chmod(0o644)


def stage(root, manifest, archive):
    validate_manifest(manifest)
    state, _, base = layout(root)
    ident = artifact_id(manifest)
    candidate = state / "versions" / ident
    no_links(candidate)
    if candidate.exists():
        if not all(matching(candidate, n, h) for n, h in manifest.items()):
            raise ValueError("Existing release is corrupt")
        # Also on rollback A->B->A: append B's chunks before serving A again.
        retain_assets(base, candidate)
        record_prepared(state, base, ident, manifest)
        return {"artifact": ident}
    candidate.parent.mkdir(parents=True, exist_ok=True)
    state.chmod(0o755)
    candidate.parent.chmod(0o755)
    incoming = state / ("incoming-" + uuid.uuid4().hex)
    incoming.mkdir(mode=0o755)
    seen = set()
    no_links(archive)
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            safe_relative(member.name)
            if not member.isfile() or member.name not in manifest or member.name in seen:
                raise ValueError("Unexpected/duplicate bundle member")
            seen.add(member.name)
            destination = incoming / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out)
            if sha(destination) != manifest[member.name]:
                raise ValueError("Transfer checksum mismatch: " + member.name)
    for name, digest in manifest.items():
        if not matching(incoming, name, digest):
            if not matching(base, name, digest):
                raise ValueError("Missing/corrupt file: " + name)
            (incoming / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / name, incoming / name)
    retain_assets(base, incoming)
    (incoming / "release.json").write_text(json.dumps({"artifact": ident, "files": manifest}, sort_keys=True))
    for path in [incoming, *incoming.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    incoming.rename(candidate)
    record_prepared(state, base, ident, manifest, new=True)
    return {"artifact": ident}


def pointer(path, target):
    temporary = path.parent / (path.name + ".next-" + uuid.uuid4().hex)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, path)


def exchange(left, right):
    # Linux renameat2 swaps the original directory and prepared symlink atomically.
    libc = ctypes.CDLL(None, use_errno=True)
    operation = libc.renameat2
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    if operation(-100, os.fsencode(left), -100, os.fsencode(right), 2):
        raise OSError(ctypes.get_errno(), "Atomic root exchange failed")


def verify_http(manifest, host):
    if not re.fullmatch(r"(?:[a-z-]+\.)?leshine\.(?:cloud|work)", host):
        raise ValueError("Unregistered verification host")
    content = subprocess.check_output(["curl", "--fail", "--silent", "--show-error",
        "--max-time", "30", "--resolve", host + ":443:127.0.0.1",
        "https://" + host + "/index.html"], timeout=40)
    if hashlib.sha256(content).hexdigest() != manifest["index.html"]:
        raise RuntimeError("Nginx is not serving the selected artifact for " + host)


def activate(root, manifest, expected, host=None):
    validate_manifest(manifest)
    state, current, base = layout(root)
    candidate = state / "versions" / artifact_id(manifest)
    no_links(candidate)
    active = current.resolve().name if current.exists() else None
    if active != expected and active != candidate.name:
        raise ValueError("Another publisher changed this target after preparation")
    if not all(matching(candidate, n, h) for n, h in manifest.items()):
        raise ValueError("Release verification failed before activation")
    if active == candidate.name and root.is_symlink():
        if host:
            verify_http(manifest, host)
        record_activation(state, base, candidate, manifest)
        return {"status": "unchanged", "artifact": active}
    retain_assets(base, candidate)
    if active:
        pointer(state / "previous", base)
    pointer(current, candidate)
    legacy = None
    initialized = root.is_symlink()
    if not initialized:
        swap = root.parent / ("." + root.name + "-switch-" + uuid.uuid4().hex)
        swap.symlink_to(current, target_is_directory=True)
        try:
            if root.exists():
                exchange(root, swap)
                legacy = state / ("legacy-" + uuid.uuid4().hex)
                swap.rename(legacy)
            else:
                os.replace(swap, root)
        except Exception:
            if swap.is_symlink():
                swap.unlink()
                if active:
                    pointer(current, base)
                else:
                    current.unlink()
            raise
    try:
        if host:
            verify_http(manifest, host)
    except Exception:
        if active:
            pointer(current, base)
        elif legacy:
            exchange(root, legacy)
            legacy.unlink()
            current.unlink()
        else:
            root.unlink()
            current.unlink()
        raise
    record_activation(state, base, candidate, manifest)
    return {"status": "updated", "artifact": candidate.name}


@contextmanager
def locked(root):
    import fcntl
    state, _, _ = layout(root)
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o755)
    lock = state / "publish.lock"
    no_links(lock)
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    request = json.load(sys.stdin)
    root = Path(request["root"])
    if str(root) not in ROOTS:
        raise ValueError("Unregistered static root")
    with locked(root):
        action = request["action"]
        if action == "plan":
            result = plan(root, request["manifest"])
        elif action == "stage":
            archive = Path(request["archive"])
            if not re.fullmatch(r"/tmp/ark-static-[0-9a-f]{64}\.tar\.gz", str(archive)):
                raise ValueError("Unregistered transfer archive")
            result = stage(root, request["manifest"], archive)
        elif action == "activate":
            result = activate(root, request["manifest"], request["expected"], request["host"])
        elif action == 'retention':
            result = cleanup(root, request['host'], request.get('prepare_only', False),
                             request.get('rollback_hints', []))
        elif action == 'prepared':
            files = request['manifest']
            validate_manifest(files)
            state, _, base = layout(root)
            ident = artifact_id(files)
            retention.verify(state / 'versions' / ident, files)
            record_prepared(state, base, ident, files)
            result = {'artifact': ident}
        else:
            raise ValueError("Unknown static action")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
