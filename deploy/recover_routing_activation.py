"""Resume the inspected 2026-11-13 routing failure, without DDL or app restart."""
import hashlib
import json
from pathlib import Path
import shlex
import shutil

REVISION = 'c090e6d2c8ac1075687fc1610e641e04ce89dd90'
RELEASE_ID = '2214cf999d394ecf85506c62aad1be20'
SCHEMA = '262_invoice_customer_sync_log'
JOURNAL_SHA = '1b36b3f7bb0374a4e0359afa24ab1903cc1c4d4f0b25ec86628ff9363c0e6d8e'
MIGRATION_SHA = '522b03a070b3f0b88971dba78ba9ab65e1fc1e6855f61c67e362545377f3f48b'


def validate(plan, raw, migration_raw):
    if (plan != {'revision': REVISION, 'release_id': RELEASE_ID,
                 'journal_sha256': JOURNAL_SHA, 'migration_sha256': MIGRATION_SHA}
            or hashlib.sha256(raw).hexdigest() != JOURNAL_SHA
            or hashlib.sha256(migration_raw).hexdigest() != MIGRATION_SHA):
        raise ValueError('Recovery differs from the inspected release checkpoint')
    journal, migration = json.loads(raw), json.loads(migration_raw)
    if (journal['status'] != 'failed' or journal['revision'] != REVISION
            or journal['release_id'] != RELEASE_ID or journal['scope'] != 'office-and-cloud'
            or journal['completed'] != ['office', 'beijing-backend', 'colorwork-routing:cloud']
            or journal.get('recovery') is not None or migration['status'] != 'upgraded'
            or migration['schema'] != SCHEMA or journal['outbound']['status'] != 'installed_paused'):
        raise RuntimeError('Unexpected recovery phase')
    return journal, migration


def cached_outputs(p, static, live):
    outputs = {}
    for name in ('frontend', 'frontend-pm', 'frontend-portal'):
        record = p.marker('build-' + name)
        outputs[name] = p.STATE / 'builds' / (name + '-' + record['digest'])
        if static.manifest(outputs[name]) != record['files']:
            raise RuntimeError('Original static build changed')
    outputs['customer-media'] = outputs['frontend'] / 'customer-media'
    for name, folder in [('frontend', 'frontend/dist'), ('frontend-pm', 'frontend-pm/dist'),
                         ('pm-lan', 'frontend-pm/dist-lan')]:
        expected = p.marker('office-' + name)['files']
        if not expected:
            raise RuntimeError('Missing office static receipt')
        for relative, digest in expected.items():
            with (live / folder / relative).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise RuntimeError('Installed office static artifact changed')
    return outputs


def verify_mail_baseline(p, options, original):
    code = """import json,subprocess
from pathlib import Path
record=json.loads(Path('/opt/ark-mail-outreach/release-current.json').read_text())
state=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',
'ark-mail-outreach','-p','ActiveState','-p','UnitFileState','-p','MainPID'],text=True).splitlines())
print(json.dumps({'record':record,'state':state}))
"""
    value = json.loads(p.run(['ssh', *options, p.BJ,
        'sudo -n python3 -c ' + shlex.quote(code)], capture=True))
    if (value['record'] != original['baseline']
            or value['state'] != {'ActiveState': 'inactive', 'UnitFileState': 'disabled', 'MainPID': '0'}):
        raise RuntimeError('Mail worker differs from the original frozen baseline')
    return value


def execute(plan_path, prepare_only=False):
    import publish as p
    import schema_release as schema
    import office_release as office
    import static_sync as static
    import colorwork_routing
    import okki_outbound_release as outbound_release
    import mail_worker_release as mail_release
    from recover_outbound_activation import remote_state, expected_writer_state, runtime_context
    from static_prepare import prepare_all

    plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    live, state = p.ROOT, p.STATE
    source = state / 'sources' / REVISION
    controller = Path(__file__).parent
    receipt = state / ('routing-activation-recovery-' + RELEASE_ID + '.json')
    with p.deployment_lock():
        raw = (state / 'publish-current.json').read_bytes()
        migration_raw = (state / 'schema-writers.json').read_bytes()
        journal, migration = validate(plan, raw, migration_raw)
        if receipt.exists() or receipt.is_symlink():
            raise RuntimeError('Recovery already attempted; inspect its phase before retry')
        for folder in (live, source):
            if (p.run(['git', 'rev-parse', 'HEAD'], cwd=folder, capture=True) != REVISION
                    or p.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=folder, capture=True)):
                raise RuntimeError('Original application source changed')
        # Controller changes only recovery and endpoint diagnostics, never worker bytes/config.
        if (outbound_release.artifact(controller) != outbound_release.artifact(source / 'deploy')
                or (controller / 'platforms.json').read_bytes() != (source / 'deploy/platforms.json').read_bytes()
                or any((controller / 'nginx' / name).read_bytes() != (source / 'deploy/nginx' / name).read_bytes()
                       for name in ('colorwork-cloud.conf', 'colorwork-office.conf'))):
            raise RuntimeError('Recovery controller changed original release artifacts')
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        get = lambda key: p.run([nssm, 'get', 'CommissionSystem', key], capture=True)
        python = get('Application')
        if (Path(python).name.lower() != 'python.exe'
                or Path(get('AppDirectory')).resolve() != (live / 'backend').resolve()
                or get('AppParameters') != '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'):
            raise RuntimeError('Office runtime changed')
        prepared = runtime_context(python, nssm, migration)
        if schema.schema_check(source, python) != {'schema': SCHEMA, 'database': SCHEMA, 'pending': []}:
            raise RuntimeError('Actual schema changed')
        success = p.marker('office-success')
        if success.get('revision') != REVISION or success.get('schema') != SCHEMA:
            raise RuntimeError('Office success receipt changed')
        office.health(8001)
        remote = remote_state(p, static.SSH_OPTIONS, REVISION)
        original = journal['outbound']
        for key in ('revision', 'release_id', 'digest', 'database_fingerprint', 'mode', 'baseline'):
            if remote['outbound'].get(key) != original.get(key):
                raise RuntimeError('Original outbound identity changed')
        inventory = json.loads((source / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
        if [row['writer'] for row in migration['writers']] != inventory['migration_writers']:
            raise RuntimeError('Original writer inventory changed')
        for row in migration['writers']:
            if schema.writer_state(row['writer'], nssm) != expected_writer_state(row):
                raise RuntimeError('Writer differs from the inspected checkpoint')
        mail_baseline = verify_mail_baseline(p, static.SSH_OPTIONS, journal['mail_worker'])
        outputs = cached_outputs(p, static, live)
        if prepare_only:
            return {'status': 'prepared', 'revision': REVISION, 'release_id': RELEASE_ID, 'schema': SCHEMA}
        with schema.database_lock(source, python):
            validate(plan, (state / 'publish-current.json').read_bytes(),
                     (state / 'schema-writers.json').read_bytes())
            if schema.schema_check(source, python) != {'schema': SCHEMA, 'database': SCHEMA, 'pending': []}:
                raise RuntimeError('Schema changed before recovery')
            p.atomic_json(receipt, {'status': 'started', 'original': journal,
                                   'migration': migration, 'remote': remote, 'mail': mail_baseline})

        def phase(name):
            journal['recovery'] = {'status': 'running', 'phase': name, 'controller': str(controller)}
            p.atomic_json(state / 'publish-current.json', journal)

        try:
            phase('outbound-prepare')
            context = outbound_release.prepare(source, REVISION, RELEASE_ID)
            if any(context['receipt'][key] != original[key] for key in ('digest', 'mode', 'database_fingerprint')):
                raise RuntimeError('Outbound mode or target changed')
            context['_baseline'], context['_mode_floor'] = dict(original['baseline']), original['mode']
            phase('routing')
            for route in colorwork_routing.prepare(controller):
                result = colorwork_routing.activate(route, controller)
                completed = 'colorwork-routing:' + result['region']
                if completed not in journal['completed']:
                    journal['completed'].append(completed)
                p.atomic_json(state / 'publish-current.json', journal)
            with schema.database_lock(source, python):
                schema.schema_check(source, python)
                for script in ('scripts/seed_pm.py', 'scripts/import_pantone.py'):
                    phase('seed:' + script)
                    p.run([python, script], cwd=source / 'backend')
                    journal.setdefault('recovered_seeds', []).append(script)
                    p.atomic_json(state / 'publish-current.json', journal)
            phase('static-prepare')
            targets = prepare_all(inventory['static_targets'], outputs, state / 'transfers')
            for item in targets:
                phase('static:' + item['target'] + ':' + item['request']['root'])
                static.activate(item)
                journal['completed'].append(item['target'] + ':' + item['request']['root'])
                p.atomic_json(state / 'publish-current.json', journal)
            phase('outbound-activate')
            journal['outbound'] = outbound_release.phase(context, 'activate')
            p.atomic_json(state / 'publish-current.json', journal)
            phase('writers-resume')
            schema.resume_external(migration['stopped'], prepared, outbound=context, journal=journal)
            journal['outbound'] = outbound_release.verify_completion(context, journal)
            journal['completed'].append('singapore-outbound')
            phase('mail-worker')
            verify_mail_baseline(p, static.SSH_OPTIONS, journal['mail_worker'])
            mail = mail_release.prepare(source, REVISION, RELEASE_ID)
            for action in ('activate', 'verify'):
                journal['mail_worker'] = mail_release.invoke(mail, action)
                p.atomic_json(state / 'publish-current.json', journal)
            journal['completed'].append('beijing-mail-worker')
            phase('maintenance-resume')
            schema.resume_maintenance(prepared)
            schema.complete(prepared)
            summary = {'revision': REVISION, 'scope': 'office-and-cloud', 'schema': SCHEMA,
                       'transfer_bytes': sum(item['bytes'] for item in targets), 'deferred': [],
                       'outbound': journal['outbound'], 'mail_worker': journal['mail_worker'],
                       'static_retention': {'status': 'deferred'}, 'candidate_retention': {'status': 'deferred'},
                       'unmanaged_services': [dict(name=item['name'], status='not_deployed')
                           for item in inventory.get('external_services', [])
                           if item['name'] not in {'ark-okki-outbound-poller', 'ark-mail-outreach'}]}
            from candidate_retention import record_success
            record_success(state, REVISION, success['previous'])
            journal['status'] = 'succeeded'
            journal['recovery'].update(status='succeeded', phase='completed')
            p.atomic_json(state / 'publish-success.json', summary)
            p.atomic_json(state / 'publish-current.json', journal)
            p.atomic_json(state / 'maintenance-pending.json', {
                'revision': REVISION, 'release_id': RELEASE_ID, 'scope': 'office-and-cloud', 'status': 'pending',
                'static_retention': {'status': 'deferred'}, 'candidate_retention': {'status': 'deferred'}})
            p.atomic_json(receipt, {'status': 'succeeded', 'revision': REVISION, 'release_id': RELEASE_ID})
            return summary
        except Exception as error:
            journal['status'] = 'failed'
            journal['recovery'].update(status='failed', error_type=type(error).__name__)
            p.atomic_json(state / 'publish-current.json', journal)
            raise
