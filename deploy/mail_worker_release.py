"""Beijing mail worker release, exclusively invoked by deploy.bat."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from static_sync import remote_python, SSH_OPTIONS

HOST = 'ubuntu@154.8.205.162'
FILES = {
    'mail-worker.mjs': 'services/openclaw-sales-agent/src/mail-worker.mjs',
    'mail-worker-main.mjs': 'services/openclaw-sales-agent/src/mail-worker-main.mjs',
    'cli/package.json': 'deploy/mail-worker-cli/package.json',
    'cli/package-lock.json': 'deploy/mail-worker-cli/package-lock.json',
}


def artifact(source):
    result = {}
    for name, relative in FILES.items():
        body = (Path(source) / relative).read_bytes()
        result[name] = {'content': base64.b64encode(body).decode(), 'sha256': hashlib.sha256(body).hexdigest()}
    return result


def invoke(prepared, action):
    result = remote_python(HOST, Path(prepared['source']) / 'deploy/mail_worker_remote.py',
        {'action': action, 'revision': prepared['revision'], 'release_id': prepared['release_id'],
         'files': prepared['files']}, sudo=True, timeout=900)
    if result.returncode:
        raise RuntimeError('Mail worker deployment failed: ' + result.stderr[-2000:])
    receipt = json.loads(result.stdout.splitlines()[-1])
    if receipt.get('revision') != prepared['revision'] or receipt.get('status') != action:
        raise RuntimeError('Mail worker receipt does not match candidate')
    return receipt


def prepare(source, revision, release_id):
    prepared = {'source': str(source), 'revision': revision, 'release_id': release_id, 'files': artifact(source)}
    prepared['receipt'] = invoke(prepared, 'prepare')
    return prepared


def execute(source, revision, action):
    # A special operation does not acquire/rewrite a coordinated release baseline.
    prepared = {'source': str(source), 'revision': revision, 'release_id': 'setup', 'files': artifact(source)}
    if action == 'oauth':
        if not re.fullmatch(r'[a-f0-9]{40}', revision or ''):
            raise ValueError('OAuth requires a prepared full revision')
        invoke(prepared, 'provision')
        # OAuth stays on the Beijing service account, outside captured release logs.
        command = ['sudo', '-n', '-u', 'ark-mail', 'env', 'HOME=/var/lib/ark-mail-outreach/home',
                   'AGENTLY_WORKSPACE=ark-mail-beijing',
                   'PATH=/opt/ark-mail-outreach/runtimes/node-v22.23.2-linux-x64/bin:/usr/bin:/bin',
                   f'/opt/ark-mail-outreach/releases/{revision}/cli/node_modules/.bin/agently-cli', 'auth', 'login']
        print('请点击或复制以下链接在浏览器中完成授权：', flush=True)
        subprocess.run(['ssh', *SSH_OPTIONS, '-tt', HOST, shlex.join(command)], check=True, timeout=900)
        return
    print(json.dumps(invoke(prepared, action)), flush=True)
