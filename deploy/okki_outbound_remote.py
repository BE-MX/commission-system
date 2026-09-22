"""Narrow, checksummed deployment of the Singapore outbound worker."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path('/root/.openclaw/workspace/okki-sync')
NODE = '/root/.nvm/versions/node/v22.22.1/bin/node'
UNITS = Path('/etc/systemd/system')
NAMES = {'okki_outbound_poller.js', 'okki_outbound_creator.mjs',
         'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer'}
TIMER = 'ark-okki-outbound-poller.timer'
SERVICE = 'ark-okki-outbound-poller.service'


def save(path, record):
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(record), encoding='utf-8')
    os.replace(temporary, path)


def timer_state():
    state = dict(line.split('=', 1) for line in run([
        'systemctl', 'show', TIMER, '-p', 'LoadState', '-p', 'ActiveState', '-p', 'UnitFileState',
    ]).splitlines())
    if state.get('LoadState') != 'loaded' or state.get('ActiveState') not in {'active', 'inactive'}:
        raise RuntimeError('Outbound timer is missing or unstable')
    if state.get('UnitFileState') not in {'enabled', 'disabled'}:
        raise RuntimeError('Outbound timer enablement requires inspection')
    return {'active': state['ActiveState'] == 'active', 'enabled': state['UnitFileState'] == 'enabled'}


def drain():
    # Stop scheduling only; do not kill a potentially accepted submission.
    run(['systemctl', 'stop', TIMER])
    deadline = time.monotonic() + 180
    while True:
        state = dict(line.split('=', 1) for line in run([
            'systemctl', 'show', SERVICE, '-p', 'LoadState', '-p', 'ActiveState', '-p', 'MainPID',
        ]).splitlines())
        if state.get('LoadState') != 'loaded':
            raise RuntimeError('Outbound service is missing')
        if state.get('ActiveState') in {'inactive', 'failed'} and state.get('MainPID') == '0':
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('Outbound service still running; scheduling remains paused, inspect release journal')
        time.sleep(2)

def run(args, **kwargs):
    result = subprocess.run(args, check=True, text=True, capture_output=True, timeout=300, **kwargs)
    return result.stdout.strip()

def execute(request):
    if set(request['files']) != NAMES or request['action'] not in {'prepare', 'freeze', 'activate', 'verify'}:
        raise ValueError('Invalid outbound deployment request')
    bodies = {name: base64.b64decode(value['content'], validate=True) for name, value in request['files'].items()}
    for name, body in bodies.items():
        if hashlib.sha256(body).hexdigest() != request['files'][name]['sha256']:
            raise ValueError('Artifact digest mismatch')
    digest = hashlib.sha256(json.dumps({name: request['files'][name]['sha256'] for name in sorted(NAMES)}).encode()).hexdigest()
    stage = ROOT / '.deploy-state' / 'ark-outbound' / digest
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink() or stage.resolve().parent != (ROOT / '.deploy-state' / 'ark-outbound').resolve():
        raise ValueError('Unexpected deployment path')
    journal = stage.parent / 'release-current.json'
    previous = json.loads(journal.read_text()) if journal.exists() else None
    coordinated = request.get('coordinated', False)
    revision = request.get('revision')
    release_id = request.get('release_id')
    if coordinated and not re.fullmatch(r'[0-9a-f]{40}', revision or ''):
        raise ValueError('Coordinated outbound release requires a pinned revision')
    if coordinated and not re.fullmatch(r'[0-9a-f]{32}', release_id or ''):
        raise ValueError('Coordinated outbound release requires a release ID')
    pending = previous and previous.get('status') != 'completed'
    if pending and (previous['digest'] != digest or previous.get('revision') != revision
                    or previous.get('release_id') != release_id or not coordinated):
        raise RuntimeError('Previous coordinated outbound release requires inspection: ' + str(journal))
    config = ROOT / '.ark-outbound.env'
    if not config.is_file() or config.stat().st_mode & 0o077:
        raise RuntimeError('Protected .ark-outbound.env required (mode 600)')
    if not Path(NODE).is_file() or not (ROOT / 'auth.js').is_file():
        raise RuntimeError('Existing Node/auth runtime missing')
    for name, body in bodies.items():
        target = stage / name
        if target.is_symlink(): raise ValueError('Staging symlink rejected')
        if not target.exists() or target.read_bytes() != body: target.write_bytes(body)
    for name in ['auth.js', 'node_modules']:
        target = stage / name
        if not target.exists(): target.symlink_to(ROOT / name)
    for name in ['okki_outbound_poller.js', 'okki_outbound_creator.mjs']:
        run([NODE, '--check', str(stage / name)])
    run(['systemd-analyze', 'verify', str(stage / 'ark-okki-outbound-poller.service'), str(stage / 'ark-okki-outbound-poller.timer')])
    # Load only remote protected credentials. EXPLAIN validates UPDATE permission
    # without executing an UPDATE or touching task state.
    probe = """import mysql from 'mysql2/promise';
const c=await mysql.createConnection({host:process.env.ARK_DB_HOST,port:Number(process.env.ARK_DB_PORT||3306),user:process.env.ARK_DB_USER,password:process.env.ARK_DB_PASSWORD,database:process.env.ARK_DB_NAME});
try {await c.query('SELECT id,status FROM ark_okki_outbound_tasks LIMIT 1'); await c.query('SELECT id,invoice_no FROM ark_invoices LIMIT 1'); await c.query(\"EXPLAIN UPDATE ark_okki_outbound_tasks SET status='pending' WHERE id=-1\"); const s=process.env.ARK_BUSINESS_DB_NAME; if(!/^[A-Za-z0-9_]+$/.test(s||''))throw Error('Invalid schema'); await c.query('SELECT order_id FROM `'+s+'`.okki_outbound_record_items LIMIT 1');} finally {await c.end();}"""
    if request['action'] not in {'prepare', 'freeze'} or not request.get('allow_pending'):
        probe = probe.replace("try {", "try {await c.query('SELECT linked_sync_id,sync_status,status,remark FROM ark_invoices LIMIT 0'); await c.query('SELECT invoice_id,order_id,attempts,reason,last_error,processed_at,updated_at FROM ark_okki_outbound_tasks LIMIT 0'); ")
    run([NODE, '--env-file=' + str(config), '--input-type=module', '-e', probe], cwd=ROOT)
    if request['action'] == 'prepare':
        return {'status': 'prepared', 'digest': digest, 'target': str(ROOT)}
    def verify_bytes():
        for name, body in bodies.items():
            dest = UNITS / name if name.endswith(('.service', '.timer')) else ROOT / name
            if dest.is_symlink() or not dest.is_file() or dest.read_bytes() != body:
                raise RuntimeError('Active outbound digest mismatch')

    if request['action'] == 'verify':
        verify_bytes()
        if not previous or previous.get('status') not in {'activated', 'completed'} or previous['digest'] != digest or previous.get('revision') != revision or previous.get('release_id') != release_id:
            raise RuntimeError('Outbound activation receipt is missing')
        if timer_state() != previous['baseline']:
            raise RuntimeError('Outbound schedule differs from recorded baseline')
        previous['status'] = 'completed'
        save(journal, previous)
        return {'status': 'verified', 'digest': digest, 'schedule': previous['baseline']}
    if request['action'] == 'freeze':
        if not coordinated:
            raise ValueError('Freeze requires a coordinated release')
        if not pending:
            previous = {'digest': digest, 'revision': revision, 'release_id': release_id,
                        'status': 'freezing', 'baseline': timer_state()}
            save(journal, previous)
        drain()
        previous['status'] = 'frozen'
        save(journal, previous)
        return {'status': 'frozen', 'digest': digest, 'schedule': previous['baseline']}
    if coordinated:
        if not pending or previous.get('status') != 'frozen':
            raise RuntimeError('Coordinated outbound release must freeze before activation')
        baseline = previous['baseline']
    else:
        baseline = {'active': True, 'enabled': True}  # Explicit outbound-only enables scheduling.
    drain()
    backup = stage / 'backup'
    backup.mkdir(mode=0o700, exist_ok=True)
    changed = []
    for name, body in bodies.items():
        dest = UNITS / name if name.endswith(('.service', '.timer')) else ROOT / name
        if dest.is_symlink(): raise ValueError('Managed destination is a symlink')
        if dest.exists() and dest.read_bytes() == body: continue
        old = dest.read_bytes() if dest.exists() else None
        if old is not None and not (backup / name).exists(): (backup / name).write_bytes(old)
        changed.append((dest, old))
    try:
        for dest, old in changed:
            temporary = dest.with_name(dest.name + '.ark-next')
            temporary.write_bytes(bodies[dest.name]); os.replace(temporary, dest)
        run(['systemctl', 'daemon-reload'])
        verify_bytes()
        run(['systemctl', 'enable' if baseline['enabled'] else 'disable', TIMER])
        if baseline['active']:
            run(['systemctl', 'start', TIMER])
        if timer_state() != baseline:
            raise RuntimeError('Outbound timer baseline was not restored')
        save(journal, {'digest': digest, 'revision': revision, 'release_id': release_id,
                       'status': 'activated' if coordinated else 'completed', 'baseline': baseline})
    except Exception:
        subprocess.run(['systemctl', 'stop', TIMER], check=False, capture_output=True)
        # Keep deployed bytes and backup when activation may have started a
        # submission; never swap a creator while a child is running.
        raise
    return {'status': 'enabled', 'digest': digest, 'target': str(ROOT), 'changed_files': len(changed)}

if __name__ == '__main__':
    try:
        import fcntl
        lock_dir = ROOT / '.deploy-state' / 'ark-outbound'
        lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (lock_dir / 'release.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        # subprocess command/output may contain service configuration; no dumping.
        print('Outbound deployment failed: ' + (str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
