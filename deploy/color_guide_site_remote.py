"""Fixed-domain nginx/TLS setup with drift guards and retained recovery evidence."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

DOMAIN = 'color-guide.leshine.cloud'
CONFIG = Path('/etc/nginx/conf.d/color-guide.leshine.cloud.conf')
STATE = Path('/home/ubuntu/commission-system/.deploy_state/color-guide-site')
CERT = Path('/etc/letsencrypt/live') / DOMAIN / 'fullchain.pem'
HOOK = Path('/etc/letsencrypt/renewal-hooks/deploy/ark-reload-nginx')
CHALLENGE_ROOT = Path('/var/www/letsencrypt')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def config_digest():
    return digest(CONFIG.read_bytes()) if CONFIG.exists() else None


def run(args):
    result = subprocess.run(args, capture_output=True, timeout=240)
    if result.returncode:
        raise RuntimeError('Command failed: ' + args[0] + '; ' + result.stderr.decode(errors='replace')[-1000:])
    return result.stdout


def atomic(path, data, mode=0o600):
    temporary = path.with_name(path.name + '.next')
    with temporary.open('wb') as stream:
        os.chmod(temporary, mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def record(path, value):
    atomic(path, json.dumps(value).encode())


@contextmanager
def locked():
    import fcntl
    if STATE.is_symlink() or CONFIG.is_symlink():
        raise RuntimeError('Managed site paths must not be symlinks')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    with (STATE / 'lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def validate(request):
    if request.get('domain') != DOMAIN or request.get('phase') not in {'plan', 'configure', 'verify'}:
        raise ValueError('Unregistered color-guide target or phase')
    template = request['template']
    if digest(template.encode()) != request['digest']:
        raise ValueError('Template digest mismatch')
    required = ['server_name ' + DOMAIN + ';', 'root /var/www/ark-static/color-guide;',
                'location /api/ { return 404; }', 'location ~ /\\. { return 404; }',
                'ssl_certificate ' + CERT.as_posix() + ';']
    if any(part not in template for part in required) or 'proxy_pass' in template:
        raise ValueError('Static-only boundary is incomplete')
    addresses = {item[4][0] for item in socket.getaddrinfo(DOMAIN, 80)}
    if addresses != {'154.8.205.162'}:
        raise RuntimeError('DNS does not exclusively select Beijing')
    run(['nginx', '-t'])
    current_file = None
    for line in run(['nginx', '-T']).decode().splitlines():
        if line.startswith('# configuration file '):
            current_file = line[len('# configuration file '):].rstrip(':')
        if 'server_name' in line and DOMAIN in line and current_file != str(CONFIG):
            raise RuntimeError('Domain belongs to another nginx configuration')
    if (STATE / 'pending.json').exists() or (STATE / 'certificate-pending.json').exists():
        raise RuntimeError('Interrupted site operation requires readback and explicit recovery')
    receipt = STATE / 'current.json'
    if CONFIG.exists() and not receipt.exists():
        raise RuntimeError('Existing unmanaged configuration cannot be overwritten')
    if receipt.exists() and config_digest() != json.loads(receipt.read_text())['config_digest']:
        raise RuntimeError('Managed color-guide configuration drift')


def install(content):
    candidate = content.encode()
    before = CONFIG.read_bytes() if CONFIG.exists() else None
    if before == candidate:
        return
    backup = STATE / ('backup-' + uuid.uuid4().hex)
    backup.mkdir(mode=0o700)
    if before is not None:
        atomic(backup / 'nginx.conf', before)
    pending = {'config_digest': digest(candidate), 'previous_digest': digest(before) if before else None,
               'backup': str(backup)}
    record(STATE / 'pending.json', pending)
    atomic(CONFIG, candidate, 0o644)
    try:
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    except Exception:
        if config_digest() != digest(candidate):
            raise RuntimeError('Install failed with drift; recovery evidence retained') from None
        if before is None:
            CONFIG.unlink()
        else:
            atomic(CONFIG, before, 0o644)
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        record(STATE / 'failure.json', pending)
        (STATE / 'pending.json').unlink()
        raise
    record(STATE / 'current.json', {'domain': DOMAIN, 'config_digest': digest(candidate), 'backup': str(backup)})
    (STATE / 'pending.json').unlink()


def probe(path, body=False):
    args = ['curl', '--silent', '--show-error', '--max-time', '15', '--resolve', DOMAIN + ':443:127.0.0.1']
    args += ['--fail'] if body else ['--output', '/dev/null', '--write-out', '%{http_code}']
    return run([*args, 'https://' + DOMAIN + path])


def restore_snapshot(before, receipt, expected):
    if config_digest() != expected:
        raise RuntimeError('Configuration drift; snapshot restore withheld')
    record(STATE / 'pending.json', {'phase': 'restore', 'expected': expected,
                                  'previous_digest': digest(before) if before else None})
    if before is None:
        CONFIG.unlink(missing_ok=True)
    else:
        atomic(CONFIG, before, 0o644)
    run(['nginx', '-t'])
    run(['systemctl', 'reload', 'nginx'])
    if receipt is None:
        (STATE / 'current.json').unlink(missing_ok=True)
    else:
        record(STATE / 'current.json', receipt)
    (STATE / 'pending.json').unlink()


def verify(index_sha256=None):
    run(['openssl', 'x509', '-in', str(CERT), '-noout', '-checkhost', DOMAIN])
    run(['openssl', 'x509', '-in', str(CERT), '-noout', '-checkend', '86400'])
    probes = {path: int(probe(path)) for path in ('/.env', '/api/auth/me', '/missing-color-guide-resource')}
    if any(code != 404 for code in probes.values()):
        raise RuntimeError('Static-only boundary verification failed')
    if index_sha256 and digest(probe('/index.html', body=True)) != index_sha256:
        raise RuntimeError('Live index does not match the reviewed artifact')
    return {'https_verified': True, 'boundaries': probes, 'index_verified': bool(index_sha256)}


def execute(request):
    validate(request)
    if request['phase'] == 'plan':
        return {'domain': DOMAIN, 'dns_verified': True, 'config_digest': config_digest()}
    if request['phase'] == 'verify':
        if not re.fullmatch(r'[0-9a-f]{64}', request.get('index_sha256', '')):
            raise ValueError('Verification needs the approved index digest')
        return verify(request['index_sha256'])
    if request.get('expected') != config_digest():
        raise RuntimeError('Configuration changed after preparation')
    if not CERT.exists():
        initial = CONFIG.read_bytes() if CONFIG.exists() else None
        receipt_path = STATE / 'current.json'
        initial_receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        challenge = ('server { listen 80; server_name ' + DOMAIN + ';\n'
                     'location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }\n'
                     'location / { return 503; } }\n')
        CHALLENGE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o755)
        install(challenge)
        record(STATE / 'certificate-pending.json', {'domain': DOMAIN, 'phase': 'issuing',
               'config_digest': digest(challenge.encode())})
        try:
            run(['certbot', 'certonly', '--non-interactive', '--agree-tos', '--webroot',
                 '-w', '/var/www/letsencrypt', '--cert-name', DOMAIN, '-d', DOMAIN])
        except Exception:
            # Keep the issuance marker: a timeout is not permission to issue again.
            restore_snapshot(initial, initial_receipt, digest(challenge.encode()))
            raise
        (STATE / 'certificate-pending.json').unlink()
    previous = CONFIG.read_text() if CONFIG.exists() else None
    install(request['template'])
    if not HOOK.exists():
        HOOK.parent.mkdir(parents=True, exist_ok=True)
        atomic(HOOK, b'#!/bin/sh\nnginx -t && systemctl reload nginx\n', 0o755)
    try:
        # nginx reload is asynchronous; bounded probes wait for new workers.
        deadline = time.monotonic() + 15
        while True:
            try:
                return verify()
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.5)
    except Exception:
        if config_digest() != request['digest']:
            raise RuntimeError('Verification failed with drift; rollback withheld') from None
        if previous != request['template']:
            restore = previous or ('server { listen 80; server_name ' + DOMAIN + ';\n'
                'location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }\n'
                'location / { return 503; } }\n')
            install(restore)
        raise


if __name__ == '__main__':
    request = json.load(sys.stdin)
    with locked():
        print(json.dumps(execute(request)), flush=True)
