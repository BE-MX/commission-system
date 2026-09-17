"""Narrow, checksummed deployment of the Singapore outbound worker."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path('/root/.openclaw/workspace/okki-sync')
NODE = '/root/.nvm/versions/node/v22.22.1/bin/node'
NAMES = {'okki_outbound_poller.js', 'okki_outbound_creator.mjs',
         'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer'}

def run(args, **kwargs):
    result = subprocess.run(args, check=True, text=True, capture_output=True, timeout=300, **kwargs)
    return result.stdout.strip()

def execute(request):
    if set(request['files']) != NAMES or request['action'] not in {'prepare', 'activate'}:
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
    run([NODE, '--env-file=' + str(config), '--input-type=module', '-e', probe], cwd=ROOT)
    if request['action'] == 'prepare':
        return {'status': 'prepared', 'digest': digest, 'target': str(ROOT)}
    timer = 'ark-okki-outbound-poller.timer'
    service = 'ark-okki-outbound-poller.service'
    # Freeze scheduling before checking idle, including future upgrades.
    was_active = run(['systemctl', 'show', timer, '-p', 'ActiveState', '--value']) == 'active'
    if was_active: run(['systemctl', 'stop', timer])
    # Never replace code underneath an in-flight submission.
    deadline = time.monotonic() + 180
    while run(['systemctl', 'show', service, '-p', 'ActiveState', '--value']) not in {'inactive', 'failed'}:
        if time.monotonic() >= deadline:
            if was_active: run(['systemctl', 'start', timer])
            raise RuntimeError('Outbound service still running; retry after completion')
        time.sleep(2)
    backup = stage / 'backup'
    backup.mkdir(mode=0o700, exist_ok=True)
    changed = []
    for name, body in bodies.items():
        dest = Path('/etc/systemd/system') / name if name.endswith(('.service', '.timer')) else ROOT / name
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
        run(['systemctl', 'enable', '--now', timer])
        if run(['systemctl', 'is-active', timer]) != 'active': raise RuntimeError('Timer not active')
        if run(['systemctl', 'is-enabled', timer]) != 'enabled': raise RuntimeError('Timer not enabled')
        for name, body in bodies.items():
            dest = Path('/etc/systemd/system') / name if name.endswith(('.service', '.timer')) else ROOT / name
            if dest.read_bytes() != body: raise RuntimeError('Active digest mismatch')
    except Exception:
        subprocess.run(['systemctl', 'stop', timer], check=False, capture_output=True)
        # Keep deployed bytes and backup when activation may have started a
        # submission; never swap a creator while a child is running.
        raise
    return {'status': 'enabled', 'digest': digest, 'target': str(ROOT), 'changed_files': len(changed)}

if __name__ == '__main__':
    try:
        print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        # subprocess command/output may contain service configuration; no dumping.
        print('Outbound deployment failed: ' + (str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
