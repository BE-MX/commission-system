"""Publish a runtime dependency update for the existing Beijing Colorwork only."""

import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path('/home/ubuntu/commission-system')
HOST = 'ubuntu@154.8.205.162'
PACKAGE = 'colorwork-workbench/package.json'
LOCK = 'colorwork-workbench/pnpm-lock.yaml'
DEPENDENCY_FILES = {PACKAGE, LOCK}
ALLOWED_FILES = DEPENDENCY_FILES | {
    'colorwork-workbench/pnpm-workspace.yaml',
    'colorwork-workbench/patches/miniflare@4.20260611.0.patch',
    'colorwork-workbench/scripts/test-cos-workerd.mjs',
    'deploy/colorwork_runtime.py', 'deploy/publish.py', 'deploy/README.md',
    'deploy/tests/test_colorwork_runtime.py',
}


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


def validate_candidate(root, baseline, revision):
    if any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha) for sha in (baseline, revision)):
        raise ValueError('Runtime release requires two full Git revisions')
    if git(root, 'rev-list', '--parents', '-n', '1', revision).split() != [revision, baseline]:
        raise ValueError('Runtime candidate must be one commit on the running Colorwork revision')
    changed = set(git(root, 'diff', '--name-only', '--no-renames', baseline, revision).splitlines())
    if not DEPENDENCY_FILES <= changed <= ALLOWED_FILES:
        raise ValueError('Runtime candidate contains changes outside the Colorwork dependency release')
    previous = json.loads(git(root, 'show', baseline + ':' + PACKAGE))
    updated = json.loads(git(root, 'show', revision + ':' + PACKAGE))
    old_version = previous['devDependencies'].pop('wrangler')
    version = updated['devDependencies'].pop('wrangler')
    previous['devDependencies'].pop('@cloudflare/workers-types', None)
    types = updated['devDependencies'].pop('@cloudflare/workers-types', None)
    if (previous != updated or not re.fullmatch(r'\d+\.\d+\.\d+', version)
            or (types is not None and not re.fullmatch(r'\d+\.\d+\.\d+', types))
            or tuple(map(int, version.split('.'))) <= tuple(map(int, old_version.split('.')))):
        raise ValueError('Only pinned Wrangler and its Workers type dependency may change')
    return version


def execute_local(root, baseline, revision, prepare_only):
    from static_sync import remote_python

    if git(root, 'rev-parse', 'HEAD') != revision or git(root, 'status', '--porcelain'):
        raise ValueError('Runtime publication requires the clean pinned candidate')
    validate_candidate(root, baseline, revision)
    request = dict(baseline=baseline, revision=revision, phase='activate')
    if prepare_only:
        with tempfile.TemporaryDirectory(prefix='colorwork-runtime-', dir=root / '.deploy_state') as temporary:
            bundle = Path(temporary) / 'source.bundle'
            git(root, 'bundle', 'create', str(bundle), baseline + '..HEAD')
            data = bundle.read_bytes()
        request.update(phase='prepare', bundle=base64.b64encode(data).decode(),
                       digest=hashlib.sha256(data).hexdigest())
    result = remote_python(HOST, Path(__file__), request, timeout=1500)
    if result.returncode:
        raise RuntimeError(result.stderr[-5500:])
    print(result.stdout.strip(), flush=True)


def wait_ready(release):
    for _ in range(30):
        try:
            release.healthy()
            return
        except (OSError, ValueError, RuntimeError):
            time.sleep(1)
    raise RuntimeError('Colorwork did not become ready')


def activate(state, source, previous, release):
    prepared = json.loads((state / ('prepared-' + source.name + '.json')).read_text())
    new_unit = state / ('unit-' + source.name + '.service')
    old_unit = state / ('unit-' + Path(previous['source']).name + '.service')
    installed = release.UNIT_DIRECTORY / (release.SERVICE + '.service')
    files = release.migration_files(source / 'colorwork-workbench')
    if (prepared['source'] != str(source) or prepared['unit'] != str(new_unit)
            or not files or prepared['migrations'] != files or previous['migrations'] != files):
        raise RuntimeError('Runtime-only release requires identical Colorwork migrations')
    if old_unit.read_bytes() != installed.read_bytes() or not installed.read_text().startswith(release.MANAGED):
        raise RuntimeError('Installed Colorwork unit differs from the successful baseline')
    if new_unit.read_text() != release.unit_text(source / 'colorwork-workbench', state, prepared['node'], 'ubuntu'):
        raise RuntimeError('Prepared Colorwork unit changed')
    data = state / 'data'
    release.verify_history(data, files)
    backup = state / 'backups' / (source.name + '-' + uuid.uuid4().hex)
    staging_backup = state / ('runtime-backup-' + backup.name)
    current = state / 'current.json'
    success = state / 'success.json'
    journal = dict(prepared, backup=str(backup), status='activating', previous_source=previous['source'])

    def service(*args):
        release.run(['sudo', '-n', 'systemctl', *args], ROOT)

    def start(unit):
        release.run(['sudo', '-n', 'install', '-m', '644', unit, installed], ROOT)
        service('daemon-reload')
        service('start', release.SERVICE)
        wait_ready(release)

    release.atomic_json(current, journal)
    try:
        service('stop', release.SERVICE)
        shutil.copytree(data, staging_backup)
        staging_backup.rename(backup)
        start(new_unit)
        journal.update(status='succeeded')
        release.atomic_json(success, journal)
        release.atomic_json(current, journal)
    except Exception:
        journal.update(status='failed')
        try:
            service('stop', release.SERVICE)
            start(old_unit)
        except Exception as error:
            try:
                release.atomic_json(current, journal)
            except OSError as receipt_error:
                print('Could not write failed Colorwork receipt: ' + str(receipt_error), file=sys.stderr)
            raise RuntimeError('Runtime activation and restart of the previous Colorwork unit failed') from error
        release.atomic_json(success, previous)
        release.atomic_json(current, previous)
        journal.update(status='rolled_back')
        release.atomic_json(state / ('runtime-rollback-' + source.name + '.json'), journal)
        raise


def runtime_digest(runtime, node, release):
    script = "process.stdout.write(require('node:module').createRequire(require.resolve('wrangler/package.json')).resolve('miniflare'))"
    miniflare = Path(release.run([node, '-e', script], runtime, True)).resolve()
    if not miniflare.is_relative_to(runtime / 'node_modules'):
        raise RuntimeError('Miniflare is not installed in the candidate')
    files = {
        'miniflare': miniflare.read_bytes(),
        'inspector': (runtime / 'node_modules/wrangler/wrangler-dist/InspectorProxyWorker.js').read_bytes(),
    }
    if b'const r2PublicService = undefined;' not in files['miniflare']:
        raise RuntimeError('Colorwork requires private R2 bindings')
    return {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}


def execute_remote(request):
    import fcntl

    baseline, revision, phase = (request[key] for key in ('baseline', 'revision', 'phase'))
    if phase not in {'prepare', 'activate'} or any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
                                                      for sha in (baseline, revision)):
        raise ValueError('Invalid Colorwork runtime release request')
    deploy = ROOT / '.deploy_state'
    state = deploy / 'colorwork'
    checkouts = deploy / 'checkouts'
    source = checkouts / revision
    with (deploy / 'backend.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = json.loads((state / 'success.json').read_text())
        if (previous != json.loads((state / 'current.json').read_text()) or previous['status'] != 'succeeded'
                or Path(previous['source']) != checkouts / baseline):
            raise RuntimeError('Running Colorwork revision changed or needs recovery')
        if phase == 'prepare':
            data = base64.b64decode(request['bundle'], validate=True)
            if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != request['digest']:
                raise ValueError('Colorwork candidate bundle digest mismatch')
            with tempfile.TemporaryDirectory(prefix='runtime-source-', dir=state) as temporary:
                bundle = Path(temporary) / 'source.bundle'
                bundle.write_bytes(data)
                if git(ROOT, 'bundle', 'list-heads', str(bundle)) != revision + ' HEAD':
                    raise ValueError('Bundle does not point at the pinned candidate')
                git(ROOT, 'bundle', 'verify', str(bundle))
                git(ROOT, 'fetch', '--no-tags', '--no-write-fetch-head', str(bundle), 'HEAD')
        version = validate_candidate(ROOT, baseline, revision)
        if phase == 'prepare' and not source.exists():
            git(ROOT, 'worktree', 'add', '--detach', str(source), revision)
        if source.resolve() != source or git(source, 'rev-parse', 'HEAD') != revision or git(source, 'status', '--porcelain'):
            raise RuntimeError('Colorwork staged source is missing or changed')
        sys.path.insert(0, str(source / 'deploy'))
        import colorwork_release as release

        if phase == 'prepare':
            env = source / 'backend/.env'
            if not env.is_symlink() and not env.exists():
                env.symlink_to(ROOT / 'backend/.env')
            if not env.is_symlink() or env.resolve() != ROOT / 'backend/.env':
                raise RuntimeError('Colorwork settings are not bound to the installed backend')
            release.prepare(ROOT, source, ROOT / 'backend/.venv/bin/python')
        runtime = source / 'colorwork-workbench'
        package = runtime / 'node_modules/wrangler/package.json'
        if json.loads(package.read_text())['version'] != version:
            raise RuntimeError('Installed Wrangler does not match the candidate')
        prepared = json.loads((state / ('prepared-' + revision + '.json')).read_text())
        fingerprints = runtime_digest(runtime, prepared['node'], release)
        receipt = state / ('runtime-input-' + revision + '.json')
        if phase == 'prepare' and not receipt.exists():
            release.atomic_json(receipt, fingerprints)
        if json.loads(receipt.read_text()) != fingerprints:
            raise RuntimeError('Prepared Wrangler runtime changed')
        build = json.loads((state / ('build-' + revision + '.json')).read_text())['files']
        if build != {p.relative_to(runtime / 'dist').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (runtime / 'dist').rglob('*') if p.is_file()}:
            raise RuntimeError('Prepared Colorwork build changed')
        if phase == 'activate':
            activate(state, source, previous, release)
        return {'status': 'prepared' if phase == 'prepare' else 'succeeded', 'revision': revision, 'wrangler': version}


if __name__ == '__main__':
    print(json.dumps(execute_remote(json.load(sys.stdin))))
