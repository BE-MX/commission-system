"""Merge the confirmed Beijing password-access overlay; never replace the whole env.

Only read access is enabled here. Ordering, PI, mail and outbound stay separately gated.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import stat
import subprocess
import sys
import urllib.request
import uuid
import time

ROOT = Path('/home/ubuntu/commission-system')
ENV = ROOT / 'backend/.env'
STATE = ROOT / '.deploy_state/customer-portal-config'


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_text(content, overlay):
    lines, pending = [], dict(overlay)
    for line in content.splitlines():
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
        lines.append(key + '=' + pending.pop(key) if key in pending else line)
    if pending:
        lines.append('# Managed customer password access; separate business acceptance gates remain off')
        lines.extend(key + '=' + value for key, value in pending.items())
    return '\n'.join(lines) + '\n'


def portal_values(content):
    values = {}
    for line in content.splitlines():
        match = re.match(r'^\s*(export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=', line)
        if not match or not match[2].upper().startswith('PORTAL_'):
            continue
        key = match[2]
        # Reject alternate dotenv spellings before generating a durable key.
        if key != key.upper() or match[1] or key in values:
            raise RuntimeError('Noncanonical or duplicate portal env key requires protected inspection')
        raw = line.split('=', 1)[1].strip()
        if '#' in raw or '\n' in raw or (raw[:1] in {'"', "'"} and raw[-1:] != raw[:1]):
            raise RuntimeError('Unsupported portal dotenv value requires protected inspection')
        values[key] = raw[1:-1] if raw[:1] in {'"', "'"} else raw
    return values


def service_environment(allow_stopped=False):
    pid = subprocess.check_output(['systemctl', 'show', 'ark-backend', '-p', 'MainPID', '--value'], text=True).strip()
    if pid == '0' and allow_stopped:
        return None
    directory = Path('/proc/' + pid)
    environment = dict(part.split(b'=', 1) for part in (directory / 'environ').read_bytes().split(b'\0') if b'=' in part)
    if any(key.upper().startswith(b'PORTAL_') for key in environment):
        raise RuntimeError('Service environment overrides portal config; merge its protected owner first')
    if (directory / 'cwd').resolve() != (ROOT / 'backend').resolve():
        raise RuntimeError('Running backend configuration owner differs from the managed root')
    return {os.fsdecode(key): os.fsdecode(value) for key, value in environment.items()}


def service_identity():
    import pwd, grp
    name = subprocess.check_output(['systemctl', 'show', 'ark-backend', '-p', 'User', '--value'], text=True).strip() or 'root'
    group = subprocess.check_output(['systemctl', 'show', 'ark-backend', '-p', 'Group', '--value'], text=True).strip()
    account = pwd.getpwnam(name)
    return account.pw_uid, grp.getgrnam(group).gr_gid if group else account.pw_gid


def apply_failure(phase, restore, stop):
    if phase in {'stop-orders', 'close'}:
        stop()
        return 'failed_paused'
    restore()
    return 'restored'


def runtime_probe(environment=None, identity=None):
    code = '''import json,sys
try:
 from app.core.config import get_settings
 from sqlalchemy import create_engine,text
 s=get_settings();e=create_engine(s.commission_db_url,hide_parameters=True)
 with e.connect() as c:
  c.execute(text('START TRANSACTION READ ONLY'))
  revisions=c.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
  namespaces=c.execute(text("SELECT DISTINCT source_account_key FROM ark_customer_external_identities WHERE source_system='okki'")).scalars().all()
  c.rollback()
 e.dispose()
 print(json.dumps({'revision':revisions,'namespace_present':'leshine-okki' in namespaces,
  'enabled':s.PORTAL_ENABLED,'writes':s.PORTAL_WRITES_ENABLED,'invoice':s.PORTAL_INVOICE_ENABLED,
  'mail':s.PORTAL_MAIL_ENABLED,'notification':s.PORTAL_NOTIFICATION_ENABLED,'outbound':s.PORTAL_OUTBOUND_WORKER_ENABLED,
  'origin':s.PORTAL_ORIGIN,'auth_secret_present':bool(getattr(s,'PORTAL_AUTH_SECRET',''))}))
except Exception as error:
 print(json.dumps({'error_type':type(error).__name__}));sys.exit(1)
'''
    permissions = {'user':identity[0], 'group':identity[1], 'extra_groups':[]} if identity else {}
    result = subprocess.run([str(ROOT / 'backend/.venv/bin/python'), '-c', code], cwd=ROOT / 'backend',
        capture_output=True, text=True, timeout=30, env=environment, **permissions)
    if result.returncode:
        raise RuntimeError('Protected configuration/database validation failed; raw diagnostics withheld')
    return json.loads(result.stdout)


def execute(request):
    if request['phase'] not in {'prepare', 'enable-access', 'stop-orders', 'close'}:
        raise ValueError('Unknown customer configuration phase')
    from contextlib import ExitStack
    import fcntl
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True); STATE.chmod(0o700)
    with ExitStack() as stack:
        lock = stack.enter_context((STATE / 'lock').open('a'))
        os.chmod(STATE / 'lock', 0o600); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        live = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        phase = request['phase']
        environment = service_environment(allow_stopped=phase in {'stop-orders', 'close'})
        probe = runtime_probe(environment) if phase not in {'stop-orders', 'close'} else {}
        if phase not in {'stop-orders', 'close'} and not probe['namespace_present']:
            raise RuntimeError('Confirmed customer identity namespace is absent')
        if phase == 'enable-access' and (live != request['revision'] or probe['revision'] != ['181_portal_password_login']):
            raise RuntimeError('Password access requires the pinned activated application and actual revision 181')
        if phase == 'prepare' and probe['enabled']:
            raise RuntimeError('Preparation cannot silently close an already enabled portal')
        identity = service_identity()
        original = ENV.read_bytes(); metadata = ENV.stat(); before = hashlib.sha256(original).hexdigest()
        content = original.decode('utf-8')
        values = portal_values(content)
        overlay = {'PORTAL_ORIGIN':'https://shop.leshine.cloud', 'PORTAL_EMPLOYEE_ORIGIN':'https://leshine.cloud',
            'PORTAL_SITE_CODE':'leshine', 'PORTAL_OKKI_NAMESPACE':'leshine-okki', 'PORTAL_TRUSTED_PROXY_IPS':'["127.0.0.1"]',
            'PORTAL_WRITES_ENABLED':'false', 'PORTAL_INVOICE_ENABLED':'false', 'PORTAL_MAIL_ENABLED':'false',
            'PORTAL_NOTIFICATION_ENABLED':'false', 'PORTAL_OUTBOUND_WORKER_ENABLED':'false', 'PORTAL_OUTBOUND_WORKER_ACTOR_ID':'0'}
        for name in ('PORTAL_ORIGIN', 'PORTAL_EMPLOYEE_ORIGIN', 'PORTAL_SITE_CODE', 'PORTAL_OKKI_NAMESPACE'):
            if phase in {'prepare', 'enable-access'} and values.get(name) and values[name] != overlay[name]:
                raise RuntimeError('Existing customer config conflicts with the approved domain/business source')
        if phase == 'stop-orders':
            overlay = {name: 'false' for name in ('PORTAL_WRITES_ENABLED', 'PORTAL_INVOICE_ENABLED')}
        if phase in {'prepare', 'enable-access'}:
            retained = values.get('PORTAL_CSRF_KEYS')
            overlay['PORTAL_CSRF_KEYS'] = retained if retained and json.loads(retained) else json.dumps({'v1': secrets.token_hex(32)}, separators=(',', ':'))
            overlay['PORTAL_CSRF_KEY_VERSION'] = values.get('PORTAL_CSRF_KEY_VERSION') or 'v1'
            # Durable receipt key: retain it, never rotate on repeated setup.
            overlay['PORTAL_AUTH_SECRET'] = values.get('PORTAL_AUTH_SECRET') or secrets.token_hex(32)
            overlay['PORTAL_ENABLED'] = 'true' if phase == 'enable-access' else 'false'
        elif phase == 'close':
            overlay['PORTAL_ENABLED'] = 'false'
        else:
            overlay['PORTAL_ENABLED'] = values.get('PORTAL_ENABLED', 'false')
        candidate = merge_text(content, overlay).encode()
        backup = STATE / ('env-' + uuid.uuid4().hex)
        backup.write_bytes(original); backup.chmod(0o600)
        temporary = ENV.with_name('.env.portal-next')
        temporary.write_bytes(candidate); temporary.chmod(0o600); os.chown(temporary, *identity)
        if fingerprint(ENV) != before: raise RuntimeError('Protected env changed; merge withheld')
        os.replace(temporary, ENV)
        activated = False
        try:
            probe = runtime_probe(environment, identity) if phase == 'prepare' else {}
            if phase != 'prepare' and environment is not None:
                subprocess.run(['systemctl', 'restart', 'ark-backend'], check=True, timeout=45, capture_output=True)
                activated = True
                deadline = time.monotonic() + 35
                while True:
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3) as response:
                            health = json.load(response)
                        break
                    except (OSError, ValueError):
                        if time.monotonic() >= deadline: raise RuntimeError('Backend readiness timed out') from None
                        time.sleep(1)
                if health.get('status') != 'ok' or health.get('database') != 'connected':
                    raise RuntimeError('Backend readiness failed after customer overlay')
                probe = runtime_probe(service_environment(), identity)
                expected = {'enabled':'PORTAL_ENABLED', 'writes':'PORTAL_WRITES_ENABLED', 'invoice':'PORTAL_INVOICE_ENABLED',
                    'mail':'PORTAL_MAIL_ENABLED', 'notification':'PORTAL_NOTIFICATION_ENABLED', 'outbound':'PORTAL_OUTBOUND_WORKER_ENABLED'}
                if any(probe[key] != (overlay[name].lower() == 'true') for key, name in expected.items() if name in overlay):
                    raise RuntimeError('Running service environment does not match the requested gates')
        except Exception:
            def restore():
                if fingerprint(ENV) != hashlib.sha256(candidate).hexdigest():
                    raise RuntimeError('Customer overlay failed with config drift; restore withheld') from None
                temporary.write_bytes(original); temporary.chmod(stat.S_IMODE(metadata.st_mode)); os.chown(temporary, metadata.st_uid, metadata.st_gid)
                os.replace(temporary, ENV)
                if activated or phase != 'prepare':
                    subprocess.run(['systemctl', 'restart', 'ark-backend'], check=True, timeout=45, capture_output=True)
            def stop():
                # A failed stop must never reopen the previous write-enabled configuration.
                subprocess.run(['systemctl', 'stop', 'ark-backend'], check=True, timeout=45, capture_output=True)
                receipt = {'phase':phase, 'status':'failed_paused', 'application_revision':live,
                    'config_digest':fingerprint(ENV), 'business_accepted':False}
                (STATE / 'current.json').write_text(json.dumps(receipt)); (STATE / 'current.json').chmod(0o600)
            status = apply_failure(phase, restore, stop)
            raise RuntimeError('Customer overlay validation failed; state=' + status) from None
        receipt = {'phase':phase,'application_revision':live,'config_digest':fingerprint(ENV),'backup':str(backup),
            'merged_keys':sorted(overlay),'probe':probe,'business_accepted':False,
            'status':'closed_paused' if environment is None else 'validated'}
        (STATE / 'current.json').write_text(json.dumps(receipt)); (STATE / 'current.json').chmod(0o600)
        return receipt


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))), flush=True)
