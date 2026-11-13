"""Standalone Beijing helper; fixed identities, checked drift and local backups."""

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/home/ubuntu/commission-system/.deploy_state/office-beijing-ingress')
NGINX = Path('/etc/nginx/sites-enabled/ark-cloud.conf')
USER = 'ark-office-tunnel'
HOME = Path('/var/lib/ark-office-tunnel')
SSHD = Path('/etc/ssh/sshd_config.d/90-ark-office-tunnel.conf')
OLD = 'https://119.28.107.92'
NEW = 'http://127.0.0.1:8002'
FEATURES = ('RECEIPT', 'DESIGN IMAGE', 'WHATSAPP', 'SHIPPING VIDEO')
SSH_CONFIG = '''Match User ark-office-tunnel
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowTcpForwarding remote
    AllowStreamLocalForwarding no
    GatewayPorts no
    PermitListen 127.0.0.1:8002
    PermitOpen none
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    PermitTunnel no
    PermitUserRC no
    MaxSessions 0
    ForceCommand /bin/false
Match all
'''
MCP = '''# BEGIN ARK PLATFORM MCP ROUTING
location = /mcp { return 308 /mcp/; }
location /mcp/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_next_upstream off;
    proxy_read_timeout 3600s;
}
# END ARK PLATFORM MCP ROUTING
'''


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


def save(path, data):
    scratch = path.with_suffix(path.suffix + '.tmp')
    scratch.write_text(json.dumps(data, indent=2))
    scratch.chmod(0o600)
    scratch.replace(path)


def direct_snippet(block):
    count = block.count('proxy_pass ' + OLD + ';')
    block = block.replace('proxy_pass ' + OLD + ';', 'proxy_pass ' + NEW + ';')
    block = re.sub(r'(?m)^\s*proxy_ssl_[^\n]+\n', '', block)
    block = block.replace('proxy_set_header Host leshine.work;', 'proxy_set_header Host $host;')
    block = block.replace('via Singapore.', 'through the dedicated Beijing SSH tunnel.')
    return block, count


def render(original):
    candidate = original
    replaced = 0
    for name in FEATURES:
        pattern = r'# BEGIN ARK ' + name + r' ROUTING.*?# END ARK ' + name + r' ROUTING'
        blocks = re.findall(pattern, candidate, flags=re.S)
        if len(blocks) != 2:
            raise ValueError('Unexpected managed routing blocks: ' + name)
        for block in set(blocks):
            updated, count = direct_snippet(block)
            expected = 4 if name == 'SHIPPING VIDEO' else 1
            if count != expected:
                raise ValueError('Unexpected Singapore upstreams: ' + name)
            replaced += candidate.count(block) * count
            candidate = candidate.replace(block, updated)
    if replaced != 14:
        raise ValueError('Unexpected office upstream count')
    if re.search(r'location\s+(?:(?:=|\^~)\s+)?/mcp/?\s', candidate):
        raise ValueError('Existing generic MCP route requires inspection')
    anchor = 'location /api/ {'
    if candidate.count(anchor) != 2:
        raise ValueError('Unexpected generic API layout')
    candidate = candidate.replace(anchor, MCP + anchor)
    return candidate


def effective(user):
    result = run(['/usr/sbin/sshd', '-T', '-C', f'user={user},host=localhost,addr=127.0.0.1'])
    return dict(line.split(' ', 1) for line in result.splitlines())


def verify_ssh():
    values = effective(USER)
    expected = {'allowtcpforwarding': 'remote', 'allowstreamlocalforwarding': 'no',
                'gatewayports': 'no', 'permitlisten': '127.0.0.1:8002', 'permitopen': 'none',
                'maxsessions': '0', 'permittty': 'no', 'allowagentforwarding': 'no',
                'passwordauthentication': 'no', 'permituserrc': 'no', 'permittunnel': 'no',
                'forcecommand': '/bin/false', 'authenticationmethods': 'publickey'}
    if any(values.get(k) != v for k, v in expected.items()):
        raise RuntimeError('Dedicated SSH restrictions did not take effect')
    return expected


def verify_tunnel():
    listeners = run(['ss', '-H', '-lntp', 'sport = :8002'])
    lines = listeners.splitlines()
    if len(lines) != 1 or lines[0].split()[3] != '127.0.0.1:8002' or 'sshd' not in lines[0]:
        raise RuntimeError('Tunnel must listen only on IPv4 loopback through sshd')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(NEW + '/health', timeout=10) as response:
        result = json.load(response)
    if result.get('status') != 'ok' or result.get('database') != 'connected':
        raise RuntimeError('Office backend health failed through tunnel')
    return {'listener': '127.0.0.1:8002', 'health': result, 'restrictions': verify_ssh()}


def install_server(key):
    if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+ ark-office-beijing-tunnel', key):
        raise ValueError('Unexpected dedicated public key')
    marker = ROOT / 'server.json'
    auth = 'restrict,port-forwarding,permitlisten="127.0.0.1:8002",command="/bin/false" ' + key + '\n'
    authorized = HOME / '.ssh/authorized_keys'
    if marker.exists():
        prior = json.loads(marker.read_text())
        if prior['key_hash'] != digest(key) or SSHD.read_text() != SSH_CONFIG or authorized.read_text() != auth:
            raise RuntimeError('Dedicated SSH state drift')
        return {'status': 'verified-existing', 'restrictions': verify_ssh()}
    if SSHD.exists() or HOME.exists() or subprocess.run(['id', USER], capture_output=True).returncode == 0:
        raise RuntimeError('Unowned tunnel account/config already exists')
    if run(['ss', '-H', '-lnt', 'sport = :8002']):
        raise RuntimeError('Port 8002 already occupied')
    admin = effective('ubuntu')
    # Journal before the first mutation; partial installation requires inspection.
    save(ROOT / 'server-intent.json', {'key_hash': digest(key), 'status': 'installing'})
    run(['useradd', '--system', '--create-home', '--home-dir', str(HOME), '--shell', '/usr/sbin/nologin', USER])
    (HOME / '.ssh').mkdir(mode=0o700)
    authorized.write_text(auth)
    authorized.chmod(0o600)
    run(['chown', '-R', USER + ':' + USER, str(HOME)])
    SSHD.write_text(SSH_CONFIG)
    SSHD.chmod(0o600)
    try:
        run(['/usr/sbin/sshd', '-t'])
        restrictions = verify_ssh()
        if effective('ubuntu') != admin:
            raise RuntimeError('Administrative SSH configuration changed')
        run(['systemctl', 'reload', 'ssh'])
    except Exception:
        # Preserve the account/key for diagnosis, disable only this exact snippet.
        if SSHD.read_text() == SSH_CONFIG:
            SSHD.rename(ROOT / 'rejected-sshd.conf')
        raise
    save(marker, {'key_hash': digest(key), 'status': 'installed'})
    return {'status': 'installed', 'restrictions': restrictions}


def routes(action, request):
    state = ROOT / 'routes.json'
    path = NGINX.resolve()
    if not path.is_relative_to('/etc/nginx'):
        raise ValueError('Unexpected Nginx target')
    original = path.read_text()
    if action == 'rollback':
        record = json.loads(state.read_text())
        if record['status'] not in {'activated', 'activating'} or digest(original) != record['candidate']:
            raise RuntimeError('Routing rollback blocked by status/config drift')
        candidate = (ROOT / 'nginx-before.conf').read_text()
        if digest(candidate) != record['baseline']:
            raise RuntimeError('Routing backup drift')
    else:
        verify_tunnel()
        candidate = render(original)
        record = {'baseline': digest(original), 'candidate': digest(candidate), 'status': 'prepared'}
        if action == 'routes-prepare':
            if state.exists() and json.loads(state.read_text())['status'] in {'activating', 'activated'}:
                raise RuntimeError('Existing activation must be verified or rolled back')
            (ROOT / 'nginx-candidate.conf').write_text(candidate)
            save(state, record)
            return record
        if any(request.get(k) != record[k] for k in ('baseline', 'candidate')):
            raise RuntimeError('Routing configuration changed after prepare')
        prior = json.loads(state.read_text())
        if prior != record:
            raise RuntimeError('Prepared routing receipt changed')
        (ROOT / 'nginx-before.conf').write_text(original)
        record['status'] = 'activating'
        save(state, record)
    if path.read_text() != original:
        raise RuntimeError('Concurrent Nginx change')
    try:
        path.write_text(candidate)
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        if path.read_text() != candidate:
            raise RuntimeError('Nginx changed during reload')
        if action != 'rollback':
            verify_tunnel()
    except Exception:
        if path.read_text() != candidate:
            raise RuntimeError('Config drift prevents automatic rollback') from None
        path.write_text(original)
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        # A failed rollback restored the active candidate and remains retryable.
        record['status'] = 'activated' if action == 'rollback' else 'failed-restored'
        save(state, record)
        raise
    record['status'] = 'rolled-back' if action == 'rollback' else 'activated'
    save(state, record)
    return record


def execute(request):
    if socket.gethostname() != 'VM-4-6-ubuntu' or os.geteuid() != 0:
        raise RuntimeError('Unexpected Beijing host/identity')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    action = request['action']
    if action == 'prepare':
        return {'host': socket.gethostname(), 'host_key': ' '.join(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()[:2]),
                'nginx': digest(NGINX.read_text()), 'port8002': run(['ss', '-H', '-lnt', 'sport = :8002'])}
    if action == 'server':
        return install_server(request['public_key'])
    if action == 'verify':
        # NSSM can need several seconds after a requested reconnect.
        for attempt in range(6):
            try:
                return verify_tunnel()
            except (RuntimeError, OSError):
                if attempt == 5:
                    raise
                time.sleep(2)
    if action in {'routes-prepare', 'routes-activate', 'rollback'}:
        return routes(action, request)
    raise ValueError('Unknown remote action')


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))))
