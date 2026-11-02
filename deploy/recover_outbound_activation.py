"""Resume only explicitly reviewed post-static outbound activation checkpoints.

No DDL, application restart, static switch, provider mutation or new release ID.
"""
import hashlib
import json
from pathlib import Path
import shlex
import shutil

REVISION = 'd6e56d82e6eef2d76744069c22b3a76dcdb26f45'
RELEASE_ID = 'a173e5bbeaf34c54939f59d733ded0bc'
SCHEMA = '204_portal_delivery_profile'
REVIEWED_CHECKPOINTS = {
    (REVISION, RELEASE_ID): {
        'schema': SCHEMA, 'database': '202_presale_order_revision',
        'pending': ['203_perf_goals', SCHEMA]},
    ('b817650a69a6865886c9f4d7a0c61bc1ec9ec807', '6d6683095e704b818c90d3db43b1c57d'): {
        'schema': '247_sales_return_freight', 'database': '246_domestic_followup',
        'pending': ['247_sales_return_freight']},
}
# One inspected failure before timer activation; immutable bytes are archived before retry.
REVIEWED_RETRIES = {
    ('b7db2d80e052a0676f6dc5eb2b2b1ab2c7dca4026004692ea0fd248b530c197f',
     '74b17012960bbfae6d1343a5f37b89acced0af2fd36da83443efc4dcbe66c206'),
}
COMPLETED = [
    'office', 'beijing-backend', 'colorwork-routing:cloud', 'colorwork-routing:office',
    'root@119.28.107.92:/var/www/ark/dist',
    'ubuntu@154.8.205.162:/var/www/ark-dist',
    'root@119.28.107.92:/var/www/pm/dist',
    'ubuntu@154.8.205.162:/var/www/ark-static/customer-media',
    'ubuntu@154.8.205.162:/var/www/ark-static/customer-orders',
]


def validate(plan, raw, migration):
    checkpoint = REVIEWED_CHECKPOINTS.get((plan.get('revision'), plan.get('release_id')))
    if (set(plan) != {'revision', 'release_id', 'journal_sha256'} or checkpoint is None
            or plan['journal_sha256'] != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Recovery does not match the reviewed original release')
    journal = json.loads(raw)
    outbound = journal.get('outbound', {})
    if (journal.get('status') != 'failed' or journal.get('revision') != plan['revision']
            or journal.get('release_id') != plan['release_id'] or journal.get('scope') != 'office-and-cloud'
            or journal.get('completed') != COMPLETED
            or migration.get('status') != 'upgraded' or migration.get('schema') != checkpoint['schema']
            or migration.get('database') != checkpoint['database']
            or migration.get('pending') != checkpoint['pending']
            or outbound.get('status') != 'installed_paused'
            or outbound.get('revision') != plan['revision'] or outbound.get('release_id') != plan['release_id']
            or outbound.get('release_confirmed') is not False
            or outbound.get('target_schedule') != {'active': False, 'enabled': False}):
        raise RuntimeError('Release is not at the inspected paused activation checkpoint')
    return journal


def inspect_previous_attempt(raw, receipt_raw, journal, migration):
    if receipt_raw is None:
        if journal.get('recovery') is not None:
            raise RuntimeError('Recovery receipt is missing')
        return None
    pair = (hashlib.sha256(raw).hexdigest(), hashlib.sha256(receipt_raw).hexdigest())
    if pair not in REVIEWED_RETRIES:
        raise RuntimeError('Recovery already attempted; inspected journal and receipt are required')
    prior = json.loads(receipt_raw)
    recovery = journal.get('recovery', {})
    without_recovery = {key: value for key, value in journal.items() if key != 'recovery'}
    if (prior.get('status') != 'started' or prior.get('original') != without_recovery
            or prior.get('migration') != migration
            or recovery.get('phase') != 'outbound-activate' or recovery.get('status') != 'running'
            or prior.get('remote', {}).get('outbound', {}).get('status') != 'installed_paused'):
        raise RuntimeError('Previous recovery progressed beyond the inspected activation failure')
    return pair[1]


def archive_previous_attempt(receipt, raw, receipt_raw, digest):
    for name, body in [('receipt', receipt_raw), ('journal', raw)]:
        path = receipt.with_name(receipt.stem + '-' + digest + '-' + name + '.json')
        if path.is_symlink():
            raise RuntimeError('Recovery archive symlink rejected')
        if path.exists():
            if path.read_bytes() != body:
                raise RuntimeError('Recovery archive differs from inspected evidence')
        else:
            with path.open('xb') as stream:
                stream.write(body)


def expected_writer_state(row, *, reviewed_retry=False):
    service = row['writer']['service']
    if service in {'CommissionSystem', 'WhatsAppConnector', 'ark-backend'}:
        return 'running'
    # The inspected retry is after completed DDL and application activation. The
    # original running tracking worker may already have resumed independently;
    # preserve its baseline, never stop it just to recreate the earlier snapshot.
    if (reviewed_retry and row['writer']['kind'] == 'pm2'
            and service == 'shipment-tracking-mcp' and row.get('before') == 'running'):
        return 'running'
    return 'stopped'


def remote_state(p, options, revision=REVISION):
    code = """import json,subprocess,urllib.request
from pathlib import Path
r=Path('/home/ubuntu/commission-system')
with urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=8) as response:h=json.load(response)
def state(unit):
 return dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show',unit,
 '-p','ActiveState','-p','UnitFileState','-p','MainPID'],text=True).splitlines())
print(json.dumps({'revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),
'dirty':subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=r,text=True).strip(),
'health':h,'timer':state('ark-okki-outbound-poller.timer'),
'service':state('ark-okki-outbound-poller.service'),
'outbound':json.loads(Path('/root/.openclaw/workspace/okki-sync/.deploy-state/ark-outbound/release-current.json').read_text())}))
"""
    value = json.loads(p.run(['ssh', *options, p.BJ,
        'sudo -n python3 -c ' + shlex.quote(code)], capture=True))
    if (value['revision'] != revision or value['dirty'] or value['health'].get('status') != 'ok'
            or value['health'].get('database') != 'connected'
            or value['timer']['ActiveState'] != 'inactive' or value['timer']['UnitFileState'] != 'disabled'
            or value['service']['ActiveState'] not in {'inactive', 'failed'} or value['service']['MainPID'] != '0'
            or value['outbound'].get('status') != 'installed_paused'):
        raise RuntimeError('Actual applications or paused outbound state changed')
    return value


def verify_static(p, inventory, static, live):
    outputs = {}
    for name in ('frontend', 'frontend-pm', 'frontend-portal'):
        record = p.marker('build-' + name)
        outputs[name] = p.STATE / 'builds' / (name + '-' + record['digest'])
        if static.manifest(outputs[name]) != record['files']:
            raise RuntimeError('Original cached static artifact changed')
    outputs['customer-media'] = outputs['frontend'] / 'customer-media'
    for target in inventory['static_targets']:
        value = static.remote(target['host'], {'action': 'plan', 'root': target['root'],
            'host': target['domain'], 'manifest': static.manifest(outputs[target['component']])})
        if value['missing'] or not value['initialized'] or value['active_artifact'] != value['artifact']:
            raise RuntimeError('Published static checkpoint changed')
    for name, folder in [('frontend', 'frontend/dist'), ('frontend-pm', 'frontend-pm/dist'), ('pm-lan', 'frontend-pm/dist-lan')]:
        for relative, digest in p.marker('office-' + name)['files'].items():
            with (live / folder / relative).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise RuntimeError('Office static checkpoint changed')


def runtime_context(python, nssm, migration):
    return {'python': python, 'nssm': nssm, 'schema': migration['schema'], 'schema_changed': True,
        'pending': list(migration['pending'])}


def execute(plan_path, prepare_only=False):
    import publish as p
    import schema_release as schema
    import office_release as office
    import static_sync as static
    import okki_outbound_release as outbound_release
    import mail_worker_release as mail_release
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    live, state = p.ROOT, p.STATE
    with p.deployment_lock():
        raw = (state / 'publish-current.json').read_bytes()
        migration = p.marker('schema-writers')
        journal = validate(plan, raw, migration)
        revision, release_id = journal['revision'], journal['release_id']
        target_schema = migration['schema']
        source = state / 'sources' / revision
        receipt = state / ('outbound-activation-recovery-' + release_id + '.json')
        if receipt.is_symlink():
            raise RuntimeError('Recovery receipt symlink rejected')
        receipt_raw = receipt.read_bytes() if receipt.exists() else None
        previous_digest = inspect_previous_attempt(raw, receipt_raw, journal, migration)
        for folder in (live, source):
            if (p.run(['git', 'rev-parse', 'HEAD'], cwd=folder, capture=True) != revision
                    or p.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=folder, capture=True)):
                raise RuntimeError('Original application source changed')
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        python = p.run([nssm, 'get', 'CommissionSystem', 'Application'], capture=True)
        directory = p.run([nssm, 'get', 'CommissionSystem', 'AppDirectory'], capture=True)
        parameters = p.run([nssm, 'get', 'CommissionSystem', 'AppParameters'], capture=True)
        if (Path(python).name.lower() != 'python.exe' or Path(directory).resolve() != (live / 'backend').resolve()
                or parameters != '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'):
            raise RuntimeError('Original office runtime changed')
        if schema.schema_check(source, python) != {'schema': target_schema, 'database': target_schema, 'pending': []}:
            raise RuntimeError('Actual schema changed')
        success = p.marker('office-success')
        if success.get('revision') != revision or success.get('schema') != target_schema:
            raise RuntimeError('Office activation receipt changed')
        office.health(8001)
        remote = remote_state(p, static.SSH_OPTIONS, revision)
        original = journal['outbound']
        for key in ('revision', 'release_id', 'digest', 'database_fingerprint', 'mode', 'baseline'):
            if remote['outbound'].get(key) != original.get(key):
                raise RuntimeError('Original outbound identity changed')
        inventory = json.loads((source / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
        if [row['writer'] for row in migration['writers']] != inventory['migration_writers']:
            raise RuntimeError('Migration writer inventory changed')
        for row in migration['writers']:
            expected = expected_writer_state(row, reviewed_retry=previous_digest is not None)
            if schema.writer_state(row['writer'], nssm) != expected:
                raise RuntimeError('Actual writer differs from the paused checkpoint')
        if outbound_release.artifact(Path(__file__).parent) != outbound_release.artifact(source / 'deploy'):
            raise RuntimeError('Recovery controller changed an original outbound artifact')
        context = outbound_release.prepare(source, revision, release_id)
        if any(context['receipt'][key] != original[key] for key in ('digest', 'mode', 'database_fingerprint')):
            raise RuntimeError('Actual outbound target or mode changed')
        context['_baseline'], context['_mode_floor'] = dict(original['baseline']), original['mode']
        verify_static(p, inventory, static, live)
        if prepare_only:
            return {'status': 'prepared', 'revision': revision, 'release_id': release_id}
        if previous_digest:
            archive_previous_attempt(receipt, raw, receipt_raw, previous_digest)
        p.atomic_json(receipt, {'status': 'started', 'original': journal, 'migration': migration, 'remote': remote,
                                **({'previous_receipt_sha256': previous_digest} if previous_digest else {})})
        prepared = runtime_context(python, nssm, migration)
        def phase(name):
            journal['recovery'] = {'status': 'running', 'phase': name, 'controller': str(Path(__file__).parent)}
            p.atomic_json(state / 'publish-current.json', journal)
        phase('outbound-activate')
        journal['outbound'] = outbound_release.phase(context, 'activate')
        p.atomic_json(state / 'publish-current.json', journal)
        phase('writers-resume')
        schema.resume_external(migration['stopped'], prepared, outbound=context, journal=journal)
        journal['outbound'] = outbound_release.verify_completion(context, journal)
        journal['completed'].append('singapore-outbound')
        phase('mail-worker')
        mail = mail_release.prepare(source, revision, release_id)
        for action in ('activate', 'verify'):
            journal['mail_worker'] = mail_release.invoke(mail, action)
            p.atomic_json(state / 'publish-current.json', journal)
        journal['completed'].append('beijing-mail-worker')
        phase('maintenance-resume')
        schema.resume_maintenance(prepared)
        journal['outbound'] = outbound_release.verify_completion(context, journal)
        schema.complete(prepared)
        summary = {'revision': revision, 'scope': 'office-and-cloud', 'schema': target_schema,
            'transfer_bytes': 0, 'deferred': [], 'outbound': journal['outbound'],
            'mail_worker': journal['mail_worker'], 'static_retention': {'status': 'deferred'},
            'candidate_retention': {'status': 'deferred'}}
        journal['status'] = 'succeeded'
        journal['recovery'].update(status='succeeded', phase='completed')
        p.atomic_json(state / 'publish-success.json', summary)
        p.atomic_json(state / 'publish-current.json', journal)
        p.atomic_json(state / 'maintenance-pending.json', {'revision': revision, 'release_id': release_id,
            'scope': 'office-and-cloud', 'status': 'pending', 'static_retention': {'status': 'deferred'},
            'candidate_retention': {'status': 'deferred'}})
        p.atomic_json(receipt, {'status': 'succeeded', 'revision': revision, 'release_id': release_id})
        return summary
