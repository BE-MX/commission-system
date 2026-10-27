"""Publish the approved standalone color guide through the managed entry point."""
import hashlib
import json
from pathlib import Path

import static_sync

HERE = Path(__file__).resolve().parent
HOST = 'ubuntu@154.8.205.162'
DOMAIN = 'color-guide.leshine.cloud'
ROOT = '/var/www/ark-static/color-guide'


def validate_plan(plan):
    if set(plan) - {'source', 'files', 'domain', 'archive_sha256'}:
        raise ValueError('Unknown color-guide plan field')
    if plan.get('domain', DOMAIN) != DOMAIN:
        raise ValueError('Unregistered color-guide domain')
    source = Path(plan['source'])
    if not source.is_absolute() or not source.is_dir():
        raise ValueError('Color-guide source must be an absolute existing directory')
    files = static_sync.manifest(source)
    if files != plan.get('files'):
        raise ValueError('Color-guide files differ from the reviewed manifest')
    return source, files


def execute(plan_path, prepare_only=False):
    import publish
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    source, files = validate_plan(plan)
    template = (HERE / 'nginx/color-guide.conf.template').read_text(encoding='utf-8')
    common = {'domain': DOMAIN, 'template': template,
              'digest': hashlib.sha256(template.encode()).hexdigest()}
    state = publish.STATE / 'color-guide'
    state.mkdir(parents=True, exist_ok=True)

    def remote(phase, **extra):
        result = static_sync.remote_python(HOST, HERE / 'color_guide_site_remote.py',
                                          {**common, 'phase': phase, **extra}, sudo=True, timeout=300)
        if result.returncode:
            raise RuntimeError('Color-guide infrastructure failed: ' + result.stderr[-2500:])
        return json.loads(result.stdout.splitlines()[-1])

    preflight = remote('plan')
    prepared = static_sync.prepare(source, HOST, ROOT, state, DOMAIN)
    if prepared['request']['manifest'] != files:
        raise RuntimeError('Color-guide source changed during preparation; activation withheld')
    receipt = {'domain': DOMAIN, 'files': files, 'archive_sha256': plan.get('archive_sha256'),
               'infrastructure': preflight, 'prepared': prepared, 'status': 'prepared'}
    publish.atomic_json(state / 'site-current.json', receipt)
    if not prepare_only:
        receipt['infrastructure'] = remote('configure', expected=preflight['config_digest'])
        publish.atomic_json(state / 'site-current.json', receipt)
        receipt['activation'] = static_sync.activate(prepared)
        receipt['verification'] = remote('verify', index_sha256=files['index.html'])
        receipt['status'] = 'succeeded'
        publish.atomic_json(state / 'site-current.json', receipt)
    print(json.dumps({'domain': DOMAIN, 'status': receipt['status'],
                      'files': len(files), 'receipt': str(state / 'site-current.json')}), flush=True)
    return receipt
