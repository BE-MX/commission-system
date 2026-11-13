"""Fixed-target, staged office ingress migration. Invoked only by deploy.bat."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess

from static_sync import remote_python, SSH_OPTIONS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATE = ROOT / '.deploy_state/office-beijing-ingress'
HOST = 'ubuntu@154.8.205.162'


def cloud(action, **values):
    result = remote_python(HOST, HERE / 'office_ingress_remote.py',
                           {'action': action, **values}, sudo=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:] or 'Beijing stage failed')
    return json.loads(result.stdout)


def office(action, host_key=''):
    if action not in {'prepare', 'key', 'client', 'verify', 'reconnect'}:
        raise ValueError('Invalid office stage')
    if host_key and not host_key.startswith('ssh-ed25519 AAAA'):
        raise ValueError('Invalid host key')
    source = (HERE / 'office_ingress_client.ps1').read_text(encoding='utf8')
    payload = {'action': action, 'host_key': host_key}
    prefix = "$request = '" + base64.b64encode(json.dumps(payload).encode()).decode() + "'\n"
    loader = "& ([ScriptBlock]::Create([Console]::In.ReadToEnd()))"
    encoded = base64.b64encode(loader.encode('utf-16-le')).decode()
    result = subprocess.run(
        ['ssh', *SSH_OPTIONS, '-p', '2224', '-o', 'HostKeyAlias=[127.0.0.1]:2223',
         'office-prod', 'powershell -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand ' + encoded],
        input=prefix + source, text=True, capture_output=True, timeout=90,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:] or 'Office stage failed')
    return json.loads(result.stdout.strip())


def execute(stage):
    from publish import atomic_json

    # Freeze the actual controller, not an uncommitted deployment script.
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    names = ['deploy/office_beijing_ingress.py', 'deploy/office_ingress_remote.py',
             'deploy/office_ingress_client.ps1', 'deploy/publish.py']
    for name in names:
        committed = subprocess.check_output(['git', 'show', revision + ':' + name], cwd=ROOT)
        if committed.replace(b'\r\n', b'\n') != (ROOT / name).read_bytes().replace(b'\r\n', b'\n'):
            raise RuntimeError('Controller must match committed source: ' + name)
    STATE.mkdir(parents=True, exist_ok=True)
    receipt = STATE / (stage + '.json')
    record = {'stage': stage, 'revision': revision, 'status': 'started'}
    atomic_json(receipt, record)
    try:
        if stage == 'prepare':
            result = {'office': office('prepare'), 'beijing': cloud('prepare')}
        elif stage == 'key':
            result = office('key')
        elif stage == 'server':
            key = office('key')['public_key']
            result = cloud('server', public_key=key)
        elif stage == 'client':
            result = office('client', cloud('prepare')['host_key'])
        elif stage in {'verify', 'reconnect'}:
            local = office(stage)
            result = {'office': local, 'beijing': cloud('verify')}
        elif stage == 'routes-prepare':
            result = cloud('routes-prepare')
        elif stage == 'routes-activate':
            prior = json.loads((STATE / 'routes-prepare.json').read_text())
            if prior['status'] != 'succeeded' or prior['revision'] != revision:
                raise RuntimeError('Routing preparation must use this controller revision')
            result = cloud('routes-activate', baseline=prior['result']['baseline'],
                           candidate=prior['result']['candidate'])
        elif stage == 'rollback':
            result = cloud('rollback')
        else:
            raise ValueError('Unknown stage')
        record.update(status='succeeded', result=result)
    except Exception as exc:
        record.update(status='failed', error_type=type(exc).__name__)
        atomic_json(receipt, record)
        raise
    atomic_json(receipt, record)
    return record
