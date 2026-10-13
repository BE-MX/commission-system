"""Prepare the dedicated Beijing sales runtime through deploy.bat."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import re

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


def read_model_config(path):
    values = {}
    names = {'mimo base url': 'base_url', 'api key': 'api_key', 'model': 'model'}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*([^:]+):\s*(\S+)\s*', line)
        if not match or match[1].strip().lower() not in names:
            raise ValueError('Model file must contain only base URL, API KEY and MODEL fields')
        key = names[match[1].strip().lower()]
        if key in values:
            raise ValueError('Duplicate model configuration field')
        values[key] = match[2]
    if set(values) != {'base_url', 'api_key', 'model'}:
        raise ValueError('Missing model configuration field')
    return values


def execute(source, revision, action, state, model_path=None, runtime_revision=None):
    source = Path(source)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip()
    if actual != revision or dirty:
        raise RuntimeError('Sales preparation requires a clean pinned candidate')
    payload = {'revision': revision, 'action': action, 'files': artifact(source)}
    if model_path:
        payload['model_config'] = read_model_config(model_path)
    if runtime_revision:
        payload['runtime_revision'] = runtime_revision
    result = remote_python(HOST, source / 'deploy/sales_agent_remote.py', payload, sudo=True, timeout=1200)
    if result.returncode:
        raise RuntimeError('Sales preparation failed: ' + result.stderr[-1500:])
    receipt = json.loads(result.stdout.splitlines()[-1])
    if receipt['revision'] != revision or receipt['status'] != action:
        raise RuntimeError('Sales receipt does not match candidate')
    folder = Path(state) / 'sales-agent'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (action + '.json')).write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt), flush=True)
