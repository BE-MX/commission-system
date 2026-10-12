"""Resume only the inspected 2026-10-12 post-DDL office readiness interruption."""
import json
from pathlib import Path
import shlex
import shutil
import time

REVISION = 'c797c45e6198d8a5de761342076d757ed5efb13d'
PREVIOUS = '9e16a4e10e6a06a3a94bccc88ba6c30d59ffb389'
SCHEMA = '186_portal_announcement_merge'
RELEASE_ID = 'b68389384a5e4e8b8f69bf4223f0ee8e'
PENDING = ['184_domestic_request_withdraw', '185_announcement_push_option', SCHEMA]


def inspect_beijing(run, options, host):
    code = """import json,subprocess
from pathlib import Path
root=Path('/home/ubuntu/commission-system')
source=root/'.deploy_state/checkouts/REVISION'
def git(folder,*args):return subprocess.check_output(['git',*args],cwd=folder,text=True).strip()
record=json.loads((root/'.deploy_state/backend-prepared-REVISION.json').read_text())
print(json.dumps({'current':git(root,'rev-parse','HEAD'),'dirty':git(root,'status','--porcelain','--untracked-files=no'),
'source_revision':git(source,'rev-parse','HEAD'),'source_dirty':git(source,'status','--porcelain','--untracked-files=no'),
'revision':record['revision'],'previous':record['previous'],'schema':record['schema']}))
""".replace('REVISION', REVISION)
    data = json.loads(run(['ssh', *options, host, 'python3 -c ' + shlex.quote(code)], capture=True))
    if data != {'current': PREVIOUS, 'dirty': '', 'source_revision': REVISION, 'source_dirty': '',
                'revision': REVISION, 'previous': PREVIOUS, 'schema': SCHEMA}:
        raise RuntimeError('Beijing prepared source or frozen baseline drift')
    return data


def validate(journal, migration, current, inventory):
    if (journal.get('revision') != REVISION or journal.get('release_id') != RELEASE_ID
            or journal.get('status') != 'failed' or journal.get('completed') != []
            or current != REVISION or migration.get('status') != 'upgraded'
            or migration.get('schema') != SCHEMA or migration.get('pending') != PENDING
            or [row.get('writer') for row in migration.get('writers', [])] != inventory['migration_writers']
            or any(row.get('before') not in {'running', 'stopped'} for row in migration.get('writers', []))):
        raise RuntimeError('Office recovery does not match the inspected failed release')
    outbound = journal.get('outbound', {})
    if (outbound.get('status') != 'installed_paused' or outbound.get('revision') != REVISION
            or outbound.get('release_id') != RELEASE_ID):
        raise RuntimeError('Original outbound installation receipt missing')


def wait_ready(health, state, *, timeout=300, monotonic=time.monotonic, sleep=time.sleep):
    deadline = monotonic() + timeout
    while True:
        try:
            health()
            if state() != 'SERVICE_RUNNING':
                raise RuntimeError('Office service is not running')
            return
        except Exception as error:
            if monotonic() >= deadline:
                raise RuntimeError('Office startup did not become healthy within the recovery deadline') from error
            print('Office recovery readiness:', type(error).__name__, flush=True)
            sleep(2)


def execute(plan_path, prepare_only=False):
    import publish as p
    request = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    if request != {'revision': REVISION, 'release_id': RELEASE_ID}:
        raise ValueError('Recovery requires the original reviewed revision and release ID')
    live, state = p.ROOT, p.STATE
    source = live / '.deploy_state/sources' / REVISION
    with p.deployment_lock():
        journal = p.marker('publish-current')
        migration = p.marker('schema-writers')
        inventory = json.loads((source / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
        validate(journal, migration, p.run(['git', 'rev-parse', 'HEAD'], cwd=live, capture=True), inventory)
        if (p.run(['git', 'rev-parse', 'HEAD'], cwd=source, capture=True) != REVISION
                or p.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=live, capture=True)
                or p.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source, capture=True)):
            raise RuntimeError('Recovery source or installed code drift')
        p.ROOT = source
        import schema_release as schema
        import office_release as office
        import cloud_backend
        import okki_outbound_release as outbound_release
        import mail_worker_release
        import colorwork_routing
        import static_sync
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        get = lambda key: p.run([nssm, 'get', 'CommissionSystem', key], capture=True)
        python = get('Application')
        if (Path(get('AppDirectory')).resolve() != (live / 'backend').resolve()
                or Path(python).name.lower() != 'python.exe'
                or get('AppParameters') != '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'):
            raise RuntimeError('Unexpected installed office command')
        prepared = {'python': python, 'nssm': nssm, 'schema': SCHEMA, 'schema_changed': True}
        if schema.schema_check(source, python)['schema'] != SCHEMA:
            raise RuntimeError('Actual schema differs from the completed migration')
        for row in migration['writers']:
            if schema.writer_state(row['writer'], nssm) != 'stopped':
                raise RuntimeError('Frozen writer is running before recovery')
        inspect_beijing(p.run, static_sync.SSH_OPTIONS, p.BJ)
        outbound = outbound_release.prepare(source, REVISION, RELEASE_ID)
        original = journal['outbound']
        outbound_release.validate_receipt(original, 'install', outbound['files'], coordinated=True,
            revision=REVISION, release_id=RELEASE_ID, database_fingerprint=outbound['receipt']['database_fingerprint'],
            mode=original['mode'], baseline=original['baseline'])
        outbound['_baseline'], outbound['_mode_floor'] = dict(original['baseline']), original['mode']
        if prepare_only:
            return {'status': 'prepared', 'revision': REVISION, 'schema': SCHEMA}
        backup = state / ('office-activation-original-' + REVISION + '.json')
        if backup.exists():
            raise RuntimeError('Recovery was already attempted; inspect phase before any retry')
        p.atomic_json(backup, {'publish': journal, 'migration': migration})
        journal['recovery'] = {'status': 'running', 'phase': 'office', 'revision': REVISION}
        p.atomic_json(state / 'publish-current.json', journal)
        def phase(name):
            journal['recovery']['phase'] = name
            p.atomic_json(state / 'publish-current.json', journal)
        # This is the verified new installation, never an old-code restart.
        with schema.database_lock(source, python):
            if schema.schema_check(source, python)['schema'] != SCHEMA:
                raise RuntimeError('Schema changed before office restart')
            for row in migration['writers']:
                if schema.writer_state(row['writer'], nssm) != 'stopped':
                    raise RuntimeError('Writer changed before office restart')
            try:
                p.run([nssm, 'start', 'CommissionSystem'])
                wait_ready(lambda: office.health(8001),
                    lambda: p.run([nssm, 'status', 'CommissionSystem'], capture=True))
            except Exception:
                try:
                    p.run([nssm, 'stop', 'CommissionSystem'])
                    if p.run([nssm, 'status', 'CommissionSystem'], capture=True) != 'SERVICE_STOPPED':
                        raise RuntimeError('Office did not confirm stopped')
                except Exception as pause_error:
                    journal['recovery'].update(status='unconfirmed', phase='office-stop-unconfirmed')
                    p.atomic_json(state / 'publish-current.json', journal)
                    raise RuntimeError('Office startup failed and pause could not be confirmed') from pause_error
                journal['recovery'].update(status='failed', phase='office-stopped')
                p.atomic_json(state / 'publish-current.json', journal)
                raise
        phase('office-connector')
        if next(row['before'] for row in migration['writers'] if row['writer']['service'] == 'WhatsAppConnector') == 'running':
            p.run([nssm, 'start', 'WhatsAppConnector'])
            if p.run([nssm, 'status', 'WhatsAppConnector'], capture=True) != 'SERVICE_RUNNING':
                raise RuntimeError('Original connector did not restart')
        phase('office-static-verification')
        outputs = p.build_frontends(include_portal=True)
        office_outputs = {'frontend': outputs['frontend'], 'frontend-pm': outputs['frontend-pm'], 'pm-lan': p.build_lan()}
        for name, dist in office_outputs.items():
            folder, leaf = ('frontend-pm', 'dist-lan') if name == 'pm-lan' else (name, 'dist')
            expected, actual = static_sync.manifest(dist), static_sync.manifest(live / folder / leaf)
            if any(actual.get(key) != value for key, value in expected.items()):
                raise RuntimeError('Installed office frontend differs from prepared candidate')
            p.atomic_json(state / ('office-' + name + '.json'), {'files': expected})
        p.atomic_json(state / 'office-success.json', {'revision': REVISION, 'previous': PREVIOUS, 'schema': SCHEMA,
            'recovered_from': 'office-readiness-budget'})
        journal['completed'].append('office')
        phase('beijing')
        cloud_backend.activate(REVISION)
        journal['completed'].append('beijing-backend')
        p.atomic_json(state / 'publish-current.json', journal)
        phase('routing')
        for route in colorwork_routing.prepare(source / 'deploy'):
            result = colorwork_routing.activate(route, source / 'deploy')
            journal['completed'].append('colorwork-routing:' + result['region'])
            p.atomic_json(state / 'publish-current.json', journal)
        phase('seed-static')
        with schema.database_lock(source, python):
            schema.schema_check(source, python)
            p.run([python, 'scripts/seed_pm.py'], cwd=source / 'backend')
            p.run([python, 'scripts/import_pantone.py'], cwd=source / 'backend')
        outputs['customer-media'] = outputs['frontend'] / 'customer-media'
        transferred = 0
        for target in inventory['static_targets']:
            phase('static:' + target['domain'])
            item = static_sync.prepare(outputs[target['component']], target['host'], target['root'],
                state / 'transfers', target['domain'])
            static_sync.activate(item)
            transferred += item['bytes']
            journal['completed'].append(item['target'] + ':' + item['request']['root'])
            p.atomic_json(state / 'publish-current.json', journal)
        phase('outbound-activate')
        journal['outbound'] = outbound_release.phase(outbound, 'activate')
        p.atomic_json(state / 'publish-current.json', journal)
        journal['outbound'] = outbound_release.verify_completion(outbound, journal)
        p.atomic_json(state / 'publish-current.json', journal)
        phase('writers-resume')
        schema.resume_external(migration['stopped'], prepared, outbound=outbound, journal=journal)
        journal['completed'].append('singapore-outbound')
        p.atomic_json(state / 'publish-current.json', journal)
        phase('mail-worker')
        mail = mail_worker_release.prepare(source, REVISION, RELEASE_ID)
        journal['mail_worker'] = mail_worker_release.invoke(mail, 'activate')
        p.atomic_json(state / 'publish-current.json', journal)
        journal['mail_worker'] = mail_worker_release.invoke(mail, 'verify')
        p.atomic_json(state / 'publish-current.json', journal)
        journal['completed'].append('beijing-mail-worker')
        phase('maintenance-resume')
        schema.resume_maintenance(prepared)
        journal['outbound'] = outbound_release.verify_completion(outbound, journal)
        p.atomic_json(state / 'publish-current.json', journal)
        schema.complete(prepared)
        summary = {'revision': REVISION, 'schema': SCHEMA, 'scope': 'office-and-cloud', 'deferred': [],
            'transfer_bytes': transferred, 'outbound': journal['outbound'], 'mail_worker': journal['mail_worker']}
        journal['status'] = 'succeeded'
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
