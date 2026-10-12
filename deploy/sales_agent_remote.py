"""Fixed Beijing preparation; never starts a consumer or changes mail state."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
try:
    import pwd
except ImportError:  # Windows tests never provision a real user.
    pwd = None
import re
import secrets
import stat
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path('/opt/ark-sales')
HOME = Path('/var/lib/ark-sales')
USER = 'ark-sales'
PROFILE = HOME / '.openclaw-ark-sales'
NODE_VERSION = 'v24.15.0'
NODE_HASH = '472655581fb851559730c48763e0c9d3bc25975c59d518003fc0849d3e4ba0f6'
SERVICE = 'ark-sales-agent'


def run(args, *, env=None, timeout=300):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                            env=env, timeout=timeout)
    if result.returncode:
        # Provider/config output can contain credentials, so do not echo it.
        write(ROOT / 'last-error.log', result.stdout + '\n' + result.stderr)
        raise RuntimeError(f'{Path(str(args[0])).name} failed (exit {result.returncode})')
    return result.stdout.strip()


def validate(payload):
    if not re.fullmatch(r'[a-f0-9]{40}', payload.get('revision', '')):
        raise ValueError('Invalid revision')
    if payload.get('action') not in {'prepare', 'configure', 'verify'}:
        raise ValueError('Invalid preparation action')
    files = {}
    for name, item in payload.get('files', {}).items():
        path = PurePosixPath(name)
        allowed = (name.startswith('services/openclaw-sales-agent/') or
                   any(name.startswith('.agents/skills/' + s + '/') for s in
                       ('ark-lead-discovery', 'ark-company-research', 'ark-public-pool-research')) or
                   name in {'deploy/sales-agent-runtime/package.json', 'deploy/sales-agent-runtime/package-lock.json',
                            'deploy/sales_agent_credentials.py'})
        if not allowed or path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('Invalid artifact path')
        body = base64.b64decode(item['content'], validate=True)
        if hashlib.sha256(body).hexdigest() != item['sha256']:
            raise ValueError('Artifact digest mismatch')
        files[name] = body
    if not files:
        raise ValueError('Missing artifact')
    return files


def write(path, body, mode=0o600):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError('Refusing symlink destination')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(12) + '.next')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body.encode() if isinstance(body, str) else body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def private_owner(path):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError('Refusing symlink ownership change')
    user = pwd.getpwnam(USER)
    os.chown(path, user.pw_uid, user.pw_gid)


def unit_text(release):
    node = PurePosixPath(ROOT.as_posix()) / 'runtime' / ('node-' + NODE_VERSION + '-linux-x64') / 'bin/node'
    cli = PurePosixPath(release.as_posix()) / 'deploy/sales-agent-runtime/node_modules/openclaw/openclaw.mjs'
    home = HOME.as_posix()
    profile = PROFILE.as_posix()
    return f'''[Unit]
Description=Ark dedicated sales research agent (prepared; model auth required)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User={USER}
Group={USER}
Environment=HOME={home}
Environment=PATH={node.parent}:/usr/bin:/bin
EnvironmentFile={profile}/.env
WorkingDirectory={release.as_posix()}
ExecStartPre=/usr/bin/test -s {profile}/secrets/mimo-api-key
ExecStartPre=/usr/bin/test -s {profile}/secrets/ark-agent-token
ExecStart={node} {cli} --profile ark-sales gateway --port 18791
Restart=on-failure
RestartSec=10
TimeoutStopSec=180
KillMode=mixed
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={home}
PrivateTmp=true
[Install]
WantedBy=multi-user.target
'''


def inactive():
    result = subprocess.run(['systemctl', 'is-active', SERVICE], capture_output=True, text=True)
    if result.stdout.strip() not in {'inactive', 'unknown', 'failed'}:
        raise RuntimeError('Sales consumer must remain inactive during preparation')
    enabled = subprocess.run(['systemctl', 'is-enabled', SERVICE], capture_output=True, text=True)
    if enabled.stdout.strip() not in {'disabled', 'masked', 'not-found', ''}:
        raise RuntimeError('Sales consumer must remain disabled during preparation')


def stage(payload, files):
    if platform.machine() != 'x86_64':
        raise RuntimeError('Expected Beijing x86_64')
    inactive()
    try:
        pwd.getpwnam(USER)
    except KeyError:
        run(['useradd', '--system', '--home-dir', HOME, '--create-home', '--shell', '/usr/sbin/nologin', USER])
    HOME.mkdir(exist_ok=True, mode=0o700)
    private_owner(HOME)
    runtime = ROOT / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    node_dir = runtime / ('node-' + NODE_VERSION + '-linux-x64')
    if not (node_dir / 'bin/node').exists():
        archive = runtime / ('node-' + NODE_VERSION + '-linux-x64.tar.xz')
        with urllib.request.urlopen(f'https://nodejs.org/dist/{NODE_VERSION}/{archive.name}', timeout=90) as response:
            write(archive, response.read(), 0o644)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_HASH:
            raise RuntimeError('Node archive digest mismatch')
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                if PurePosixPath(member.name).is_absolute() or '..' in PurePosixPath(member.name).parts:
                    raise RuntimeError('Invalid Node archive path')
            bundle.extractall(runtime, filter='data')
    release = ROOT / 'releases' / payload['revision']
    release.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        target = release / name
        if target.exists() and target.read_bytes() != body:
            raise RuntimeError('Immutable candidate drift')
        if not target.exists():
            write(target, body, 0o644)
    node = node_dir / 'bin/node'
    env = {**os.environ, 'PATH': str(node.parent) + ':/usr/bin:/bin', 'HOME': str(ROOT / 'build-home')}
    for folder in ('deploy/sales-agent-runtime', 'services/openclaw-sales-agent'):
        run([node, node_dir / 'lib/node_modules/npm/bin/npm-cli.js', 'ci', '--ignore-scripts',
             '--no-audit', '--no-fund', '--prefix', release / folder], env=env, timeout=900)
    run([node, release / 'deploy/sales-agent-runtime/node_modules/openclaw/openclaw.mjs', '--version'], env=env)
    write(ROOT / 'prepared.json', json.dumps({'revision': payload['revision']}))
    return release, node


def configure(payload):
    inactive()
    release = ROOT / 'releases' / payload['revision']
    if json.loads((ROOT / 'prepared.json').read_text())['revision'] != payload['revision']:
        raise RuntimeError('Candidate not prepared')
    node = ROOT / 'runtime' / ('node-' + NODE_VERSION + '-linux-x64') / 'bin/node'
    cli = release / 'deploy/sales-agent-runtime/node_modules/openclaw/openclaw.mjs'
    if PROFILE.is_symlink() or any(parent.is_symlink() for parent in PROFILE.parents):
        raise RuntimeError('Refusing symlink profile')
    PROFILE.mkdir(exist_ok=True, mode=0o700)
    private_owner(PROFILE)
    env_path = PROFILE / '.env'
    if not env_path.exists():
        write(env_path, 'OPENCLAW_GATEWAY_TOKEN=' + secrets.token_hex(32) + '\n'
              'ARK_BASE_URL=https://leshine.cloud\nARK_ALLOWED_ORIGIN=https://leshine.cloud\n'
              'ARK_AGENT_ID=openclaw-sales-beijing\nARK_API_TIMEOUT_MS=30000\nARK_HEARTBEAT_ENABLED=false\n')
        private_owner(env_path)
    args = ['sudo', '-u', USER, 'env', f'HOME={HOME}', f'PATH={node.parent}:/usr/bin:/bin',
            f'OPENCLAW_BIN={cli}', f'OPENCLAW_NODE={node}']
    # Configure, install Skills and MCP, with scheduling disabled and no gateway install.
    run([*args, node, release / 'services/openclaw-sales-agent/scripts/bootstrap.mjs', '--prepare-only'], timeout=900)
    # Credential issuance uses the existing principal and audited application API.
    # Plaintext never passes through this process or developer-machine receipts.
    run(['/home/ubuntu/commission-system/backend/.venv/bin/python',
         release / 'deploy/sales_agent_credentials.py'], timeout=90)
    write(Path('/etc/systemd/system') / (SERVICE + '.service'), unit_text(release), 0o644)
    run(['systemctl', 'daemon-reload'])
    write(ROOT / 'configured.json', json.dumps({'revision': payload['revision']}))


def verify(payload):
    inactive()
    revision = payload['revision']
    if json.loads((ROOT / 'configured.json').read_text())['revision'] != revision:
        raise RuntimeError('Candidate not configured')
    config = json.loads((PROFILE / 'openclaw.json').read_text())
    main = config['agents']['entries']['main']
    if main['heartbeat']['every'] != '0m' or config['gateway']['port'] != 18791 or config['gateway']['bind'] != 'loopback' or config['gateway']['auth']['mode'] != 'token':
        raise RuntimeError('Unsafe preparation policy')
    mcp = config['mcp']['servers']['ark-sales']
    release = ROOT / 'releases' / revision
    node = ROOT / 'runtime' / ('node-' + NODE_VERSION + '-linux-x64') / 'bin/node'
    if (mcp['env']['ARK_BASE_URL'] != 'https://leshine.cloud' or
        mcp['env']['ARK_ALLOWED_ORIGIN'] != 'https://leshine.cloud' or mcp['command'] != str(node) or
        mcp['args'] != [str(release / 'services/openclaw-sales-agent/src/server.mjs')] or
        mcp['cwd'] != str(release / 'services/openclaw-sales-agent')):
        raise RuntimeError('Incorrect API owner')
    if config['agents']['defaults']['models']['mimo/mimo-v2.5']['agentRuntime']['id'] != 'openclaw':
        raise RuntimeError('Model runtime pin drift')
    if not {'exec', 'write', 'edit', 'apply_patch', 'group:messaging'}.issubset(main['tools']['deny']) or not main['tools']['fs']['workspaceOnly']:
        raise RuntimeError('Main tool permissions drift')
    if (Path('/etc/systemd/system') / (SERVICE + '.service')).read_text() != unit_text(release):
        raise RuntimeError('Systemd unit drift')
    missing = []
    owner = pwd.getpwnam(USER)
    for name in ('mimo-api-key', 'ark-agent-token', 'deepseek-api-key'):
        path = PROFILE / 'secrets' / name
        if not path.exists():
            missing.append(name)
            continue
        meta = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_uid != owner.pw_uid or not path.read_text().strip():
            raise RuntimeError('Invalid private credential file: ' + name)
    return {'model': main.get('model', config['agents']['defaults']['model']),
            'missing_credentials': missing, 'heartbeat': 'disabled', 'gateway_port': 18791,
            'api_origin': 'https://leshine.cloud', 'service': 'inactive', 'enabled': False, 'mail_state': 'preserved'}


def execute(payload):
    files = validate(payload)
    action = payload['action']
    if action != 'prepare':
        release = ROOT / 'releases' / payload['revision']
        for name, body in files.items():
            path = release / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != body:
                raise RuntimeError('Prepared artifact drift: ' + name)
    if action == 'prepare':
        stage(payload, files)
    elif action == 'configure':
        configure(payload)
    detail = verify(payload) if action == 'verify' else {}
    return {'revision': payload['revision'], 'status': action, **detail}


if __name__ == '__main__':
    try:
        print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
