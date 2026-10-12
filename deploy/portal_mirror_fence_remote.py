"""Hold the existing mirror cron lock across the portal maintenance window."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

DIRECTORY = Path('/var/lib/ark-schema-maintenance')
UNIT = 'ark-schema-outbound-mirror-fence.service'
CRON = Path('/etc/cron.d/ark-agent-sync')
SCRIPT = DIRECTORY / 'mirror-fence.py'
RECORD = DIRECTORY / 'mirror-fence.json'
APPROVED_CRON_SHA256 = '13e3a254126d0cc67a65aea38f0c12cebc99968da2af6fa396196b5c0ee5053f'
HOLDER = '''import fcntl,os,socket,time
from pathlib import Path
deadline=time.monotonic()+120
with open('/tmp/okki-outbound.lock','a') as lock:
 while True:
  try:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); break
  except BlockingIOError:
   if time.monotonic()>=deadline: raise RuntimeError('Mirror lock drain timed out')
   time.sleep(.2)
 while True:
  busy=False
  for p in Path('/proc').iterdir():
   if not p.name.isdigit(): continue
   try: args=(p/'cmdline').read_bytes().split(b'\\0')
   except (FileNotFoundError,ProcessLookupError,PermissionError): continue
   if args and Path(os.fsdecode(args[0])).name=='node' and any(Path(os.fsdecode(a)).name in {'sync-outbound.js','resync-outbound-by-order.js'} for a in args[1:]): busy=True
  if not busy: break
  if time.monotonic()>=deadline: raise RuntimeError('Manual mirror drain timed out')
  time.sleep(.2)
 address=os.environ['NOTIFY_SOCKET']
 if address.startswith('@'): address='\\0'+address[1:]
 with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as notify:
  notify.connect(address); notify.sendall(b'READY=1')
 while True: time.sleep(60)
'''


def command(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=140)
    if check and result.returncode:
        raise RuntimeError('Mirror maintenance command failed; original cron retained')
    return result


def unit_state():
    result = command(['systemctl', 'show', UNIT, '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID'], check=False)
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def cron_digest():
    body = CRON.read_bytes()
    if hashlib.sha256(body).hexdigest() != APPROVED_CRON_SHA256:
        raise RuntimeError('Mirror cron differs from the inspected exclusive-lock command')
    jobs = [line for line in body.decode().splitlines() if line.strip()
        and not line.lstrip().startswith('#') and 'sync-outbound.js' in line]
    if len(jobs) != 1 or not all(value in jobs[0] for value in (
            'root ', 'flock', '/tmp/okki-outbound.lock', '/root/.openclaw/workspace/okki-sync')):
        raise RuntimeError('Mirror cron differs from the inspected single locked job')
    return hashlib.sha256(body).hexdigest()


def manual_mirror_running():
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if args and Path(os.fsdecode(args[0])).name == 'node' and any(
                Path(os.fsdecode(arg)).name in {'sync-outbound.js', 'resync-outbound-by-order.js'} for arg in args[1:]):
            return True
    return False


def private_record(record):
    temporary = RECORD.with_suffix('.next')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, RECORD)


def execute(request):
    import fcntl
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    if DIRECTORY.is_symlink() or DIRECTORY.stat().st_uid != 0:
        raise RuntimeError('Mirror fence directory is not protected root state')
    os.chmod(DIRECTORY, 0o700)
    with (DIRECTORY / 'management.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return execute_locked(request)


def verify_holder(state, record):
    if state.get('ActiveState') in {'active', 'activating', 'deactivating'}:
        args = Path('/proc/' + state['MainPID'] + '/cmdline').read_bytes().split(b'\0')
        if args[:3] != [b'/usr/bin/python3', str(SCRIPT).encode(), record['token'].encode()]:
            raise RuntimeError('Active mirror fence process is not owned by this token')
        if SCRIPT.is_symlink() or hashlib.sha256(SCRIPT.read_bytes()).hexdigest() != hashlib.sha256(HOLDER.encode()).hexdigest():
            raise RuntimeError('Active mirror fence helper changed')


def execute_locked(request):
    action = request['action']
    if action not in {'check', 'freeze', 'thaw', 'verify-frozen'}:
        raise ValueError('Unsupported mirror maintenance action')
    digest = cron_digest()
    state = unit_state()
    existing = json.loads(RECORD.read_text()) if RECORD.exists() else None
    if action == 'check':
        if (existing and existing.get('status') != 'restored') or state.get('ActiveState') not in {'inactive', None}:
            raise RuntimeError('Another mirror maintenance fence requires recovery')
        return {'cron_sha256': digest, 'status': 'ready'}
    token = request['token']
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Invalid maintenance identity')
    if digest != request['cron_sha256']:
        raise RuntimeError('Mirror cron changed since maintenance preflight')
    if action == 'freeze':
        if (existing and existing.get('status') != 'restored') or state.get('ActiveState') not in {'inactive', None}:
            raise RuntimeError('Mirror fence is already owned')
        DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        if DIRECTORY.is_symlink() or DIRECTORY.stat().st_uid != 0:
            raise RuntimeError('Mirror fence directory is not protected root state')
        os.chmod(DIRECTORY, 0o700)
        expected = hashlib.sha256(HOLDER.encode()).hexdigest()
        if SCRIPT.exists() and (SCRIPT.is_symlink() or hashlib.sha256(SCRIPT.read_bytes()).hexdigest() != expected):
            raise RuntimeError('Mirror fence helper drift')
        if not SCRIPT.exists():
            fd = os.open(SCRIPT, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as stream: stream.write(HOLDER)
        record = {'token': token, 'cron_sha256': digest, 'status': 'starting'}
        private_record(record)
        command(['systemd-run', '--unit=' + UNIT, '--collect', '--property=Type=notify',
            '--property=NotifyAccess=all', '--property=TimeoutStartSec=130', '--property=KillMode=control-group',
            '/usr/bin/python3', str(SCRIPT), token])
        if unit_state().get('ActiveState') != 'active':
            raise RuntimeError('Mirror fence did not hold the drained cron lock')
        record['status'] = 'frozen'; private_record(record)
        return record
    if not existing or existing['token'] != token or existing['cron_sha256'] != digest:
        raise RuntimeError('Mirror fence identity does not match its owner')
    verify_holder(state, existing)
    if action == 'verify-frozen':
        if existing['status'] != 'frozen' or state.get('ActiveState') != 'active':
            raise RuntimeError('Mirror cron is not fenced')
        if manual_mirror_running():
            raise RuntimeError('An uncooperative manual mirror process is running')
        return existing
    if state.get('ActiveState') in {'active', 'activating', 'deactivating', 'failed'}:
        command(['systemctl', 'stop', UNIT])
    if unit_state().get('ActiveState') not in {'inactive', None}:
        raise RuntimeError('Mirror fence did not release')
    existing['status'] = 'restored'; private_record(existing)
    return existing


if __name__ == '__main__':
    try:
        print(json.dumps(execute(json.load(__import__('sys').stdin))))
    except Exception as error:
        raise RuntimeError('Mirror maintenance failed: ' + type(error).__name__) from None
