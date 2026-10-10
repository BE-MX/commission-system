"""Fixed Beijing customer-site boundary with restricted backup and drift-safe restore."""
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager

DOMAIN = 'shop.leshine.cloud'
ADDRESS = '154.8.205.162'
CONFIG = Path('/etc/nginx/conf.d/customer-orders.shop.leshine.cloud.conf')
STATE = Path('/home/ubuntu/commission-system/.deploy_state/customer-portal-site')
CERTIFICATE = Path('/etc/letsencrypt/live') / DOMAIN / 'fullchain.pem'
RENEW_HOOK = Path('/etc/letsencrypt/renewal-hooks/deploy/ark-reload-nginx')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=240)
    if result.returncode:
        # Operational commands have no credentials; never dump an entire nginx -T.
        raise RuntimeError('Command failed: ' + args[0] + '; ' + result.stderr[-1000:])
    return result.stdout


def atomic_json(path, value):
    temporary = path.with_suffix('.next')
    with temporary.open('w') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def site_lock():
    import fcntl
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    with (STATE / 'lock').open('a') as stream:
        os.chmod(STATE / 'lock', 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def recover_pending():
    journal = STATE / 'pending.json'
    if not journal.exists():
        return
    record = json.loads(journal.read_text())
    current = digest(CONFIG.read_bytes()) if CONFIG.exists() else None
    if current == record['config_digest']:
        try:
            run(['nginx', '-t'])
            run(['systemctl', 'reload', 'nginx'])
        except Exception:
            restore_pending(record)
            raise RuntimeError('Interrupted candidate failed verification; previous ingress restored') from None
        atomic_json(STATE / 'current.json', record)
    elif current == record['previous_digest']:
        # Disk rollback alone cannot establish what the nginx workers are using.
        restore_pending(record)
        return
    else:
        raise RuntimeError('Pending customer-site operation differs from both reviewed byte sets; restore withheld')
    journal.unlink()


def restore_pending(record):
    current = digest(CONFIG.read_bytes()) if CONFIG.exists() else None
    if current not in {record['config_digest'], record['previous_digest']}:
        raise RuntimeError('Customer-site bytes changed; restore withheld')
    if record['previous_digest'] is None:
        CONFIG.unlink(missing_ok=True)
    else:
        backup = Path(record['backup']).resolve()
        if backup.parent != STATE.resolve() or not re.fullmatch(r'backup-[0-9a-f]{32}', backup.name):
            raise RuntimeError('Invalid customer-site recovery path')
        before = (backup / 'nginx.conf').read_bytes()
        if digest(before) != record['previous_digest']:
            raise RuntimeError('Customer-site backup differs; restore withheld')
        temporary = CONFIG.with_suffix('.next')
        temporary.write_bytes(before)
        temporary.chmod(0o644)
        os.replace(temporary, CONFIG)
    run(['nginx', '-t'])
    run(['systemctl', 'reload', 'nginx'])
    if record.get('previous_receipt'):
        atomic_json(STATE / 'current.json', record['previous_receipt'])
    else:
        (STATE / 'current.json').unlink(missing_ok=True)
    (STATE / 'pending.json').unlink()


def validate_identity(request):
    if request['domain'] != DOMAIN or request['phase'] not in {'plan', 'https', 'verify'}:
        raise ValueError('Unregistered customer-site target or phase')
    if not re.fullmatch(r'[0-9a-f]{40}', request['revision']) or not re.fullmatch(r'[0-9a-f]{64}', request['script_digest']):
        raise ValueError('Reviewed source identity is required')
    template = request['template']
    if digest(template.encode()) != request['digest']:
        raise ValueError('Customer-site template digest differs')
    required = ['server_name ' + DOMAIN + ';', 'proxy_pass http://127.0.0.1:8001;',
        'location ^~ /api/portal/v1/', 'location /api/ { return 404; }',
        'proxy_set_header Authorization "";', 'proxy_set_header X-Real-IP $remote_addr;',
        'proxy_set_header X-Forwarded-For "";', 'proxy_set_header X-Forwarded-Proto "";',
        'proxy_set_header Forwarded "";', 'root /var/www/ark-static/customer-orders;', 'access_log off;']
    if any(value not in template for value in required):
        raise ValueError('Customer-only API boundary is incomplete')


def validate(request):
    validate_identity(request)
    addresses = {item[4][0] for item in socket.getaddrinfo(DOMAIN, 80)}
    if addresses != {ADDRESS}:
        raise RuntimeError('DNS does not exclusively select the approved Beijing address')
    run(['nginx', '-t'])
    dump = run(['nginx', '-T'])
    current_file = None
    for line in dump.splitlines():
        if line.startswith('# configuration file '):
            current_file = line[len('# configuration file '):].rstrip(':')
        if 'server_name' in line and DOMAIN in line and current_file != str(CONFIG):
            raise RuntimeError('Domain is already owned by another nginx configuration')
    if CONFIG.exists() and not (STATE / 'current.json').exists():
        raise RuntimeError('Unmanaged existing customer configuration; inspect before adoption')
    if (STATE / 'current.json').exists():
        record = json.loads((STATE / 'current.json').read_text())
        if not CONFIG.is_file() or digest(CONFIG.read_bytes()) != record['config_digest']:
            raise RuntimeError('Customer-site configuration drift; do not overwrite')


def install(content):
    previous = CONFIG.read_bytes() if CONFIG.exists() else None
    candidate = content.encode()
    if previous == candidate:
        return
    backup = STATE / ('backup-' + uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    if previous is not None:
        (backup / 'nginx.conf').write_bytes(previous)
        (backup / 'nginx.conf').chmod(0o600)
    record = {'domain': DOMAIN, 'config_digest': digest(candidate), 'backup': str(backup),
        'previous_digest': digest(previous) if previous is not None else None,
        'previous_receipt': json.loads((STATE / 'current.json').read_text()) if (STATE / 'current.json').exists() else None}
    atomic_json(STATE / 'pending.json', record)
    next_file = CONFIG.with_suffix('.next')
    next_file.write_bytes(candidate)
    next_file.chmod(0o644)
    os.replace(next_file, CONFIG)
    try:
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    except Exception:
        restore_pending(record)
        raise
    atomic_json(STATE / 'current.json', record)
    (STATE / 'pending.json').unlink()


def status(path):
    try:
        with urllib.request.urlopen('https://' + DOMAIN + path, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def verify():
    run(['openssl', 'x509', '-in', str(CERTIFICATE), '-noout', '-checkhost', DOMAIN])
    run(['openssl', 'x509', '-in', str(CERTIFICATE), '-noout', '-checkend', '86400'])
    run(['nginx', '-t'])
    probes = {path: status(path) for path in ('/api/portal/admin/v1/settings', '/api/auth/me', '/api/health',
        '/.env', '/api/portal/v1/session')}
    if any(probes[path] != 404 for path in probes if path != '/api/portal/v1/session'):
        raise RuntimeError('Customer site exposes a forbidden employee/API/file route')
    if probes['/api/portal/v1/session'] not in {401, 503}:
        raise RuntimeError('Customer session boundary probe failed')
    return {'domain': DOMAIN, 'https_verified': True, 'api_boundaries': probes,
        'static_index_present': Path('/var/www/ark-static/customer-orders/index.html').is_file(),
        'business_accepted': False}


def execute(request):
    validate(request)
    if request['phase'] == 'plan':
        return {'domain': DOMAIN, 'dns_verified': True, 'phase': 'planned', 'business_accepted': False}
    if request['phase'] == 'verify':
        return verify()
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    if not CERTIFICATE.exists():
        challenge = ('server { listen 80; server_name ' + DOMAIN + '; access_log off;\n'
            'location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }\n'
            'location / { return 503; } }\n')
        Path('/var/www/letsencrypt').mkdir(parents=True, exist_ok=True, mode=0o755)
        install(challenge)
        run(['certbot', 'certonly', '--non-interactive', '--agree-tos', '--webroot',
            '-w', '/var/www/letsencrypt', '--cert-name', DOMAIN, '-d', DOMAIN])
    # Public failure restores the last known safe ingress bytes using the same
    # journal and digest guard. A certificate can safely remain for the retry.
    previous = CONFIG.read_text() if CONFIG.exists() else None
    install(request['template'])
    hook = RENEW_HOOK
    if not hook.exists():
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text('#!/bin/sh\nnginx -t && systemctl reload nginx\n')
        hook.chmod(0o755)
    try:
        return verify()
    except Exception:
        if digest(CONFIG.read_bytes()) != request['digest']:
            raise RuntimeError('Public verification failed with configuration drift; rollback withheld') from None
        restore = previous or ('server { listen 80; server_name ' + DOMAIN + '; access_log off;\n'
            'location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }\n'
            'location / { return 503; } }\n')
        if restore != request['template']:
            install(restore)
        atomic_json(STATE / 'failure.json', {'domain': DOMAIN,
            'status': 'public-verification-failed', 'config_digest': digest(CONFIG.read_bytes()),
            'restored_previous': previous is not None and previous != request['template']})
        raise


if __name__ == '__main__':
    request = json.load(sys.stdin)
    validate_identity(request)
    with site_lock():
        if request['phase'] == 'https':
            recover_pending()
        elif (STATE / 'pending.json').exists():
            raise RuntimeError('An interrupted site operation requires the pinned https recovery; verify/plan remain read-only')
        print(json.dumps(execute(request)), flush=True)
