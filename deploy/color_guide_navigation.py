"""Publish a fixed, clean navigation candidate without pushing a Git remote."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import static_sync
from color_guide_navigation_remote import ALLOWED_PATHS, PATHS

HERE = Path(__file__).resolve().parent
HOST = 'ubuntu@154.8.205.162'
SCHEMA = 2


def git(source, *args):
    return subprocess.check_output(['git', *args], cwd=source)


def candidate_identity(source, baseline):
    if not isinstance(baseline, str) or not re.fullmatch(r'[0-9a-f]{40}', baseline):
        raise ValueError('Navigation baseline must be a full commit SHA')
    candidate = git(source, 'rev-parse', 'HEAD').decode().strip()
    if candidate == baseline or git(source, 'status', '--porcelain', '--untracked-files=normal').strip():
        raise ValueError('Navigation publication requires a committed, clean candidate')
    subprocess.run(['git', 'merge-base', '--is-ancestor', baseline, candidate], cwd=source, check=True)
    changed = set(git(source, 'diff', '--name-only', baseline, candidate).decode().splitlines())
    if not set(PATHS) <= changed or changed - ALLOWED_PATHS:
        raise ValueError('Candidate contains changes outside the reviewed color-guide scope')
    files = {}
    for name in PATHS:
        old = git(source, 'show', baseline + ':' + name)
        new = git(source, 'show', candidate + ':' + name)
        files[name] = {'before': hashlib.sha256(old).hexdigest(), 'after': hashlib.sha256(new).hexdigest()}
    policy = json.loads(git(source, 'show', candidate + ':' + PATHS[1]))
    if policy['source_sha256'] != files[PATHS[0]]['after']:
        raise ValueError('Committed navigation source and policy differ')
    dist = source / 'frontend/dist'
    built = json.loads((dist / 'nav-manifest.json').read_text(encoding='utf-8'))
    if built.get('git_sha') != candidate or built.get('favorite_access') != policy['favorite_access']:
        raise ValueError('Build does not belong to the committed navigation candidate; rebuild first')
    return {'schema': SCHEMA, 'baseline': baseline, 'candidate': candidate, 'files': files,
            'manifest': static_sync.manifest(dist)}


def validate_prepared(prepared, identity):
    if prepared.get('schema') != SCHEMA:
        raise ValueError('Legacy navigation preparation: archive prepared.json, then prepare the committed candidate')
    for key in ('baseline', 'candidate', 'files'):
        if prepared.get(key) != identity[key]:
            raise ValueError('Candidate changed since preparation; retain the original evidence')
    if prepared.get('static', {}).get('manifest') != identity['manifest']:
        raise ValueError('Frontend artifact changed since preparation; retain the original evidence')


def execute(plan_path, prepare_only=False):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    source = HERE.parent
    identity = candidate_identity(source, plan['baseline'])
    state = source / '.deploy_state/color-guide/navigation'
    state.mkdir(parents=True, exist_ok=True)
    prepared_path = state / 'prepared.json'
    script = HERE / 'color_guide_navigation_remote.py'

    def invoke(payload):
        result = static_sync.remote_python(HOST, script, payload, sudo=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-3000:])
        return json.loads(result.stdout)

    if prepared_path.exists():
        prepared = json.loads(prepared_path.read_text(encoding='utf-8'))
        validate_prepared(prepared, identity)
        if prepare_only:
            before = invoke({**prepared, 'phase': 'plan'})
            if before['static_artifact'] != prepared['static']['expected']:
                raise RuntimeError('Frontend baseline changed since preparation')
            print(json.dumps({'status': 'prepared', 'candidate': identity['candidate'], 'reused': True}))
            return
    else:
        if not prepare_only:
            raise ValueError('Run --prepare-only first to freeze the candidate and frontend manifest')
        candidate = identity['candidate']
        bundle = state / (candidate + '.bundle')
        if not bundle.exists():
            subprocess.run(['git', 'bundle', 'create', str(bundle), identity['baseline'] + '..HEAD'],
                           cwd=source, check=True)
        request = {key: value for key, value in identity.items() if key != 'manifest'}
        request.update(bundle='/tmp/ark-color-guide-' + candidate + '.bundle',
                       bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(), phase='plan')
        before = invoke(request)
        if before['bundle_sha256'] is None:
            subprocess.run(['scp', *static_sync.SSH_OPTIONS, str(bundle), HOST + ':' + request['bundle']],
                           check=True, timeout=300)
        elif before['bundle_sha256'] != request['bundle_sha256']:
            raise RuntimeError('Existing remote bundle differs; do not overwrite an unknown transfer')
        invoke({**request, 'phase': 'stage'})
        staged = static_sync.prepare(source / 'frontend/dist', HOST, '/var/www/ark-dist', state, 'leshine.cloud')
        if staged['request']['expected'] != before['static_artifact']:
            raise RuntimeError('Static baseline changed during preparation')
        if staged['request']['manifest'] != identity['manifest']:
            raise RuntimeError('Frontend build changed during preparation')
        prepared = {**request, 'static': staged['request'], 'phase': 'activate'}
        prepared_path.write_text(json.dumps(prepared, indent=2), encoding='utf-8')
        print(json.dumps({'status': 'prepared', 'candidate': candidate,
                          'static_baseline': before['static_artifact']}))
        return
    result = invoke({**prepared, 'phase': 'activate'})
    (state / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)
