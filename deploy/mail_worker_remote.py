"""Fixed Beijing mail service installer. No application secrets in receipts/logs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

ROOT = Path('/opt/ark-mail-outreach')
STATE = Path('/var/lib/ark-mail-outreach')
CONFIG = Path('/etc/leshine/ark-mail-outreach.env')
UNIT = Path('/etc/systemd/system/ark-mail-outreach.service')
SERVICE = 'ark-mail-outreach'
USER = 'ark-mail'
NODE_VERSION = 'v22.23.2'
NODE_SHA256 = 'd60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307'
NAMES = {'mail-worker.mjs', 'mail-worker-main.mjs', 'cli/package.json', 'cli/package-lock.json'}
BACKEND_ENV = Path('/home/ubuntu/commission-system/backend/.env')


def run(args, *, timeout=180, env=None):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        # Never echo command args, environment, OAuth or provider diagnostics.
        raise RuntimeError(f'{Path(str(args[0])).name} failed with exit {result.returncode}')
    return result.stdout.strip()


def write(path, value, mode=0o600):
    temporary = path.with_name(path.name + '.next')
    with open(temporary, 'w', encoding='utf-8') as stream:
        os.chmod(temporary, mode)
        stream.write(json.dumps(value) if not isinstance(value, str) else value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def worker_hashes(body):
    found = []
    for line in body.decode('utf-8-sig').splitlines():
        match = re.fullmatch(r'\s*MAIL_OUTREACH_WORKER_TOKENS_JSON\s*=\s*(.*?)\s*', line)
        if match:
            value = match.group(1)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            found.append(json.loads(value or '{}'))
    if len(found) > 1:
        raise RuntimeError('Duplicate worker token configuration')
    values = found[0] if found else {}
    if not isinstance(values, dict) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key)
            or not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value) for key, value in values.items()):
        raise RuntimeError('Unrecognized existing worker token mapping')
    return values


def update_environment(body, digest, send_enabled=False):
    values = worker_hashes(body)
    values['ark-mail-beijing'] = digest
    replacements = {'MAIL_OUTREACH_WORKER_TOKENS_JSON': "'" + json.dumps(values, separators=(',', ':')) + "'",
                    'MAIL_OUTREACH_ALLOWED_RECIPIENTS': '86muliang@163.com',
                    'MAIL_OUTREACH_SEND_ENABLED': 'true' if send_enabled else 'false'}
    lines = body.decode('utf-8-sig').splitlines(keepends=True)
    newline = '\r\n' if b'\r\n' in body else '\n'
    seen = set()
    for index, line in enumerate(lines):
        match = re.match(r'\s*([A-Z0-9_]+)\s*=', line)
        if match and match[1] in replacements:
            key = match[1]
            if key in seen:
                raise RuntimeError('Duplicate mail environment key')
            seen.add(key)
            lines[index] = f'{key}={replacements[key]}{newline}'
    if lines and not lines[-1].endswith(('\n', '\r')):
        lines[-1] += newline
    lines.extend(f'{key}={value}{newline}' for key, value in replacements.items() if key not in seen)
    return ''.join(lines).encode('utf-8-sig' if body.startswith(b'\xef\xbb\xbf') else 'utf-8')


def configure(request):
    prepared(request)
    token, attempt = request.get('token', ''), request.get('attempt', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{48,128}', token) or not re.fullmatch(r'[a-f0-9]{32}', attempt):
        raise ValueError('Invalid protected credential plan')
    import pwd
    account = pwd.getpwnam(USER)
    directory = ROOT / 'configuration' / attempt
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    backup = directory / 'backend-before.env'
    current = BACKEND_ENV.read_bytes()
    expected = request.get('expected_environment_sha')
    if not backup.exists():
        if hashlib.sha256(current).hexdigest() != expected:
            raise RuntimeError('Beijing environment changed before configuration')
        backup.write_bytes(current)
        backup.chmod(0o600)
    original = backup.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected:
        raise RuntimeError('Configuration backup identity mismatch')
    enabled = request.get('send_enabled') is True
    digest = hashlib.sha256(token.encode()).hexdigest()
    desired = update_environment(original, digest, enabled)
    prior = update_environment(original, digest) if enabled else original
    if current not in {prior, desired}:
        raise RuntimeError('Beijing environment changed after configuration preparation')
    if enabled:
        verify_oauth(request)
    token_path = Path('/etc/leshine/ark-mail-outreach.token')
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    config_body = b'ARK_BASE_URL=https://leshine.cloud\nMAIL_WORKER_TOKEN_FILE=/etc/leshine/ark-mail-outreach.token\nMAIL_OUTREACH_ALLOWED_RECIPIENTS=86muliang@163.com\n'
    for file, expected_key, desired_body in [(CONFIG, 'expected_config_sha', config_body),
                                           (token_path, 'expected_token_sha', (token + '\n').encode())]:
        actual = hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None
        if actual not in {request.get(expected_key), hashlib.sha256(desired_body).hexdigest()}:
            raise RuntimeError('Worker private configuration drift; refusing overwrite')
    for file in [CONFIG, token_path]:
        if file.exists() and not (directory / (file.name + '.before')).exists():
            shutil.copy2(file, directory / (file.name + '.before'))
            (directory / (file.name + '.before')).chmod(0o600)
    if token_path.exists() and token_path.read_text().strip() != token:
        raise RuntimeError('Existing worker credential differs; explicit rotation required')
    write(token_path, token + '\n', 0o640)
    os.chown(token_path, 0, account.pw_gid)
    write(CONFIG, config_body.decode())
    if current != desired:
        metadata = BACKEND_ENV.stat()
        temporary = BACKEND_ENV.with_name(BACKEND_ENV.name + '.mail-' + attempt)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(desired)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, metadata.st_mode & 0o777)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        if BACKEND_ENV.read_bytes() != prior:
            raise RuntimeError('Beijing environment drift at activation')
        os.replace(temporary, BACKEND_ENV)
    write(directory / ('enabled-receipt.json' if enabled else 'receipt.json'), {'revision': request['revision'], 'status': 'sending-enabled' if enabled else 'configured',
        'before_sha': expected, 'after_sha': hashlib.sha256(desired).hexdigest()})
    return {'services_restarted': False, 'send_enabled': enabled}


def validate(request):
    if not re.fullmatch(r'[a-f0-9]{40}', request.get('revision', '')):
        raise ValueError('Full revision required')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', request.get('release_id', '')):
        raise ValueError('Release identity required')
    files = request.get('files', {})
    if set(files) != NAMES:
        raise ValueError('Unexpected artifact paths')
    bodies = {}
    for name, entry in files.items():
        body = base64.b64decode(entry['content'], validate=True)
        if len(body) > 2_000_000 or hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError('Artifact digest mismatch')
        bodies[name] = body
    package = json.loads(bodies['cli/package.json'])
    if package.get('dependencies') != {'@tencent-qqmail/agently-cli': '1.0.18'}:
        raise ValueError('Unreviewed CLI version')
    return bodies


def ensure_node():
    if platform.machine() != 'x86_64' or platform.system() != 'Linux':
        raise RuntimeError('Mail worker requires Beijing Linux x86_64')
    runtimes = ROOT / 'runtimes'
    node = runtimes / f'node-{NODE_VERSION}-linux-x64/bin/node'
    if node.is_file() and run([node, '--version']) == NODE_VERSION:
        return node
    runtimes.mkdir(parents=True, exist_ok=True)
    archive = runtimes / f'node-{NODE_VERSION}-linux-x64.tar.xz'
    with urllib.request.urlopen(f'https://nodejs.org/dist/{NODE_VERSION}/{archive.name}', timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != NODE_SHA256:
        raise RuntimeError('Node archive checksum mismatch')
    archive.write_bytes(data)
    with tarfile.open(archive) as stream:
        stream.extractall(runtimes, filter='data')
    if run([node, '--version']) != NODE_VERSION:
        raise RuntimeError('Node version verification failed')
    return node


def unit_text(folder, node, revision):
    folder_path, node_path, node_dir = folder.as_posix(), node.as_posix(), node.parent.as_posix()
    state_path, config_path = STATE.as_posix(), CONFIG.as_posix()
    return f'''[Unit]
Description=Ark approved customer mail worker
After=network-online.target ark-backend.service
Wants=network-online.target

[Service]
Type=simple
User={USER}
Group={USER}
WorkingDirectory={folder_path}
EnvironmentFile={config_path}
Environment=HOME={state_path}/home
Environment=MAIL_WORKER_STATE={state_path}
Environment=AGENTLY_CLI_BIN={folder_path}/cli/node_modules/.bin/agently-cli
Environment=MAIL_WORKER_REVISION={revision}
Environment=PATH={node_dir}:/usr/bin:/bin
ExecStart=/usr/bin/flock --no-fork --nonblock {state_path}/process.lock {node_path} {folder_path}/mail-worker-main.mjs
Restart=on-failure
RestartSec=10
KillMode=mixed
TimeoutStopSec=180
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={state_path}
UMask=0077

[Install]
WantedBy=multi-user.target
'''


def prepared(request):
    folder = ROOT / 'releases' / request['revision']
    record = read(folder / 'prepared.json')
    expected = {name: value['sha256'] for name, value in request['files'].items()}
    if not record or record.get('files') != expected:
        raise RuntimeError('Prepare this exact artifact first')
    for name, digest in expected.items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Prepared artifact drift')
    return folder, record


def prepare(request, bodies):
    folder = ROOT / 'releases' / request['revision']
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != body:
            raise RuntimeError('Immutable candidate changed')
        path.write_bytes(body)
        path.chmod(0o644)
    node = ensure_node()
    cli = folder / 'cli/node_modules/.bin/agently-cli'
    if not cli.exists():
        # npm rejects using the same path for its user and global config sources.
        build_home = ROOT / 'build-home'
        build_home.mkdir(exist_ok=True)
        user_config, global_config = build_home / 'user.npmrc', build_home / 'global.npmrc'
        for config in (user_config, global_config):
            if config.exists() and config.read_bytes():
                raise RuntimeError('Unexpected private npm configuration in managed build directory')
            config.touch(mode=0o600, exist_ok=True)
        env = {'PATH': str(node.parent) + ':/usr/bin:/bin', 'HOME': str(ROOT / 'build-home'),
               'npm_config_cache': str(ROOT / 'npm-cache'), 'NPM_CONFIG_USERCONFIG': str(user_config),
               'NPM_CONFIG_GLOBALCONFIG': str(global_config), 'npm_config_registry': 'https://registry.npmjs.org/',
               'npm_config_strict_ssl': 'true'}
        run([node, node.parent / 'npm', 'ci', '--prefix', folder / 'cli', '--ignore-scripts', '--no-audit', '--no-fund'], env=env, timeout=600)
    env = dict(os.environ, PATH=str(node.parent) + ':/usr/bin:/bin')
    if '1.0.18' not in run([cli, '--version'], env=env):
        raise RuntimeError('CLI version verification failed')
    run([node, '--check', folder / 'mail-worker.mjs'])
    run([node, '--check', folder / 'mail-worker-main.mjs'])
    unit = unit_text(folder, node, request['revision'])
    write(folder / 'worker.service', unit, 0o644)
    write(folder / 'prepared.json', {'files': {name: value['sha256'] for name, value in request['files'].items()}, 'node': str(node)})
    if request['release_id'] != 'setup':
        validate_config()
        current = state()
        if current.get('LoadState') == 'not-found' or current.get('ActiveState') == 'active':
            verify_oauth(request)
    return {'configured': CONFIG.exists()}


def provision(request):
    # Creates a stopped service account/home. Does not manufacture or move OAuth credentials.
    prepared(request)
    import pwd
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        run(['useradd', '--system', '--home-dir', STATE / 'home', '--shell', '/usr/sbin/nologin', USER])
        account = pwd.getpwnam(USER)
    for path in [STATE, STATE / 'home']:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        os.chown(path, account.pw_uid, account.pw_gid)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    return {'configured': CONFIG.exists(), 'oauth_required': True}


def state():
    lines = run(['systemctl', 'show', SERVICE, '--property=LoadState,ActiveState,MainPID,UnitFileState'])
    return dict(line.split('=', 1) for line in lines.splitlines() if '=' in line)


def release_record(request):
    record = read(ROOT / 'release-current.json')
    if not record or record.get('revision') != request['revision'] or record.get('release_id') != request['release_id']:
        raise RuntimeError('Mail release baseline mismatch')
    return record


def freeze(request):
    prepared(request)
    existing = read(ROOT / 'release-current.json')
    if existing and existing.get('status') != 'verified':
        if (existing.get('revision'), existing.get('release_id')) != (request['revision'], request['release_id']):
            raise RuntimeError('Unfinished mail release requires its original candidate and release identity')
        record = existing
    else:
        before = state()
        record = {'revision': request['revision'], 'release_id': request['release_id'], 'status': 'freezing',
                  'was_active': before.get('ActiveState') == 'active',
                  'was_enabled': before.get('UnitFileState') == 'enabled', 'first_install': before.get('LoadState') == 'not-found'}
        write(ROOT / 'release-current.json', record)
    if STATE.exists():
        write(STATE / 'freeze.json', {'revision': request['revision'], 'release_id': request['release_id']}, 0o644)
    if state().get('LoadState') != 'not-found':
        run(['systemctl', 'stop', SERVICE], timeout=200)
    after = state()
    if after.get('ActiveState') not in {'inactive', 'failed'} or after.get('MainPID') != '0':
        raise RuntimeError('Mail worker did not drain')
    if read(STATE / 'pending.json'):
        # Flush-only restart: the persistent marker prevents new claims/sends.
        run(['systemctl', 'start', SERVICE])
        try:
            for attempt in range(45):
                if not read(STATE / 'pending.json'):
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Mail receipt cannot be reconciled; inspect API before release')
        finally:
            run(['systemctl', 'stop', SERVICE], timeout=200)
    record['status'] = 'frozen'
    write(ROOT / 'release-current.json', record)
    return {'baseline': record}


def validate_config():
    if not CONFIG.is_file() or CONFIG.stat().st_mode & 0o077 or CONFIG.stat().st_uid != 0:
        raise RuntimeError('Create a root-only worker environment file first')
    values = {}
    for line in CONFIG.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    if set(values) != {'ARK_BASE_URL', 'MAIL_WORKER_TOKEN_FILE', 'MAIL_OUTREACH_ALLOWED_RECIPIENTS'}:
        raise RuntimeError('Unexpected mail worker environment keys')
    if values.get('ARK_BASE_URL') != 'https://leshine.cloud':
        raise RuntimeError('Worker must use the Beijing HTTPS application')
    token = Path(values.get('MAIL_WORKER_TOKEN_FILE', '/nonexistent'))
    import pwd
    group = pwd.getpwnam(USER).pw_gid
    if (token != Path('/etc/leshine/ark-mail-outreach.token') or not token.is_file()
            or token.stat().st_mode & 0o777 != 0o640 or token.stat().st_uid != 0 or token.stat().st_gid != group):
        raise RuntimeError('Worker token file missing or unsafe')
    if len(token.read_text().strip()) < 32:
        raise RuntimeError('Worker token too short')
    if values.get('MAIL_OUTREACH_ALLOWED_RECIPIENTS') != '86muliang@163.com':
        raise RuntimeError('Initial acceptance is restricted to the owner-approved recipient')


def activate(request):
    release_record(request)  # Never stop a different release's service on bad input.
    try:
        return activate_inner(request)
    except Exception:
        activation_failed(request)
        raise


def verify_oauth(request):
    folder, record = prepared(request)
    validate_config()
    node = Path(record['node'])
    cli = folder / 'cli/node_modules/.bin/agently-cli'
    probe = json.loads(run(['sudo', '-n', '-u', USER, 'env', f'HOME={STATE}/home',
        'AGENTLY_WORKSPACE=ark-mail-beijing', f'PATH={node.parent}:/usr/bin:/bin', cli, '+me']))
    if not probe.get('ok') or not any(alias.get('is_primary') is True and alias.get('email') == 'leshinehair@agent.qq.com'
                                    for alias in probe.get('data', {}).get('aliases', [])):
        raise RuntimeError('Complete Beijing OAuth for the approved sender before releasing')


def activate_inner(request):
    folder, _ = prepared(request)
    validate_config()
    record = release_record(request)
    if record['status'] not in {'frozen', 'activated', 'verified'}:
        raise RuntimeError('Freeze and drain before activating mail worker')
    if state().get('MainPID') != '0':
        # A matching already-active candidate is verified, never stopped twice on a retry.
        if record['status'] in {'activated', 'verified'}:
            return verify(request)
        raise RuntimeError('Unexpected running mail process')
    provision(request)
    # Start frozen; verify identity/version before allowing the first new claim.
    write(STATE / 'freeze.json', {'revision': request['revision'], 'release_id': request['release_id']}, 0o644)
    if UNIT.exists():
        backup = ROOT / f'unit-before-{request["release_id"]}.service'
        if not backup.exists():
            shutil.copy2(UNIT, backup)
    write(UNIT, (folder / 'worker.service').read_text(), 0o644)
    run(['systemctl', 'daemon-reload'])
    if record['first_install'] or record['was_enabled']:
        run(['systemctl', 'enable', SERVICE])
    if record['first_install'] or record['was_active']:
        run(['systemctl', 'start', SERVICE])
    record['status'] = 'activated'
    write(ROOT / 'release-current.json', record)
    result = verify_ready(request, allow_frozen=True)
    if record['first_install'] or record['was_active']:
        (STATE / 'freeze.json').unlink(missing_ok=True)
    return result


def activation_failed(request):
    record = release_record(request)
    try:
        write(STATE / 'freeze.json', {'revision': request['revision'], 'release_id': request['release_id']}, 0o644)
        record['status'] = 'activation-failed'
        write(ROOT / 'release-current.json', record)
    finally:
        # Even full disks or a journal failure must still stop the sender.
        run(['systemctl', 'stop', SERVICE], timeout=200)


def verify(request):
    try:
        return verify_ready(request)
    except Exception:
        # Failed health/version/auth verification must not leave a sender claiming work.
        # Keep its new code/schema and durable receipts; never restart an old candidate.
        activation_failed(request)
        raise


def verify_ready(request, allow_frozen=False):
    record = release_record(request)
    should_run = record['first_install'] or record['was_active']
    if should_run:
        if not allow_frozen and (STATE / 'freeze.json').exists():
            raise RuntimeError('Mail worker remains frozen')
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:7911/health', timeout=3) as response:
                    health = json.load(response)
                if health.get('revision') != request['revision'] or health.get('pending_receipt') or health.get('draining') or not health.get('last_ok') or not health.get('authenticated'):
                    raise RuntimeError('Mail worker health mismatch')
                break
            except Exception:
                if attempt == 29:
                    raise RuntimeError('Mail worker readiness failed') from None
                time.sleep(2)
    elif state().get('MainPID') != '0':
        raise RuntimeError('Previously stopped mail worker unexpectedly running')
    record['status'] = 'verified'
    write(ROOT / 'release-current.json', record)
    return {'running': should_run}


def dispatch(request):
    bodies = validate(request)
    if request['action'] == 'prepare':
        details = prepare(request, bodies)
    elif request['action'] == 'provision':
        details = provision(request)
    elif request['action'] == 'config-probe':
        body = BACKEND_ENV.read_bytes()
        worker_hashes(body)
        token_path = Path('/etc/leshine/ark-mail-outreach.token')
        details = {'environment_sha': hashlib.sha256(body).hexdigest(),
                   'config_sha': hashlib.sha256(CONFIG.read_bytes()).hexdigest() if CONFIG.exists() else None,
                   'token_sha': hashlib.sha256(token_path.read_bytes()).hexdigest() if token_path.exists() else None}
    elif request['action'] in {'freeze', 'activate', 'verify', 'configure'}:
        details = globals()[request['action']](request)
    else:
        raise ValueError('Unsupported mail release action')
    return {'status': request['action'], 'revision': request['revision'], **details}


def main(request):
    import fcntl
    validate(request)
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / 'operation.lock', 'a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return dispatch(request)


if __name__ == '__main__':
    try:
        print(json.dumps(main(json.loads(sys.stdin.read()))))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
