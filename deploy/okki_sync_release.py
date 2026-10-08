"""A reviewed three-file outbound mirror release through deploy.bat."""
import base64
import hashlib
import json
from pathlib import Path
from static_sync import remote_python

NAMES = ('inspection-contract.mjs', 'outbound-store.mjs', 'sync-outbound.js')


def execute(plan_path, prepare_only=False):
    import publish
    source = Path(__file__).resolve().parent.parent
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    if set(plan) != {'expected_live', 'candidate'} or set(plan['candidate']) != set(NAMES):
        raise ValueError('A fixed reviewed mirror plan is required')
    files = {}
    for name in NAMES:
        body = (source / 'services' / 'okki-sync' / name).read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != plan['candidate'][name]:
            raise RuntimeError('Candidate changed after review: ' + name)
        files[name] = {'sha256': digest, 'content': base64.b64encode(body).decode()}
    request = {'action': 'prepare' if prepare_only else 'activate', 'files': files, 'expected_live': plan['expected_live']}
    with publish.deployment_lock():
        result = remote_python('ubuntu@154.8.205.162', source / 'deploy' / 'okki_sync_remote.py', request, sudo=True, timeout=90)
        if result.returncode:
            raise RuntimeError('Outbound mirror release failed; inspect the remote release journal')
        receipt = json.loads(result.stdout)
        expected = hashlib.sha256(json.dumps({name: files[name]['sha256'] for name in sorted(NAMES)}, sort_keys=True).encode()).hexdigest()
        if receipt.get('digest') != expected or receipt.get('status') not in ({'prepared', 'verified'} if prepare_only else {'verified'}):
            raise RuntimeError('Outbound mirror receipt does not match this candidate')
        publish.atomic_json(publish.STATE / 'okki-sync-release.json', receipt)
        print(json.dumps(receipt), flush=True)
