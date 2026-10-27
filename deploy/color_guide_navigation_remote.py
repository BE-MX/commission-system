"""Apply a fixed navigation commit, preserving a clean checkout and recovery evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import remote_static

ROOT = Path('/home/ubuntu/commission-system')
STATE = ROOT / '.deploy_state/color-guide-navigation'
STATIC_ROOT = Path('/var/www/ark-dist')
PATHS = ('frontend/src/config/navigation.js', 'backend/app/system/navigation_access_manifest.json')
URL = 'https://color-guide.leshine.cloud/'
ALLOWED_PATHS = frozenset((*PATHS,
    'deploy/color_guide_navigation.py', 'deploy/color_guide_navigation_remote.py',
    'deploy/color_guide_site.py', 'deploy/color_guide_site_remote.py',
    'deploy/nginx/color-guide.conf.template', 'deploy/tests/test_color_guide_navigation.py',
    'deploy/tests/test_color_guide_site.py', 'deploy/publish.py', 'deploy/platforms.json',
    'deploy/remote_static.py', 'deploy/static_sync.py', 'deploy/README.md',
    'deploy/color-guide.md', 'docs/handoff.md'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, content, mode=0o600):
    temporary = path.with_name(path.name + '.color-guide-next')
    temporary.write_bytes(content)
    temporary.chmod(mode)
    os.replace(temporary, path)


def git(*args):
    # Preserve the existing checkout/index/object ownership during sudo execution.
    return subprocess.check_output(['sudo', '-n', '-u', 'ubuntu', 'git', '-C', str(ROOT), *args])


def validate_payload(request):
    if request.get('schema') != 2 or any(not re.fullmatch(r'[0-9a-f]{40}', request.get(key, ''))
                                       for key in ('baseline', 'candidate')):
        raise ValueError('Expected a fixed schema-2 navigation candidate')
    if request['baseline'] == request['candidate'] or set(request['files']) != set(PATHS):
        raise ValueError('Unexpected navigation release scope')
    for row in request['files'].values():
        if set(row) != {'before', 'after'} or any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in row.values()):
            raise ValueError('Navigation file digest is invalid')
    expected_bundle = '/tmp/ark-color-guide-' + request['candidate'] + '.bundle'
    if request.get('bundle') != expected_bundle or not re.fullmatch(r'[0-9a-f]{64}', request.get('bundle_sha256', '')):
        raise ValueError('Unexpected bundle path or digest')


def inspect(request):
    actual = git('rev-parse', 'HEAD').decode().strip()
    if actual != request['baseline']:
        raise RuntimeError('Beijing application baseline changed')
    if git('status', '--porcelain', '--untracked-files=no').strip():
        raise RuntimeError('Beijing checkout has tracked changes')
    if (STATE / 'pending.json').exists():
        raise RuntimeError('Interrupted navigation release: inspect retained backups and live files before recovery')
    for name, row in request['files'].items():
        path = ROOT / name
        remote_static.no_links(path)
        if digest(path.read_bytes()) != row['before']:
            raise RuntimeError('Navigation baseline drift: ' + name)
    live = json.loads((STATIC_ROOT / 'nav-manifest.json').read_text())
    if live['git_sha'] != request['baseline']:
        raise RuntimeError('Frontend and backend baseline differ')
    _, current, base = remote_static.layout(STATIC_ROOT)
    if not current.is_symlink():
        raise RuntimeError('Expected a managed frontend release')
    bundle = Path(request['bundle'])
    remote_static.no_links(bundle)
    bundle_digest = digest(bundle.read_bytes()) if bundle.exists() else None
    return {'static_artifact': base.name, 'baseline': actual, 'bundle_sha256': bundle_digest}


def validate_candidate(request):
    git('merge-base', '--is-ancestor', request['baseline'], request['candidate'])
    changed = set(git('diff', '--name-only', request['baseline'], request['candidate']).decode().splitlines())
    if not set(PATHS) <= changed or changed - ALLOWED_PATHS:
        raise ValueError('Candidate changes exceed the reviewed navigation/site deployment scope')
    for line in git('ls-tree', '-r', request['candidate'], '--', *sorted(changed)).decode().splitlines():
        mode, kind, _ = line.split(None, 2)
        if mode not in {'100644', '100755'} or kind != 'blob':
            raise ValueError('Changed paths must be regular source files')
    decoded = {}
    for name, row in request['files'].items():
        old = git('show', request['baseline'] + ':' + name)
        new = git('show', request['candidate'] + ':' + name)
        if digest(old) != row['before'] or digest(new) != row['after']:
            raise ValueError('Committed navigation content digest mismatch')
        decoded[name] = new
    manifest = json.loads(decoded[PATHS[1]])
    if manifest['source_sha256'] != digest(decoded[PATHS[0]]):
        raise ValueError('Navigation manifest does not match source')
    expected = [{}, {}, {'anyPermission': ['colorwork_download:read', 'colorwork_edit:read', 'colorwork_master:read']}]
    if manifest['favorite_access'].get(URL) != expected:
        raise ValueError('Color guide must retain the colorwork group permissions')
    return decoded


def verify_checkout(revision, files, field):
    if git('rev-parse', 'HEAD').decode().strip() != revision or git('status', '--porcelain', '--untracked-files=no').strip():
        raise RuntimeError('Navigation checkout is not the expected clean commit')
    for name, row in files.items():
        remote_static.no_links(ROOT / name)
        if digest((ROOT / name).read_bytes()) != row[field]:
            raise RuntimeError('Navigation readback mismatch')


def execute(request):
    validate_payload(request)
    before = inspect(request)
    if request['phase'] == 'plan':
        return before
    if before['bundle_sha256'] != request['bundle_sha256']:
        raise ValueError('Transferred Git bundle digest mismatch')
    if request['phase'] == 'stage':
        git('bundle', 'verify', request['bundle'])
        git('fetch', '--no-tags', request['bundle'], 'HEAD')
        if git('rev-parse', 'FETCH_HEAD').decode().strip() != request['candidate']:
            raise ValueError('Bundle HEAD differs from the approved candidate')
        validate_candidate(request)
        return {'status': 'staged', 'candidate': request['candidate']}
    if request['phase'] != 'activate':
        raise ValueError('Unknown navigation phase')
    decoded = validate_candidate(request)
    static = request['static']
    if static['root'] != str(STATIC_ROOT) or static['host'] != 'leshine.cloud' or static['expected'] != before['static_artifact']:
        raise ValueError('Unexpected frontend target or baseline')
    remote_static.validate_manifest(static['manifest'])
    static_state, _, _ = remote_static.layout(STATIC_ROOT)
    candidate = static_state / 'versions' / remote_static.artifact_id(static['manifest'])
    if not remote_static.matching(candidate, 'nav-manifest.json', static['manifest']['nav-manifest.json']):
        raise ValueError('Staged navigation manifest differs from the fixed artifact')
    built = json.loads((candidate / 'nav-manifest.json').read_text())
    if built.get('git_sha') != request['candidate'] or built.get('favorite_access') != json.loads(decoded[PATHS[1]])['favorite_access']:
        raise ValueError('Staged frontend does not belong to the approved navigation candidate')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = STATE / uuid.uuid4().hex
    backup.mkdir(mode=0o700)
    for index, name in enumerate(PATHS):
        atomic(backup / str(index), (ROOT / name).read_bytes())
    record = {**request, 'backup': str(backup), 'status': 'applying'}
    atomic(STATE / 'pending.json', json.dumps(record).encode())
    try:
        git('checkout', '--detach', request['candidate'])
        verify_checkout(request['candidate'], request['files'], 'after')
        result = remote_static.activate(STATIC_ROOT, static['manifest'], static['expected'], static['host'])
        verify_checkout(request['candidate'], request['files'], 'after')
    except Exception:
        _, _, active = remote_static.layout(STATIC_ROOT)
        if active.name != static['expected']:
            raise RuntimeError('Frontend changed during failed activation; preserve candidate and pending evidence') from None
        # A dirty/partially switched checkout is an uncertain result, not permission
        # to overwrite work. Leave the journal for explicit inspected recovery.
        head = git('rev-parse', 'HEAD').decode().strip()
        if head not in {request['baseline'], request['candidate']} or git('status', '--porcelain', '--untracked-files=no').strip():
            raise RuntimeError('Checkout drift prevents automatic rollback; pending evidence retained') from None
        git('checkout', '--detach', request['baseline'])
        verify_checkout(request['baseline'], request['files'], 'before')
        record['status'] = 'rolled_back'
        atomic(backup / 'result.json', json.dumps(record).encode())
        (STATE / 'pending.json').unlink()
        raise
    record.update(status='succeeded', artifact=result['artifact'], checkout_clean=True)
    atomic(STATE / 'success.json', json.dumps(record).encode())
    (STATE / 'pending.json').unlink()
    return {'status': 'succeeded', 'baseline': request['baseline'], 'candidate': request['candidate'],
            'artifact': result['artifact'], 'checkout_clean': True,
            'scope': 'Beijing frontend and navigation candidate only', 'backend_restarted': False}


if __name__ == '__main__':
    import fcntl
    with (ROOT / '.deploy_state/backend.lock').open('a') as backend_lock:
        fcntl.flock(backend_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with remote_static.locked(STATIC_ROOT):
            print(json.dumps(execute(json.load(sys.stdin))))
