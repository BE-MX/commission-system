"""CAS provision mail credentials through the office deploy entry, never CLI args."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid

from mail_worker_release import HOST, artifact
from static_sync import remote_python

IDENTITY = 'ark-mail-beijing'


def secure_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        raise RuntimeError('Mail configuration must run on the installed office Windows host')
    # SIDs avoid translated group names. Only the current deploying user/system/admins.
    who = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh'], text=True).strip()
    import csv
    sid = next(csv.reader([who]))[1]
    subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F',
                    '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'], check=True, capture_output=True)


def env_hash(body):
    return hashlib.sha256(body).hexdigest()


def save_plan(path, value):
    temporary = path.with_name(path.name + '.next')
    with open(temporary, 'w', encoding='utf-8') as stream:
        stream.write(json.dumps(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_local(path, body, expected):
    temporary = path.with_name(path.name + '.mail-' + uuid.uuid4().hex)
    # Create an empty exclusive file, apply the live ACL, and only then write secrets.
    with open(temporary, 'xb'):
        pass
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = f'Get-Acl -LiteralPath {literal(path)} | Set-Acl -LiteralPath {literal(temporary)}'
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], check=True, capture_output=True)
    with open(temporary, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if env_hash(path.read_bytes()) != expected:
        raise RuntimeError('Office environment drift at activation')
    os.replace(temporary, path)


def invoke(source, revision, action, extra=None):
    request = {'action': action, 'revision': revision, 'release_id': 'setup', 'files': artifact(source), **(extra or {})}
    result = remote_python(HOST, Path(source) / 'deploy/mail_worker_remote.py', request, sudo=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Beijing mail configuration failed: ' + result.stderr[-1000:])
    return json.loads(result.stdout.splitlines()[-1])


def configure(source, live, revision, *, enable_sending=False):
    from mail_worker_remote import update_environment, worker_hashes
    directory = Path(live) / '.deploy_state/credentials/mail-worker'
    secure_directory(directory)
    path = directory / 'configure-current.json'
    env = Path(live) / 'backend/.env'
    if path.exists():
        plan = json.loads(path.read_text())
        if plan['revision'] != revision:
            raise RuntimeError('Existing credential preparation belongs to another candidate; inspect before rotation')
    else:
        if enable_sending:
            raise RuntimeError('Configure credentials before enabling sends')
        probe = invoke(source, revision, 'config-probe')
        original = env.read_bytes()
        # Parse both before creating a persistent credential.
        worker_hashes(original)
        token = secrets.token_urlsafe(48)
        attempt = uuid.uuid4().hex
        plan = {'revision': revision, 'attempt': attempt, 'token': token,
                'office_original_sha': env_hash(original), 'beijing_original_sha': probe['environment_sha'],
                'beijing_config_sha': probe['config_sha'], 'beijing_token_sha': probe['token_sha'], 'status': 'prepared'}
        (directory / f'office-before-{attempt}.env').write_bytes(original)
        save_plan(path, plan)
    digest = hashlib.sha256(plan['token'].encode()).hexdigest()
    original = (directory / f'office-before-{plan["attempt"]}.env').read_bytes()
    if env_hash(original) != plan['office_original_sha']:
        raise RuntimeError('Office configuration backup identity mismatch')
    if enable_sending and plan['status'] not in {'configured', 'sending-enabled'}:
        raise RuntimeError('Complete credential preparation before enabling sends')
    desired = update_environment(original, digest, enable_sending)
    prior = update_environment(original, digest) if enable_sending else original
    current = env.read_bytes()
    if env_hash(current) not in {env_hash(prior), env_hash(desired)}:
        raise RuntimeError('Office environment changed after preparation; no overwrite attempted')
    # Any uncertain remote response is retried using the exact same durable attempt/token.
    invoke(source, revision, 'configure', {'attempt': plan['attempt'], 'token': plan['token'],
        'expected_environment_sha': plan['beijing_original_sha'],
        'expected_config_sha': plan['beijing_config_sha'], 'expected_token_sha': plan['beijing_token_sha'],
        'send_enabled': enable_sending})
    if current != desired:
        # Recheck after the remote operation, immediately before replacing office config.
        if env_hash(env.read_bytes()) != env_hash(prior):
            raise RuntimeError('Office environment changed during preparation')
        atomic_local(env, desired, env_hash(prior))
    # source_release creates a hardlink; replacing the live file must refresh this
    # candidate's link so preflight/imports cannot keep the old credential config.
    candidate_env = Path(source) / 'backend/.env'
    if candidate_env.exists() and candidate_env.read_bytes() not in {original, prior, desired}:
        raise RuntimeError('Candidate runtime environment has independent changes')
    if candidate_env.resolve() != env.resolve():
        temporary = candidate_env.with_name('.env.mail-link')
        temporary.unlink(missing_ok=True)
        os.link(env, temporary)
        os.replace(temporary, candidate_env)
    plan['status'] = 'sending-enabled' if enable_sending else 'configured'
    save_plan(path, plan)
    return {'status': plan['status'], 'revision': revision, 'identity': IDENTITY,
            'office_environment_sha': env_hash(desired), 'services_restarted': False}
