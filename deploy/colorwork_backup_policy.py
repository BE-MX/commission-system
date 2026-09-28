"""Install the bounded Colorwork backup policy without changing live code/data."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

TARGET = 'ubuntu@154.8.205.162'
MACHINE = 'fd410411419d40079742fdbc36dec028'
MACHINE_FILE = Path('/etc/machine-id')
STATE = Path('/home/ubuntu/commission-system/.deploy_state/colorwork')
SCRIPT = Path('/usr/local/lib/ark-colorwork-backup-retention.py')
UNIT = 'ark-colorwork-backup-retention'
UNITS = Path('/etc/systemd/system')
MANAGED = '# Managed by Ark colorwork backup retention\n'


def unit_files(installation_id):
    return {
        UNIT + '.service': MANAGED + f'''[Unit]
Description=Retain recent successful Colorwork recovery backups
After=ark-colorwork.service

[Service]
Type=oneshot
User=root
Environment=ARK_RETENTION_INSTALL_ID={installation_id}
ExecStart=/usr/bin/python3 {SCRIPT} --apply
TimeoutStartSec=300
UMask=0077
Nice=15
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths={STATE}/backups {STATE}/maintenance {STATE.parent}/backend.lock
''',
        UNIT + '.timer': MANAGED + f'''[Unit]
Description=Hourly bounded Colorwork backup retention

[Timer]
OnCalendar=hourly
RandomizedDelaySec=5min
Persistent=true
Unit={UNIT}.service

[Install]
WantedBy=timers.target
''',
    }


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, data, mode):
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise RuntimeError('Unsafe installation path')
    temporary = path.with_name(path.name + '.retention-new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def installation_lock():
    import fcntl
    if Path('/etc/machine-id').read_text().strip() != MACHINE or STATE.resolve() != STATE:
        raise RuntimeError('Unexpected installation host or path')
    folder = STATE / 'maintenance'
    if folder.is_symlink():
        raise RuntimeError('Unsafe installation lock directory')
    folder.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(folder / 'policy-install.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def install(request):
    if request.get('action') == 'install':
        with installation_lock():
            return install_locked(request)
    return install_locked(request)


def install_locked(request):
    if MACHINE_FILE.read_text().strip() != MACHINE:
        raise RuntimeError('Unexpected target machine')
    if request['action'] not in {'prepare', 'install'}:
        raise ValueError('Unknown backup policy action')
    source = base64.b64decode(request['source_b64'], validate=True)
    if digest(source) != request['sha256']:
        raise ValueError('Retention artifact digest mismatch')
    # Parse and run the exact candidate in read-only mode before installing it.
    scope = {'__name__': 'retention_candidate'}
    exec(compile(source, str(SCRIPT), 'exec'), scope)
    plan = scope['run_cleanup'](False)
    if plan['status'] != 'planned':
        raise RuntimeError('Deployment is busy; retry policy installation later')
    installation_id = uuid.uuid4().hex
    files = {SCRIPT: source, **{UNITS / name: text.encode() for name, text in unit_files(installation_id).items()}}
    for path in files:
        if path.is_symlink() or path.parent.resolve() != path.parent:
            raise RuntimeError('Unsafe installation target')
        if path.exists():
            if path == SCRIPT:
                if not path.read_text().startswith('"""Retain two recent Colorwork backups'):
                    raise RuntimeError('Refusing an unmanaged retention script')
            elif not path.read_text().startswith(MANAGED):
                raise RuntimeError('Refusing an unmanaged systemd unit')
    if request['action'] == 'prepare':
        return {'status': 'prepared', 'sha256': digest(source),
                'keep': plan['keep'], 'pending_delete': plan['delete']}
    maintenance = STATE / 'maintenance'
    if maintenance.is_symlink():
        raise RuntimeError('Unsafe maintenance directory')
    maintenance.mkdir(mode=0o700, exist_ok=True)
    staging = maintenance / 'unit-validation'
    staging.mkdir(mode=0o700, exist_ok=True)
    for name, text in unit_files(installation_id).items():
        write_atomic(staging / name, text.encode(), 0o600)
    subprocess.run(['systemd-analyze', 'verify', *map(str, staging.iterdir())], check=True,
                   capture_output=True, text=True)
    # Snapshot only these three managed installation files; no application restart.
    before = {path: (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None for path in files}
    timer = UNIT + '.timer'
    was_enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet', timer]).returncode == 0
    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', timer]).returncode == 0
    try:
        if (UNITS / timer).exists():
            subprocess.run(['systemctl', 'stop', timer], check=True)
        # A oneshot is "activating", not "active", while it runs. Stopping its
        # timer does not stop the in-flight job; never replace its executable.
        status = subprocess.run(['systemctl', 'show', UNIT + '.service',
                                 '-p', 'ActiveState', '-p', 'MainPID'],
                                check=True, capture_output=True, text=True).stdout
        fields = dict(line.split('=', 1) for line in status.splitlines() if '=' in line)
        if fields.get('ActiveState') not in {'inactive', 'failed'} or fields.get('MainPID') != '0':
            raise RuntimeError('Retention job is running; retry later')
        for path, data in files.items():
            write_atomic(path, data, 0o644)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        # Keep the timer stopped until the exact installed script has run once.
        subprocess.run(['systemctl', 'start', UNIT + '.service'], check=True)
        receipt = json.loads((maintenance / 'retention-outcome.json').read_text())
        # systemd can garbage-collect a completed first-run unit before its timer
        # is enabled. Bind the worker's outcome to this installation and artifact
        # rather than relying on the manager retaining its InvocationID property.
        if (receipt.get('installation_id') != installation_id
                or receipt.get('script_sha256') != request['sha256']
                or not receipt.get('invocation_id')
                or receipt.get('status') not in {'completed', 'skipped'}):
            raise RuntimeError('No verified outcome for the installed policy run')
        subprocess.run(['systemctl', 'enable', '--now', timer], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', timer], check=True)
        subprocess.run(['systemctl', 'is-enabled', '--quiet', timer], check=True)
        if digest(SCRIPT.read_bytes()) != request['sha256']:
            raise RuntimeError('Installed artifact mismatch')
    except Exception:
        subprocess.run(['systemctl', 'disable', '--now', timer], check=False)
        for path, old in before.items():
            if old is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, *old)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        if was_enabled:
            subprocess.run(['systemctl', 'enable', timer], check=True)
        if was_active:
            subprocess.run(['systemctl', 'start', timer], check=True)
        raise
    finally:
        for name in unit_files(installation_id):
            (staging / name).unlink(missing_ok=True)
        staging.rmdir()
    return {'status': 'installed', 'sha256': digest(source), 'timer': timer,
            'schedule': 'hourly with up to five minutes jitter',
            'last_run': receipt['status'], 'retained': receipt.get('keep', []),
            'deleted': receipt.get('deleted', []), 'reason': receipt.get('reason'),
            'installation_id': installation_id, 'invocation_id': receipt['invocation_id']}


def execute(prepare_only=False):
    from static_sync import remote_python
    here = Path(__file__).resolve().parent
    source = (here / 'colorwork_backup_retention.py').read_bytes()
    result = remote_python(TARGET, Path(__file__), {
        'action': 'prepare' if prepare_only else 'install',
        'source_b64': base64.b64encode(source).decode(), 'sha256': digest(source),
    }, sudo=True)
    if result.returncode:
        raise RuntimeError('Backup policy operation failed: ' + result.stderr[-2500:])
    receipt = json.loads(result.stdout)
    folder = here.parent / '.deploy_state/colorwork-backup-retention'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ('prepared.json' if prepare_only else 'installed.json')).write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    print(json.dumps(install(json.load(sys.stdin))))
