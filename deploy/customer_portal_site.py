"""Managed customer-site HTTPS setup; does not activate application or business gates."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

from static_sync import remote_python

HERE = Path(__file__).resolve().parent
HOST = 'ubuntu@154.8.205.162'
DOMAIN = 'shop.leshine.cloud'


def execute(phase, revision, prepare_only=False, config=False):
    import publish
    root = HERE.parent
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=root, text=True)
    if not revision or not re.fullmatch(r'[0-9a-f]{40}', revision) or revision != actual or dirty:
        raise RuntimeError('Customer-site setup requires clean reviewed source and its full --revision')
    source = HERE / 'nginx/customer-orders.conf.template'
    template = source.read_text(encoding='utf-8').replace('__PORTAL_DOMAIN__', DOMAIN)
    request = {'phase': 'plan' if prepare_only else phase, 'domain': DOMAIN,
        'template': template, 'digest': hashlib.sha256(template.encode()).hexdigest(), 'revision': revision,
        'script_digest': hashlib.sha256((HERE / 'customer_portal_site_remote.py').read_bytes()).hexdigest()}
    with publish.deployment_lock():
        script = HERE / ('customer_portal_config_remote.py' if config else 'customer_portal_site_remote.py')
        if config:
            request = {'phase': phase, 'revision': revision}
            if prepare_only: raise RuntimeError('Customer overlay preparation is explicit; do not combine prepare-only')
        result = remote_python(HOST, script, request, sudo=True, timeout=300)
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:] or 'Customer-site setup failed; inspect its retained journal')
        receipt = json.loads(result.stdout.splitlines()[-1])
        receipt.update(revision=revision, script_digest=hashlib.sha256(script.read_bytes()).hexdigest())
        if not config: receipt['template_digest'] = request['digest']
        publish.atomic_json(publish.STATE / ('customer-portal-config.json' if config else 'customer-portal-site.json'), receipt)
        print(json.dumps(receipt), flush=True)
