"""Complete only the inspected schema-186 outbound verification interruption."""
import json
from pathlib import Path
import shlex
import shutil

from recover_office_activation import REVISION, RELEASE_ID, SCHEMA, PREVIOUS, PENDING

STATIC_CHECKPOINT = [
    'root@119.28.107.92:/var/www/ark/dist',
    'ubuntu@154.8.205.162:/var/www/ark-dist',
    'root@119.28.107.92:/var/www/pm/dist',
    'ubuntu@154.8.205.162:/var/www/ark-static/customer-media',
    'ubuntu@154.8.205.162:/var/www/ark-static/customer-orders',
]
COMPLETED = ['office', 'beijing-backend', 'colorwork-routing:cloud',
             'colorwork-routing:office', *STATIC_CHECKPOINT]


def validate(journal, migration, archived, inventory):
    original = archived.get('publish', {})
    if (journal.get('revision') != REVISION or journal.get('release_id') != RELEASE_ID
            or journal.get('status') != 'failed' or journal.get('completed') != COMPLETED
            or journal.get('recovery', {}).get('phase') != 'outbound-activate'
            or migration != archived.get('migration') or migration.get('status') != 'upgraded'
            or migration.get('schema') != SCHEMA or migration.get('database') != '183_portal_password_login'
            or migration.get('pending') != PENDING
            or original.get('revision') != REVISION or original.get('release_id') != RELEASE_ID
            or original.get('status') != 'failed' or original.get('completed') != []
            or [r.get('writer') for r in migration.get('writers', [])] != inventory['migration_writers']
            or [t['host'] + ':' + t['root'] for t in inventory['static_targets']] != STATIC_CHECKPOINT):
        raise RuntimeError('Completion does not match the original release checkpoint')
    receipt = journal.get('outbound', {})
    original_receipt = original.get('outbound', {})
    identity = ('revision', 'release_id', 'digest', 'database_fingerprint', 'mode', 'baseline')
    if (receipt.get('status') != 'enabled' or receipt.get('revision') != REVISION
            or receipt.get('release_id') != RELEASE_ID
            or original_receipt.get('status') != 'installed_paused'
            or any(receipt.get(key) != original_receipt.get(key) for key in identity)):
        raise RuntimeError('Original outbound activation receipt is missing')


def inspect_remote(p, options):
    code = """import json,subprocess,urllib.request
from pathlib import Path
from sqlalchemy import create_engine,text
from app.core.config import get_settings
root=Path('/home/ubuntu/commission-system')
def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
with urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=8) as response:health=json.load(response)
engine=create_engine(get_settings().commission_db_url)
with engine.connect() as connection:revision=connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
engine.dispose()
print(json.dumps({'revision':git('rev-parse','HEAD'),'dirty':git('status','--porcelain','--untracked-files=no'),
'schema':revision,'health':health}))
"""
    command = ('cd /home/ubuntu/commission-system/backend && '
               '/home/ubuntu/commission-system/backend/.venv/bin/python -c ' + shlex.quote(code))
    data = json.loads(p.run(['ssh', *options, p.BJ, command], capture=True))
    if (data.get('revision') != REVISION or data.get('dirty') or data.get('schema') != [SCHEMA]
            or data.get('health', {}).get('status') != 'ok'
            or data.get('health', {}).get('database') != 'connected'):
        raise RuntimeError('Beijing running version, schema or health differs from checkpoint')
    code = """import json,subprocess
from pathlib import Path
def state(unit):
 return dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','UnitFileState','-p','MainPID'],text=True).splitlines())
record=json.loads(Path('/root/.openclaw/workspace/okki-sync/.deploy-state/ark-outbound/release-current.json').read_text())
print(json.dumps({'record':record,'timer':state('ark-okki-outbound-poller.timer'),'service':state('ark-okki-outbound-poller.service')}))
"""
    return json.loads(p.run(['ssh', *options, p.BJ, 'sudo -n python3 -c ' + shlex.quote(code)], capture=True))


def validate_paused(remote, receipt):
    record, timer, service = remote['record'], remote['timer'], remote['service']
    keys = ('revision', 'release_id', 'digest', 'database_fingerprint', 'mode', 'baseline')
    if (record.get('status') != 'failed_paused' or record.get('release_confirmed') is not False
            or any(record.get(k) != receipt.get(k) for k in keys)
            or record.get('target_schedule') != {'active': False, 'enabled': False}
            or timer.get('ActiveState') != 'inactive' or timer.get('UnitFileState') != 'disabled'
            or service.get('ActiveState') not in {'inactive', 'failed'} or service.get('MainPID') != '0'):
        raise RuntimeError('Original outbound failure is not positively paused and drained')


def verify_static(p, state, live, inventory, static, artifact_id):
    outputs = {}
    for name in ('frontend', 'frontend-pm', 'frontend-portal'):
        record = p.marker('build-' + name)
        folder = state / 'builds' / (name + '-' + record['digest'])
        if static.manifest(folder) != record['files']:
            raise RuntimeError('Original cached build differs from its verified manifest')
        outputs[name] = folder
    outputs['customer-media'] = outputs['frontend'] / 'customer-media'
    for target in inventory['static_targets']:
        files = static.manifest(outputs[target['component']])
        result = static.remote(target['host'], {'action': 'plan', 'root': target['root'],
            'manifest': files, 'host': target['domain']})
        ident = artifact_id(files)
        if (result.get('missing') != [] or result.get('initialized') is not True
                or result.get('artifact') != ident or result.get('active_artifact') != ident):
            raise RuntimeError('Published static artifact differs from the completed checkpoint')
    lan = p.marker('build-pm-lan')
    office = {'frontend': outputs['frontend'], 'frontend-pm': outputs['frontend-pm'],
              'pm-lan': state / 'builds' / ('pm-lan-' + lan['digest'])}
    if static.manifest(office['pm-lan']) != lan['files']:
        raise RuntimeError('Original LAN build manifest differs')
    for name, folder in office.items():
        parent, leaf = ('frontend-pm', 'dist-lan') if name == 'pm-lan' else (name, 'dist')
        files, actual = static.manifest(folder), static.manifest(live / parent / leaf)
        if any(actual.get(k) != v for k, v in files.items()):
            raise RuntimeError('Office static files differ from the verified release')


def execute(plan_path, prepare_only=False):
    import publish as p
    request = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    if request != {'revision': REVISION, 'release_id': RELEASE_ID}:
        raise ValueError('Completion requires the original revision and release identity')
    live, state, controller = p.ROOT, p.STATE, Path(__file__).resolve().parent
    source = state / 'sources' / REVISION
    with p.deployment_lock():
        journal, migration = p.marker('publish-current'), p.marker('schema-writers')
        archived = json.loads((state / ('office-activation-original-' + REVISION + '.json')).read_text(encoding='utf-8'))
        inventory = json.loads((source / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
        validate(journal, migration, archived, inventory)
        for folder in (live, source):
            if (p.run(['git', 'rev-parse', 'HEAD'], cwd=folder, capture=True) != REVISION
                    or p.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=folder, capture=True)):
                raise RuntimeError('Application source differs from the original release')
        p.ROOT = source
        import schema_release as schema
        import office_release as office
        import static_sync as static
        import okki_outbound_release as outbound_release
        import mail_worker_release as mail_release
        from static_retention import artifact_id
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        python = p.run([nssm, 'get', 'CommissionSystem', 'Application'], capture=True)
        directory = p.run([nssm, 'get', 'CommissionSystem', 'AppDirectory'], capture=True)
        parameters = p.run([nssm, 'get', 'CommissionSystem', 'AppParameters'], capture=True)
        if (Path(python).name.lower() != 'python.exe' or Path(directory).resolve() != (live / 'backend').resolve()
                or parameters != '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'):
            raise RuntimeError('Office installed runtime differs from checkpoint')
        if schema.schema_check(source, python) != {'schema': SCHEMA, 'database': SCHEMA, 'pending': []}:
            raise RuntimeError('Current schema differs from completed migration')
        success = p.marker('office-success')
        if success.get('revision') != REVISION or success.get('schema') != SCHEMA:
            raise RuntimeError('Office success receipt differs from checkpoint')
        office.health(8001)
        for row in migration['writers']:
            expected = 'running' if row['writer']['service'] in {'CommissionSystem', 'WhatsAppConnector', 'ark-backend'} else 'stopped'
            if schema.writer_state(row['writer'], nssm) != expected:
                raise RuntimeError('Actual writer state differs from completion checkpoint')
        remote = inspect_remote(p, static.SSH_OPTIONS)
        validate_paused(remote, journal['outbound'])
        if outbound_release.artifact(controller) != outbound_release.artifact(source / 'deploy'):
            raise RuntimeError('Controller must preserve all five original outbound artifacts')
        context = outbound_release.prepare(controller.parent, REVISION, RELEASE_ID)
        original = journal['outbound']
        outbound_release.validate_receipt(original, 'activate', context['files'], coordinated=True,
            revision=REVISION, release_id=RELEASE_ID, database_fingerprint=context['receipt']['database_fingerprint'],
            mode=original['mode'], baseline=original['baseline'])
        context['_baseline'], context['_mode_floor'] = dict(original['baseline']), original['mode']
        verify_static(p, state, live, inventory, static, artifact_id)
        if prepare_only:
            return {'status': 'prepared', 'revision': REVISION, 'release_id': RELEASE_ID, 'schema': SCHEMA}
        backup = state / ('release-completion-original-' + REVISION + '.json')
        if backup.exists():
            raise RuntimeError('Completion was already attempted; inspect actual phase before retry')
        p.atomic_json(backup, {'publish': journal, 'migration': migration, 'outbound_remote': remote})
        prepared = {'python': python, 'nssm': nssm, 'schema': SCHEMA, 'schema_changed': True}
        def phase(name):
            journal['recovery'] = {'status': 'running', 'phase': name, 'revision': REVISION}
            p.atomic_json(state / 'publish-current.json', journal)
        for action in ('freeze', 'install', 'activate'):
            phase('completion-outbound-' + action)
            journal['outbound'] = outbound_release.phase(context, action)
            p.atomic_json(state / 'publish-current.json', journal)
        journal['outbound'] = outbound_release.verify_completion(context, journal)
        p.atomic_json(state / 'publish-current.json', journal)
        phase('completion-writers-resume')
        schema.resume_external(migration['stopped'], prepared, outbound=context, journal=journal)
        journal['completed'].append('singapore-outbound')
        phase('completion-mail')
        mail = mail_release.prepare(source, REVISION, RELEASE_ID)
        for action in ('activate', 'verify'):
            journal['mail_worker'] = mail_release.invoke(mail, action)
            p.atomic_json(state / 'publish-current.json', journal)
        journal['completed'].append('beijing-mail-worker')
        phase('completion-maintenance')
        schema.resume_maintenance(prepared)
        journal['outbound'] = outbound_release.verify_completion(context, journal)
        p.atomic_json(state / 'publish-current.json', journal)
        schema.complete(prepared)
        summary = {'revision': REVISION, 'schema': SCHEMA, 'scope': 'office-and-cloud', 'deferred': [],
            'transfer_bytes': 0, 'outbound': journal['outbound'], 'mail_worker': journal['mail_worker']}
        journal.update(status='succeeded')
        journal['recovery'].update(status='succeeded', phase='completed')
        p.atomic_json(state / 'publish-success.json', summary)
        p.atomic_json(state / 'publish-current.json', journal)
        from static_retention_release import run as retain_static
        try:
            summary['static_retention'] = retain_static(live, source, include_office=True)
        except Exception as error:
            journal['static_retention_error'] = type(error).__name__ + ': ' + str(error)
            p.atomic_json(state / 'publish-current.json', journal)
            raise
        p.atomic_json(state / 'publish-success.json', summary)
        return summary
