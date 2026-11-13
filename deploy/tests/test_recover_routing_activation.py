"""The post-DDL recovery accepts only one reviewed immutable checkpoint."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / 'recover_routing_activation.py'
spec = importlib.util.spec_from_file_location('routing_recovery', SOURCE)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.fixture
def checkpoint(monkeypatch):
    journal = {'status': 'failed', 'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
               'scope': 'office-and-cloud',
               'completed': ['office', 'beijing-backend', 'colorwork-routing:cloud'],
               'outbound': {'status': 'installed_paused'}}
    migration = {'status': 'upgraded', 'schema': recovery.SCHEMA}
    raw, migration_raw = json.dumps(journal).encode(), json.dumps(migration).encode()
    # Synthetic fixture has its own identity; production hashes remain fixed in source.
    monkeypatch.setattr(recovery, 'JOURNAL_SHA', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(recovery, 'MIGRATION_SHA', hashlib.sha256(migration_raw).hexdigest())
    plan = {'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
            'journal_sha256': recovery.JOURNAL_SHA, 'migration_sha256': recovery.MIGRATION_SHA}
    return plan, raw, migration_raw


def test_exact_checkpoint_is_read_only(checkpoint):
    plan, raw, migration_raw = checkpoint
    assert recovery.validate(plan, raw, migration_raw) == (json.loads(raw), json.loads(migration_raw))


@pytest.mark.parametrize('target', ['journal', 'migration', 'plan', 'revision', 'extra'])
def test_drift_in_any_bound_evidence_rejects_replay(checkpoint, target):
    plan, raw, migration_raw = checkpoint
    if target == 'journal':
        raw += b' '
    elif target == 'migration':
        migration_raw += b' '
    elif target == 'plan':
        plan['journal_sha256'] = '0' * 64
    elif target == 'revision':
        plan['revision'] = '0' * 40
    else:
        plan['force'] = True
    with pytest.raises(ValueError, match='inspected'):
        recovery.validate(plan, raw, migration_raw)


@pytest.mark.parametrize('field,value', [
    ('status', 'succeeded'), ('scope', 'cloud-only'), ('completed', ['office']),
    ('recovery', {'status': 'running', 'phase': 'seed'}),
    ('outbound', {'status': 'activated'}),
])
def test_even_reviewed_bytes_cannot_admit_a_different_phase(checkpoint, monkeypatch, field, value):
    plan, raw, migration_raw = checkpoint
    journal = json.loads(raw)
    journal[field] = value
    raw = json.dumps(journal).encode()
    monkeypatch.setattr(recovery, 'JOURNAL_SHA', hashlib.sha256(raw).hexdigest())
    plan['journal_sha256'] = recovery.JOURNAL_SHA
    with pytest.raises(RuntimeError, match='phase'):
        recovery.validate(plan, raw, migration_raw)


def test_recovery_cannot_repeat_ddl_or_restart_healthy_apps():
    tree = ast.parse(SOURCE.read_text(encoding='utf8'))
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not {'schema.migrate', 'schema.invoke', 'office.activate', 'cloud_backend.activate'}.intersection(calls)
    assert {'schema.resume_external', 'schema.resume_maintenance',
            'outbound_release.verify_completion', 'static.activate'}.issubset(calls)


def test_modified_cached_or_installed_static_blocks_recovery(tmp_path):
    records = {}
    for name in ('frontend', 'frontend-pm', 'frontend-portal'):
        records['build-' + name] = {'digest': name, 'files': {'index.html': 'fixture'}}
    actual = {}
    for name, folder in [('frontend', 'frontend/dist'), ('frontend-pm', 'frontend-pm/dist'),
                         ('pm-lan', 'frontend-pm/dist-lan')]:
        path = tmp_path / folder / 'index.html'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original')
        records['office-' + name] = {'files': {'index.html': hashlib.sha256(b'original').hexdigest()}}
    p = SimpleNamespace(STATE=tmp_path / 'state', marker=records.__getitem__)
    static = SimpleNamespace(manifest=lambda path: actual.get(str(path), {'index.html': 'fixture'}))
    assert len(recovery.cached_outputs(p, static, tmp_path)) == 4
    path.write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='Installed'):
        recovery.cached_outputs(p, static, tmp_path)
    path.write_bytes(b'original')
    actual[str(p.STATE / 'builds/frontend-frontend')] = {'index.html': 'different'}
    with pytest.raises(RuntimeError, match='build changed'):
        recovery.cached_outputs(p, static, tmp_path)


@pytest.mark.parametrize('change', [None, 'baseline', 'running', 'enabled'])
def test_mail_cannot_acquire_a_new_baseline_or_start_unexpectedly(change):
    baseline = {'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
                'status': 'frozen', 'was_active': False, 'was_enabled': False, 'first_install': False}
    value = {'record': dict(baseline),
             'state': {'ActiveState': 'inactive', 'UnitFileState': 'disabled', 'MainPID': '0'}}
    if change == 'baseline':
        value['record']['was_active'] = True
    elif change == 'running':
        value['state'].update(ActiveState='active', MainPID='123')
    elif change == 'enabled':
        value['state']['UnitFileState'] = 'enabled'
    p = SimpleNamespace(BJ='owned-host', run=lambda *args, **kwargs: json.dumps(value))
    if change:
        with pytest.raises(RuntimeError, match='baseline'):
            recovery.verify_mail_baseline(p, [], {'baseline': baseline})
    else:
        assert recovery.verify_mail_baseline(p, [], {'baseline': baseline}) == value


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Real recovery orchestration with all external effects replaced by recorded calls."""
    live = tmp_path / 'live'
    state = live / '.deploy_state'
    source = state / 'sources' / recovery.REVISION
    (source / 'deploy/nginx').mkdir(parents=True)
    for name in ('platforms.json', 'nginx/colorwork-cloud.conf', 'nginx/colorwork-office.conf'):
        (source / 'deploy' / name).write_bytes((SOURCE.parent / name).read_bytes())
    inventory = json.loads((source / 'deploy/platforms.json').read_text(encoding='utf8'))
    baseline = {'active': True, 'enabled': True}
    outbound = {'status': 'installed_paused', 'revision': recovery.REVISION,
                'release_id': recovery.RELEASE_ID, 'digest': 'artifact', 'mode': 'legacy',
                'database_fingerprint': 'owned-db', 'baseline': baseline}
    journal = {'status': 'failed', 'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
               'scope': 'office-and-cloud', 'completed': ['office', 'beijing-backend', 'colorwork-routing:cloud'],
               'outbound': outbound, 'mail_worker': {'baseline': {'was_active': False}}}
    migration = {'status': 'upgraded', 'schema': recovery.SCHEMA, 'pending': [recovery.SCHEMA],
                 'stopped': [], 'writers': [{'writer': w, 'before': 'running'} for w in inventory['migration_writers']]}
    raw, migration_raw = json.dumps(journal).encode(), json.dumps(migration).encode()
    (state / 'publish-current.json').write_bytes(raw)
    (state / 'schema-writers.json').write_bytes(migration_raw)
    monkeypatch.setattr(recovery, 'JOURNAL_SHA', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(recovery, 'MIGRATION_SHA', hashlib.sha256(migration_raw).hexdigest())
    plan = state / 'plan.json'
    plan.write_text(json.dumps({'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
        'journal_sha256': recovery.JOURNAL_SHA, 'migration_sha256': recovery.MIGRATION_SHA}))
    events, options = [], {'fail_static': None}
    def effect(name, result=None):
        def call(*args, **kwargs):
            events.append(name)
            return result
        return call
    def run(args, **kwargs):
        if args[0] == 'git':
            return recovery.REVISION if args[1] == 'rev-parse' else ''
        if args[1:3] == ['get', 'CommissionSystem']:
            return {'Application': str(live / 'python.exe'), 'AppDirectory': str(live / 'backend'),
                    'AppParameters': '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'}[args[3]]
        events.append('seed:' + args[1])
    def atomic(path, data):
        path.write_text(json.dumps(data))
    p = SimpleNamespace(ROOT=live, STATE=state, BJ='owned-host', run=run, atomic_json=atomic,
        deployment_lock=nullcontext, marker=lambda name: {'revision': recovery.REVISION,
                                                        'schema': recovery.SCHEMA, 'previous': 'a' * 40})
    schema = SimpleNamespace(database_lock=lambda *args: nullcontext(),
        schema_check=lambda *args: {'schema': recovery.SCHEMA, 'database': recovery.SCHEMA, 'pending': []},
        writer_state=lambda *args: 'running', resume_external=effect('writers'),
        resume_maintenance=effect('maintenance'), complete=effect('complete'))
    def activate_static(item):
        events.append('static:' + item['target'])
        if options['fail_static'] == item['target']:
            raise RuntimeError('synthetic static failure')
    static = SimpleNamespace(SSH_OPTIONS=[], activate=activate_static)
    routes = SimpleNamespace(prepare=effect('routes-prepare', ['cloud', 'office']),
        activate=lambda item, source: {'region': item})
    out = SimpleNamespace(artifact=lambda path: {'same': 'bytes'},
        prepare=effect('outbound-prepare', {'receipt': dict(outbound)}),
        phase=effect('outbound-activate', {**outbound, 'status': 'activated'}),
        verify_completion=effect('outbound-verify', {**outbound, 'status': 'verified'}))
    mail = SimpleNamespace(prepare=effect('mail-prepare', {}), invoke=effect('mail', {'status': 'verify'}))
    helper = SimpleNamespace(remote_state=lambda *args: {'outbound': dict(outbound)},
        expected_writer_state=lambda row: 'running', runtime_context=lambda *args: {})
    targets = [{'target': str(i), 'request': {'root': '/owned'}, 'bytes': 0} for i in range(2)]
    modules = {'publish': p, 'schema_release': schema, 'office_release': SimpleNamespace(health=lambda port: None),
        'static_sync': static, 'colorwork_routing': routes, 'okki_outbound_release': out,
        'mail_worker_release': mail, 'recover_outbound_activation': helper,
        'static_prepare': SimpleNamespace(prepare_all=effect('static-prepare', targets)),
        'candidate_retention': SimpleNamespace(record_success=effect('history'))}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(recovery, 'cached_outputs', lambda *args: {})
    monkeypatch.setattr(recovery, 'verify_mail_baseline', lambda *args: {'original': True})
    return plan, state, events, options


def test_prepare_does_not_start_or_record_recovery(runtime):
    plan, state, events, _ = runtime
    before = (state / 'publish-current.json').read_bytes()
    assert recovery.execute(plan, prepare_only=True)['status'] == 'prepared'
    assert events == []
    assert (state / 'publish-current.json').read_bytes() == before
    assert not list(state.glob('routing-activation-recovery-*'))


def test_complete_recovery_restores_tasks_only_after_static(runtime):
    plan, state, events, _ = runtime
    assert recovery.execute(plan)['revision'] == recovery.REVISION
    assert events.index('static:1') < events.index('outbound-activate') < events.index('writers')
    assert events.index('mail') < events.index('maintenance') < events.index('complete')
    journal = json.loads((state / 'publish-current.json').read_text())
    assert journal['status'] == 'succeeded'
    assert journal['completed'].count('colorwork-routing:cloud') == 1
    assert journal['recovered_seeds'] == ['scripts/seed_pm.py', 'scripts/import_pantone.py']
    with pytest.raises(ValueError):
        recovery.execute(plan)


def test_partial_static_failure_preserves_progress_and_rejects_replay(runtime):
    plan, state, events, options = runtime
    options['fail_static'] = '1'
    with pytest.raises(RuntimeError, match='synthetic'):
        recovery.execute(plan)
    assert 'outbound-activate' not in events and 'writers' not in events and 'complete' not in events
    journal = json.loads((state / 'publish-current.json').read_text())
    assert journal['status'] == 'failed' and '0:/owned' in journal['completed']
    assert '1:/owned' not in journal['completed']
    assert journal['recovery']['phase'] == 'static:1:/owned'
    before = list(events)
    with pytest.raises(ValueError):
        recovery.execute(plan)
    assert events == before
