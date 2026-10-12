"""Prepare the dedicated Beijing sales runtime through deploy.bat."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

from static_sync import remote_python

HOST = 'ubuntu@154.8.205.162'
SERVICE = 'services/openclaw-sales-agent'


def artifact(source):
    source = Path(source)
    paths = [source / SERVICE / name for name in ('package.json', 'package-lock.json')]
    for folder in ('src', 'scripts', 'workspace-template'):
        paths.extend((source / SERVICE / folder).glob('*'))
    for skill in ('ark-lead-discovery', 'ark-company-research', 'ark-public-pool-research'):
        paths.extend((source / '.agents/skills' / skill).rglob('*'))
    paths.extend((source / 'deploy/sales-agent-runtime').glob('*.json'))
    paths.append(source / 'deploy/sales_agent_credentials.py')
    result = {}
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError('Sales artifacts cannot contain symlinks')
        if path.is_file():
            body = path.read_bytes()
            result[path.relative_to(source).as_posix()] = {
                'content': base64.b64encode(body).decode(), 'sha256': hashlib.sha256(body).hexdigest()}
    return result


def execute(source, revision, action, state):
    source = Path(source)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip()
    if actual != revision or dirty:
        raise RuntimeError('Sales preparation requires a clean pinned candidate')
    result = remote_python(HOST, source / 'deploy/sales_agent_remote.py',
        {'revision': revision, 'action': action, 'files': artifact(source)}, sudo=True, timeout=1200)
    if result.returncode:
        raise RuntimeError('Sales preparation failed: ' + result.stderr[-1500:])
    receipt = json.loads(result.stdout.splitlines()[-1])
    if receipt['revision'] != revision or receipt['status'] != action:
        raise RuntimeError('Sales receipt does not match candidate')
    folder = Path(state) / 'sales-agent'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (action + '.json')).write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt), flush=True)
