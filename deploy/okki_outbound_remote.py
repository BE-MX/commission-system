"""Checksummed deployment of the registered outbound worker with a paused install phase."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import queue
import threading
import shutil
import subprocess
import sys
import time

ROOT = Path('/root/.openclaw/workspace/okki-sync')
NODE = '/root/.nvm/versions/node/v22.22.1/bin/node'
UNITS = Path('/etc/systemd/system')
NAMES = {'okki_outbound_poller.js', 'okki_outbound_creator.mjs', 'okki_outbound_mode.mjs',
         'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer'}
TIMER = 'ark-okki-outbound-poller.timer'
SERVICE = 'ark-okki-outbound-poller.service'
MODULES = ('okki_outbound_poller.js', 'okki_outbound_creator.mjs', 'okki_outbound_mode.mjs')
IMPORT_PROBE = 'for (const url of process.argv.slice(1)) await import(url);'

MODE_CONTROL_PROBE = """import mysql from 'mysql2/promise';
const {serveDeploymentFence}=await import(process.argv[1]);
let c;
try {
  c=await mysql.createConnection({host:process.env.ARK_DB_HOST,port:Number(process.env.ARK_DB_PORT||3306),user:process.env.ARK_DB_USER,password:process.env.ARK_DB_PASSWORD,database:process.env.ARK_DB_NAME,connectTimeout:5000});
  await c.query('SET SESSION autocommit=1');
  await serveDeploymentFence(c,process.argv[2]);
  await c.end();c=null;
} catch {
  if(c)c.destroy();
  console.error('Outbound mode control is unavailable');process.exitCode=1;
}"""
PAUSED = {'active': False, 'enabled': False}
MODE = 'outbound-worker-v1'


def validate_observation(value):
    if (not isinstance(value, dict) or set(value) != {'mode', 'database_fingerprint'}
            or not isinstance(value.get('mode'), str) or value['mode'] not in {'legacy', MODE}
            or not isinstance(value.get('database_fingerprint'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', value['database_fingerprint'])):
        raise RuntimeError('Outbound mode observation cannot be confirmed')
    return value


def mode_command(stage, config, operation):
    return [NODE, '--env-file=' + str(config), '--input-type=module', '-e', MODE_CONTROL_PROBE,
            (stage / 'okki_outbound_mode.mjs').resolve().as_uri(), operation]


def parse_observation(line, phase):
    try:
        value = json.loads(line)
        if not isinstance(value, dict) or value.pop('phase', None) != phase:
            raise ValueError('Invalid control phase')
        return validate_observation(value)
    except (ValueError, TypeError, RuntimeError):
        raise RuntimeError('Outbound mode control cannot be confirmed') from None


def observe_mode(stage, config):
    try:
        return parse_observation(run(mode_command(stage, config, 'observe'), cwd=ROOT), 'observed')
    except Exception:
        raise RuntimeError('Outbound mode observation cannot be confirmed') from None


class ModeFence:
    """Keep a dedicated Node/MySQL connection live through the scheduling/journal window."""
    def __init__(self, stage, config):
        self.command = mode_command(stage, config, 'hold')
        self.child = None
        self.observation = None

    def _read(self, phase):
        result = queue.Queue(maxsize=1)
        def read():
            try: result.put(self.child.stdout.readline(8193))
            except Exception: result.put(None)
        threading.Thread(target=read, daemon=True).start()
        try:
            line = result.get(timeout=30)
            if not line or len(line) > 8192 or not line.endswith('\n'):
                raise ValueError('Incomplete mode control response')
            return parse_observation(line, phase)
        except (queue.Empty, ValueError, RuntimeError):
            raise RuntimeError('Outbound mode control cannot be confirmed') from None

    def _command(self, command, phase):
        try:
            self.child.stdin.write(command + '\n'); self.child.stdin.flush()
            value = self._read(phase)
            if value != self.observation:
                raise ValueError('Mode control changed')
            return value
        except Exception:
            raise RuntimeError('Outbound mode control cannot be confirmed') from None

    def _abort(self):
        if self.child is None: return
        if self.child.poll() is None:
            self.child.kill(); self.child.wait(timeout=10)
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            if stream and not stream.closed:
                try: stream.close()
                except OSError:
                    # The child is already terminated; a broken pipe flush is not lock evidence.
                    pass

    def __enter__(self):
        try:
            self.child = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            self.observation = self._read('ready')
            return self
        except BaseException:
            self._abort()
            raise

    def check(self):
        return self._command('check', 'checked')

    def __exit__(self, kind, *_):
        try:
            if kind is None:
                self._command('release', 'released')
                self.child.stdin.close()
                if self.child.wait(timeout=30) != 0:
                    raise RuntimeError('Outbound mode release cannot be confirmed')
        except Exception:
            raise RuntimeError('Outbound mode release cannot be confirmed') from None
        finally:
            self._abort()


def confirm_target(observation, previous, request):
    validate_observation(observation)
    for evidence in (previous, request):
        if not evidence: continue
        fingerprint = evidence.get('database_fingerprint')
        mode = evidence.get('mode')
        if (fingerprint is not None and fingerprint != observation['database_fingerprint']) or (
                mode == MODE and observation['mode'] != MODE):
            raise RuntimeError('Outbound mode or target database changed')


def remember_mode(observation, directory):
    """Independent sticky floor survives failed phases and a lost prepare response."""
    validate_observation(observation)
    path = directory / 'mode-floor.json'
    if path.is_symlink() or path.with_suffix('.next').is_symlink():
        raise RuntimeError('Outbound mode floor requires inspection')
    if path.exists():
        try:
            floor = validate_observation(json.loads(path.read_text()))
            if floor['mode'] != MODE: raise ValueError('Invalid permanent floor')
            confirm_target(observation, floor, {})
        except (OSError, ValueError, RuntimeError):
            raise RuntimeError('Outbound permanent mode or target database changed') from None
    elif observation['mode'] == MODE:
        save(path, dict(observation))


def confirm_baseline(previous, request):
    value = request.get('baseline')
    if (not isinstance(value, dict) or set(value) != {'active', 'enabled'}
            or any(type(item) is not bool for item in value.values()) or value != previous['baseline']):
        raise RuntimeError('Outbound baseline receipt does not match release')


def target_schedule(observation, baseline):
    return dict(PAUSED if observation['mode'] == MODE else baseline)


def pause_schedule():
    run(['systemctl', 'disable', TIMER]); run(['systemctl', 'stop', TIMER])
    if timer_state() != PAUSED:
        raise RuntimeError('Outbound pause cannot be confirmed')



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

def verify_modules(stage):
    # Load only candidate modules in staging, without protected runtime config.
    # Each production module guards main; import resolves dependencies but cannot
    # invoke its creator/poller entry point. Syntax checks alone miss dependencies.
    if any((stage / name).exists() for name in ('.env', '.ark-outbound.env')):
        raise RuntimeError('Outbound staging must not contain runtime configuration')
    for name in MODULES:
        run([NODE, '--check', str(stage / name)])
    run([NODE, '--no-warnings', '--input-type=module', '-e', IMPORT_PROBE,
         *(str((stage / name).resolve().as_uri()) for name in MODULES)], cwd=stage)


def execute_candidate(request):
    if set(request['files']) != NAMES or request['action'] not in {'prepare', 'freeze', 'install', 'activate', 'verify'}:
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
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get('status') not in
                {'freezing', 'frozen', 'installed_paused', 'target_verified', 'activated', 'completed', 'failed_paused'}
                or not isinstance(previous.get('baseline'), dict)
                or set(previous['baseline']) != {'active', 'enabled'}
                or any(type(value) is not bool for value in previous['baseline'].values())):
            raise RuntimeError('Outbound release journal requires inspection')
        validate_observation({key: previous.get(key) for key in ('mode', 'database_fingerprint')})
    coordinated = request.get('coordinated', False)
    revision = request.get('revision')
    release_id = request.get('release_id')
    if coordinated and not re.fullmatch(r'[0-9a-f]{40}', revision or ''):
        raise ValueError('Coordinated outbound release requires a pinned revision')
    if coordinated and not re.fullmatch(r'[0-9a-f]{32}', release_id or ''):
        raise ValueError('Coordinated outbound release requires a release ID')
    if coordinated and request['action'] != 'prepare':
        validate_observation({key: request.get(key) for key in ('mode', 'database_fingerprint')})
    same_release = (previous and coordinated and previous['digest'] == digest
                    and previous.get('revision') == revision and previous.get('release_id') == release_id)
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
    verify_modules(stage)
    run(['systemd-analyze', 'verify', str(stage / 'ark-okki-outbound-poller.service'), str(stage / 'ark-okki-outbound-poller.timer')])
    # Load only remote protected credentials. EXPLAIN validates UPDATE permission
    # without executing an UPDATE or touching task state.
    probe = """import mysql from 'mysql2/promise';
const c=await mysql.createConnection({host:process.env.ARK_DB_HOST,port:Number(process.env.ARK_DB_PORT||3306),user:process.env.ARK_DB_USER,password:process.env.ARK_DB_PASSWORD,database:process.env.ARK_DB_NAME});
try {await c.query('SELECT id,status FROM ark_okki_outbound_tasks LIMIT 1'); await c.query('SELECT id,invoice_no FROM ark_invoices LIMIT 1'); await c.query(\"EXPLAIN UPDATE ark_okki_outbound_tasks SET status='pending' WHERE id=-1\"); const s=process.env.ARK_BUSINESS_DB_NAME; if(!/^[A-Za-z0-9_]+$/.test(s||''))throw Error('Invalid schema'); await c.query('SELECT order_id FROM `'+s+'`.okki_outbound_record_items LIMIT 1');} finally {await c.end();}"""
    if request['action'] not in {'prepare', 'freeze'} or not request.get('allow_pending'):
        probe = probe.replace("try {", "try {await c.query('SELECT linked_sync_id,sync_status,status,remark FROM ark_invoices LIMIT 0'); await c.query('SELECT invoice_id,order_id,attempts,reason,last_error,processed_at,updated_at FROM ark_okki_outbound_tasks LIMIT 0'); ")
    run([NODE, '--env-file=' + str(config), '--input-type=module', '-e', probe], cwd=ROOT)
    observation = observe_mode(stage, config)
    confirm_target(observation, previous, request)
    remember_mode(observation, stage.parent)
    def receipt(status, **extra):
        return {'status': status, 'digest': digest, 'revision': revision, 'release_id': release_id,
                'target': str(ROOT), **observation, **extra}
    if request['action'] == 'prepare':
        return receipt('prepared')
    def verify_bytes():
        for name, body in bodies.items():
            dest = UNITS / name if name.endswith(('.service', '.timer')) else ROOT / name
            if dest.is_symlink() or not dest.is_file() or dest.read_bytes() != body:
                raise RuntimeError('Active outbound digest mismatch')

    if request['action'] == 'verify':
        verify_bytes()
        if (not previous or previous.get('status') not in {'activated', 'completed'}
                or previous['digest'] != digest or previous.get('revision') != revision
                or previous.get('release_id') != release_id or previous.get('release_confirmed') is not True):
            raise RuntimeError('Outbound activation receipt is missing')
        if coordinated: confirm_baseline(previous, request)
        with ModeFence(stage, config) as fence:
            observation = fence.observation
            confirm_target(observation, previous, request)
            remember_mode(observation, stage.parent)
            expected_schedule = target_schedule(observation, previous['baseline'])
            recorded_schedule = previous.get('target_schedule')
            if (not isinstance(recorded_schedule, dict) or set(recorded_schedule) != {'active', 'enabled'}
                    or any(type(value) is not bool for value in recorded_schedule.values())
                    or previous['mode'] != observation['mode'] or previous.get('target_schedule') != expected_schedule
                    or timer_state() != expected_schedule):
                raise RuntimeError('Outbound schedule differs from the mode target')
            fence.check()
            previous.update(status='target_verified', release_confirmed=False)
            save(journal, previous)
        previous.update(status='completed', release_confirmed=True)
        save(journal, previous)
        return receipt('verified', baseline=previous['baseline'], schedule=expected_schedule,
                       target_schedule=expected_schedule, release_confirmed=True)
    if request['action'] == 'freeze':
        if not coordinated:
            raise ValueError('Freeze requires a coordinated release')
        if not pending and not same_release:
            previous = {'digest': digest, 'revision': revision, 'release_id': release_id,
                        'status': 'freezing', 'baseline': timer_state(), **observation}
            save(journal, previous)
        run(['systemctl', 'disable', TIMER])
        drain()
        if timer_state() != {'active': False, 'enabled': False}:
            raise RuntimeError('Outbound scheduling was not persistently paused')
        if previous['status'] in {'installed_paused', 'activated', 'target_verified', 'completed'}:
            verify_bytes()
            previous['status'] = 'installed_paused'
            previous['target_schedule'] = {'active': False, 'enabled': False}
        else:
            previous['status'] = 'frozen'
        previous.update(observation, release_confirmed=False)
        save(journal, previous)
        return receipt('frozen', baseline=previous['baseline'], schedule=previous['baseline'], target_schedule=dict(PAUSED), release_confirmed=False)
    installing = request['action'] == 'install'
    if installing and not coordinated:
        raise ValueError('Paused install requires a coordinated release')
    if coordinated:
        required = {'frozen', 'installed_paused'} if installing else {'installed_paused'}
        if not pending or previous.get('status') not in required:
            stage_name = 'freeze' if installing else 'install'
            raise RuntimeError('Coordinated outbound release must ' + stage_name + ' before this phase')
        confirm_baseline(previous, request)
        baseline = previous['baseline']
    else:
        baseline = {'active': True, 'enabled': True}  # Explicit outbound-only enables scheduling.
    def install_bytes():
        drain()
        backup = stage / 'backup'; backup.mkdir(mode=0o700, exist_ok=True)
        changed = []
        for name, body in bodies.items():
            dest = UNITS / name if name.endswith(('.service', '.timer')) else ROOT / name
            if dest.is_symlink(): raise ValueError('Managed destination is a symlink')
            if dest.exists() and dest.read_bytes() == body: continue
            old = dest.read_bytes() if dest.exists() else None
            if old is not None and not (backup / name).exists(): (backup / name).write_bytes(old)
            changed.append((dest, old))
        for dest, old in changed:
            temporary = dest.with_name(dest.name + '.ark-next')
            temporary.write_bytes(bodies[dest.name]); os.replace(temporary, dest)
        run(['systemctl', 'daemon-reload']); verify_bytes()
        return len(changed)

    if installing:
        changed_count = install_bytes()
        pause_schedule()
        save(journal, {'digest': digest, 'revision': revision, 'release_id': release_id,
                       'status': 'installed_paused', 'baseline': baseline, 'target_schedule': dict(PAUSED),
                       'release_confirmed': False, **observation})
        return receipt('installed_paused', changed_files=changed_count, baseline=baseline,
                       schedule=dict(PAUSED), target_schedule=dict(PAUSED), release_confirmed=False)
    with ModeFence(stage, config) as fence:
        observation = fence.observation
        confirm_target(observation, previous, request)
        remember_mode(observation, stage.parent)
        if not coordinated and observation['mode'] != 'legacy':
            raise RuntimeError('New outbound mode prohibits standalone legacy activation')
        changed_count = install_bytes()
        schedule = target_schedule(observation, baseline)
        run(['systemctl', 'enable' if schedule['enabled'] else 'disable', TIMER])
        if schedule['active']: run(['systemctl', 'start', TIMER])
        if timer_state() != schedule:
            raise RuntimeError('Outbound timer differs from the mode target')
        fence.check()
        record = {'digest': digest, 'revision': revision, 'release_id': release_id, 'status': 'target_verified',
                  'baseline': baseline, 'target_schedule': schedule, 'release_confirmed': False, **observation}
        save(journal, record)
    record.update(status='activated' if coordinated else 'completed', release_confirmed=True)
    save(journal, record)
    return receipt('enabled', changed_files=changed_count, baseline=baseline, schedule=schedule,
                   target_schedule=schedule, release_confirmed=True)


def deployment_directory():
    directory=ROOT / '.deploy-state/ark-outbound'
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise ValueError('Unexpected outbound deployment root')
    paths=[ROOT / '.deploy-state',directory,directory / 'release.lock']
    for name in ('release-current.json','mode-floor.json','pause-current.json'):
        path=directory / name;paths.extend([path,path.with_suffix('.next')])
    if any(path.is_symlink() for path in paths) or directory.resolve() != ROOT.resolve() / '.deploy-state/ark-outbound':
        raise ValueError('Outbound deployment state symlink rejected')
    return directory


def pause_failed_activation():
    pause_schedule()
    journal = ROOT / '.deploy-state/ark-outbound/release-current.json'
    if journal.exists():
        record = json.loads(journal.read_text())
        if isinstance(record, dict) and record.get('status') in {'target_verified', 'activated', 'completed'}:
            record.update(status='failed_paused', release_confirmed=False, target_schedule=dict(PAUSED),
                          service_drain_confirmed=False)
            save(journal, record)


def execute(request):
    directory=deployment_directory()
    if isinstance(request, dict) and request.get('action') == 'pause':
        if set(request) != {'action'} or ROOT.is_symlink() or not ROOT.is_dir():
            raise ValueError('Invalid registered pause request')
        pause_failed_activation()
        receipt = {'status':'paused', 'target':str(ROOT), 'schedule':dict(PAUSED),
                   'target_schedule':dict(PAUSED), 'release_confirmed':False, 'service_drain_confirmed':False}
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        save(directory / 'pause-current.json',receipt)
        return receipt
    try:
        return execute_candidate(request)
    except Exception:
        if isinstance(request, dict) and request.get('action') in {'activate', 'verify'}:
            try:
                pause_failed_activation()
            except Exception:
                print('Outbound failure: pause or failed receipt requires inspection', file=sys.stderr, flush=True)
        # Never revert candidate bytes while an earlier submission may still be in flight.
        raise

if __name__ == '__main__':
    try:
        import fcntl
        lock_dir = deployment_directory()
        lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (lock_dir / 'release.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        # subprocess command/output may contain service configuration; no dumping.
        print('Outbound deployment failed: ' + (str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
