"""Stage/activate only the inspected outbound mirror, preserving the existing cron."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/root/.openclaw/workspace/okki-sync')
NODE = '/root/.nvm/versions/node/v22.22.1/bin/node'
NAMES = ('inspection-contract.mjs', 'outbound-store.mjs', 'sync-outbound.js')


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def save(path, value):
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


@contextmanager
def mirror_lock():
    import fcntl
    with open('/tmp/okki-outbound.lock', 'a') as lock:
        deadline = time.monotonic() + 45
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Outbound synchronization has not drained')
                time.sleep(0.2)
        try:
            # Manual/daily invocations may not use the cron lock.
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit():
                    continue
                try:
                    args = (proc / 'cmdline').read_bytes().split(b'\0')
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
                if args and Path(os.fsdecode(args[0])).name == 'node' and any(Path(os.fsdecode(arg)).name in {'sync-outbound.js', 'resync-outbound-by-order.js'} for arg in args[1:]):
                    raise RuntimeError('A manual outbound sync is still running; retry after it exits')
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def execute(request):
    ensure_tree(ROOT)
    with release_lock():
        return execute_locked(request)


def ensure_tree(path):
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError("Deployment path symlink rejected")
    if path != ROOT and not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Deployment path escapes outbound root")


@contextmanager
def release_lock():
    import fcntl
    path = ROOT / ".ark-outbound-release.lock"
    ensure_tree(path)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def execute_locked(request):
    if request.get('action') not in {'prepare', 'activate'} or set(request.get('files', {})) != set(NAMES) or set(request.get('expected_live', {})) != set(NAMES):
        raise ValueError('Invalid outbound mirror release request')
    bodies = {}
    for name in NAMES:
        value = request['files'][name]
        body = base64.b64decode(value['content'], validate=True)
        if hashlib.sha256(body).hexdigest() != value['sha256']:
            raise ValueError('Outbound mirror artifact digest mismatch')
        expected = request['expected_live'][name]
        if expected is not None and (not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
            raise ValueError('Invalid inspected live digest')
        bodies[name] = body
    digest = hashlib.sha256(json.dumps({name: request['files'][name]['sha256'] for name in sorted(NAMES)}, sort_keys=True).encode()).hexdigest()
    stage = ROOT / '.deploy-state' / 'ark-sync' / digest
    if ROOT.is_symlink() or stage.resolve().parent != (ROOT / '.deploy-state' / 'ark-sync').resolve():
        raise ValueError('Unexpected outbound staging path')
    ensure_tree(stage)
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = stage / 'release.json'
    ensure_tree(journal)
    ensure_tree(journal.with_suffix('.next'))
    state = json.loads(journal.read_text()) if journal.exists() else None
    def check_live(expected):
        for name in NAMES:
            path = ROOT / name
            if path.is_symlink() or digest_file(path) != expected[name]:
                raise RuntimeError('Live outbound mirror changed since review: ' + name)
    candidate = {name: request['files'][name]['sha256'] for name in NAMES}
    if state and state.get('status') == 'verified':
        check_live(candidate)
        return {'status': 'verified', 'digest': digest, 'target': str(ROOT)}
    if state and state.get('status') not in {'prepared', 'rolled_back'}:
        raise RuntimeError('Previous outbound activation requires inspection')
    check_live(request['expected_live'])
    for name, body in bodies.items():
        path = stage / name
        if path.is_symlink():
            raise ValueError('Staging symlink rejected')
        path.write_bytes(body)
        os.chmod(path, 0o600)
        subprocess.run([NODE, '--check', str(path)], check=True, capture_output=True, timeout=20)
    if request['action'] == 'prepare':
        save(journal, {'status': 'prepared', 'digest': digest, 'expected_live': request['expected_live']})
        return {'status': 'prepared', 'digest': digest, 'target': str(ROOT)}
    if not state or state.get('status') != 'prepared' or state.get('expected_live') != request['expected_live']:
        raise RuntimeError('An identical prepared release is required before activation')
    with mirror_lock():
        check_live(request['expected_live'])
        backup = stage / 'backup'
        ensure_tree(backup)
        backup.mkdir(mode=0o700, exist_ok=True)
        for name in NAMES:
            ensure_tree(backup / name)
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, backup / name)
        save(journal, {'status': 'activating', 'digest': digest, 'expected_live': request['expected_live']})
        changed = []
        try:
            # Helpers first, entry last: no old entry imports half an artifact.
            for name in NAMES:
                temporary = ROOT / ('.ark-sync-' + name + '.next')
                if temporary.is_symlink():
                    raise ValueError('Activation symlink rejected')
                temporary.write_bytes(bodies[name])
                os.chmod(temporary, 0o600)
                os.replace(temporary, ROOT / name)
                changed.append(name)
            check_live(candidate)
            save(journal, {'status': 'verified', 'digest': digest, 'expected_live': request['expected_live']})
        except Exception:
            for name in reversed(changed):
                if (backup / name).is_file():
                    shutil.copy2(backup / name, ROOT / name)
                else:
                    (ROOT / name).unlink()
            save(journal, {'status': 'rolled_back', 'digest': digest, 'expected_live': request['expected_live']})
            raise
    return {'status': 'verified', 'digest': digest, 'target': str(ROOT)}


if __name__ == '__main__':
    import sys
    try:
        print(json.dumps(execute(json.loads(sys.stdin.read()))))
    except Exception as error:
        print('Outbound mirror release failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
