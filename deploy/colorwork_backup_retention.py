"""Retain two recent Colorwork backups plus the successful recovery reference.

Run only on Beijing under the existing backend deployment lock. The live data,
checkouts and migration imports are deliberately outside the writable scope.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import urllib.request

ROOT = Path('/home/ubuntu/commission-system/.deploy_state')
MACHINE = 'fd410411419d40079742fdbc36dec028'
NAME = re.compile(r'[0-9a-f]{40}-[0-9a-f]{32}')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_tree(path, device):
    if path.is_symlink() or path.resolve() != path or path.stat().st_dev != device:
        raise RuntimeError('Unsafe backup path')
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(directory) / name
            st = item.lstat()
            if st.st_dev != device or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise RuntimeError('Unsafe backup entry')


def make_plan(state):
    backups = state / 'backups'
    if backups.resolve() != backups or not backups.is_dir():
        raise RuntimeError('Unsafe backup root')
    journals, refs = {}, []
    for name in ['current.json', 'success.json']:
        path = state / name
        if path.is_symlink():
            raise RuntimeError('Unsafe journal')
        data = json.loads(path.read_text())
        if data.get('status') != 'succeeded':
            raise RuntimeError('Both release journals must be succeeded')
        ref = Path(data['backup'])
        if ref.parent != backups or not ref.is_dir() or ref.is_symlink():
            raise RuntimeError('Recovery reference is missing or outside backups')
        refs.append(data)
        journals[name] = digest(path)
    if any(refs[0].get(k) != refs[1].get(k) for k in ['source', 'backup']):
        raise RuntimeError('Release journals disagree')
    last = state / 'maintenance/retention-last.json'
    if last.is_symlink():
        raise RuntimeError('Unsafe retention journal')
    previous = json.loads(last.read_text()).get('created', {}) if last.exists() else {}
    created, identities = {}, {}
    device = backups.stat().st_dev
    for folder in backups.iterdir():
        if not NAME.fullmatch(folder.name) or not folder.is_dir():
            raise RuntimeError('Unrecognized backup entry')
        safe_tree(folder, device)
        st = folder.stat()
        # A partially deleted directory changes ctime. Preserve its original rank
        # across interrupted cleanup so it cannot become a retained recent backup.
        created[folder.name] = previous.get(folder.name, st.st_ctime_ns)
        if not isinstance(created[folder.name], int):
            raise RuntimeError('Invalid backup ordering journal')
        identities[folder.name] = [st.st_dev, st.st_ino]
    recent = sorted(created, key=lambda n: (created[n], n), reverse=True)[:2]
    keep = set(recent) | {Path(d['backup']).name for d in refs}
    if len(created) < 2:
        raise RuntimeError('Fewer than two recovery backups; preserve all')
    return {'status': 'planned', 'keep': sorted(keep),
            'delete': sorted(set(created) - keep), 'created': created,
            'identities': identities, 'journals': journals, 'deleted': []}


def check_unchanged(state, plan):
    if any(digest(state / name) != expected for name, expected in plan['journals'].items()):
        raise RuntimeError('Release journal changed during retention')
    for name in plan['keep'] + [n for n in plan['delete'] if n not in plan['deleted']]:
        p = state / 'backups' / name
        if p.is_symlink() or not p.is_dir() or [p.stat().st_dev, p.stat().st_ino] != plan['identities'][name]:
            raise RuntimeError('Backup identity changed')


def validate_retained(state, plan):
    for name in plan['keep']:
        folder = state / 'backups' / name
        databases = list(folder.rglob('*.sqlite'))
        if not databases or not any(p.is_file() for p in (folder / 'v3/r2').rglob('*')):
            raise RuntimeError('Retained backup lacks SQLite or R2 data')
        for path in databases:
            connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
            try:
                if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise RuntimeError('Retained backup SQLite validation failed')
            finally:
                connection.close()
        validate_r2(folder / 'v3/r2')


def validate_r2(root):
    """Verify the inspected Miniflare layout, including multipart blob sizes."""
    buckets = 0
    for db in (root / 'miniflare-R2BucketObject').glob('*.sqlite'):
        connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='_mf_objects'").fetchone():
                continue
            buckets += 1
            blobs = connection.execute('SELECT blob_id,size FROM _mf_objects WHERE blob_id IS NOT NULL').fetchall()
            blobs += connection.execute('SELECT blob_id,size FROM _mf_multipart_parts').fetchall()
            for blob, size in blobs:
                if not isinstance(blob, str) or Path(blob).name != blob or not blob:
                    raise RuntimeError('Invalid R2 blob reference')
                path = root / 'site-creator-r2/blobs' / blob
                if not path.is_file() or path.stat().st_size != size:
                    raise RuntimeError('Retained R2 blob missing or size mismatch')
            mismatch = connection.execute('''SELECT COUNT(*) FROM _mf_objects o
                WHERE o.blob_id IS NULL AND o.size != COALESCE(
                  (SELECT SUM(p.size) FROM _mf_multipart_parts p WHERE p.object_key=o.key),0)''').fetchone()[0]
            if mismatch:
                raise RuntimeError('Retained multipart R2 object is incomplete')
        finally:
            connection.close()
    if buckets != 1:
        raise RuntimeError('Unknown R2 storage layout; preserve backups')


def save_receipt(state, plan, name='retention-last.json'):
    folder = state / 'maintenance'
    if folder.resolve() != folder:
        raise RuntimeError('Unsafe maintenance directory')
    path = folder / name
    temporary = folder / (name + '.tmp')
    # Only the deployment-lock holder writes this receipt.
    if temporary.is_symlink():
        raise RuntimeError('Unsafe receipt staging path')
    temporary.write_text(json.dumps(plan, indent=2))
    temporary.chmod(0o600)
    os.replace(temporary, path)


def apply_plan(state, plan):
    check_unchanged(state, plan)
    if {p.name for p in (state / 'backups').iterdir()} != set(plan['created']):
        raise RuntimeError('Backup set changed')
    validate_retained(state, plan)
    plan['status'] = 'running'
    save_receipt(state, plan)
    for name in plan['delete']:
        check_unchanged(state, plan)
        path = state / 'backups' / name
        safe_tree(path, (state / 'backups').stat().st_dev)
        shutil.rmtree(path)
        plan['deleted'].append(name)
        save_receipt(state, plan)
    plan['status'] = 'completed'
    save_receipt(state, plan)
    return plan


def verify_service():
    for unit in ['ark-backend', 'ark-colorwork']:
        subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True)
    with urllib.request.urlopen('http://127.0.0.1:8787/api/colorwork/workbench/api/health', timeout=8) as response:
        if response.status != 200 or json.load(response) != {'status': 'ok', 'module': 'colorwork'}:
            raise RuntimeError('Colorwork is not healthy')


def verify_unused(state, plan):
    candidates = [str(state / 'backups' / n) for n in plan['delete']]
    prefixes = tuple(p + '/' for p in candidates)
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        mount = line.split()[4].replace('\\040', ' ')
        if mount in candidates or mount.startswith(prefixes):
            raise RuntimeError('Mounted backup cannot be removed')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for link in [process / 'cwd', *list((process / 'fd').iterdir())]:
                try:
                    dest = os.readlink(link)
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if dest in candidates or dest.startswith(prefixes):
                    raise RuntimeError('Backup is in use by a process')
        except (FileNotFoundError, ProcessLookupError):
            continue


def run_cleanup(apply=False):
    import fcntl
    if Path('/etc/machine-id').read_text().strip() != MACHINE:
        raise RuntimeError('Unexpected target machine')
    if ROOT.resolve() != ROOT or not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('Unsafe runtime or state directory')
    with (ROOT / 'backend.lock').open('r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'skipped', 'reason': 'deployment-in-progress'}
        verify_service()
        state = ROOT / 'colorwork'
        plan = make_plan(state)
        verify_unused(state, plan)
        validate_retained(state, plan)
        return apply_plan(state, plan) if apply else plan


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = run_cleanup(args.apply)
    if args.apply:
        # Separate from the ordering/deletion journal: a skipped run must not
        # overwrite recovery evidence or be mistaken for an older completed run.
        outcome = {key: result[key] for key in ['status', 'keep', 'deleted', 'reason'] if key in result}
        outcome['invocation_id'] = os.environ.get('INVOCATION_ID')
        outcome['installation_id'] = os.environ.get('ARK_RETENTION_INSTALL_ID')
        outcome['script_sha256'] = digest(Path(__file__))
        save_receipt(ROOT / 'colorwork', outcome, 'retention-outcome.json')
    print(json.dumps(result))
