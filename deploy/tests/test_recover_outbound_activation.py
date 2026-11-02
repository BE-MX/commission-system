"""Reject every checkpoint other than the reviewed post-static interruption."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / 'recover_outbound_activation.py'
spec = importlib.util.spec_from_file_location('outbound_activation_recovery', SOURCE)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def checkpoint():
    journal = {'status': 'failed', 'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
        'scope': 'office-and-cloud', 'completed': recovery.COMPLETED,
        'outbound': {'status': 'installed_paused', 'revision': recovery.REVISION,
            'release_id': recovery.RELEASE_ID, 'release_confirmed': False,
            'target_schedule': {'active': False, 'enabled': False}}}
    migration = {'status': 'upgraded', 'schema': recovery.SCHEMA,
        'database': '202_presale_order_revision', 'pending': ['203_perf_goals', recovery.SCHEMA]}
    return journal, migration


def validate(journal, migration, patch=None):
    raw = json.dumps(journal).encode()
    plan = {'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
        'journal_sha256': hashlib.sha256(raw).hexdigest()}
    plan.update(patch or {})
    return recovery.validate(plan, raw, migration)


def test_exact_checkpoint_is_accepted_without_modifying_inputs():
    journal, migration = checkpoint()
    expected = copy.deepcopy((journal, migration))
    assert validate(journal, migration) == journal
    assert (journal, migration) == expected


@pytest.mark.parametrize('field,value', [
    ('status', 'succeeded'), ('scope', 'cloud-only'), ('revision', '0' * 40),
    ('release_id', '0' * 32), ('completed', recovery.COMPLETED[:-1]),
    ('completed', recovery.COMPLETED + ['singapore-outbound'])])
def test_wrong_release_or_partial_checkpoint_is_rejected(field, value):
    journal, migration = checkpoint(); journal[field] = value
    with pytest.raises(RuntimeError): validate(journal, migration)


@pytest.mark.parametrize('field,value', [('status', 'activated'), ('release_confirmed', True),
    ('target_schedule', {'active': True, 'enabled': True})])
def test_an_uncertain_activation_is_not_replayed(field, value):
    journal, migration = checkpoint(); journal['outbound'][field] = value
    with pytest.raises(RuntimeError): validate(journal, migration)


@pytest.mark.parametrize('field,value', [('schema', '202_presale_order_revision'),
    ('status', 'migrating'), ('database', '201_portal_access_requests'), ('pending', [])])
def test_migration_checkpoint_is_exact(field, value):
    journal, migration = checkpoint(); migration[field] = value
    with pytest.raises(RuntimeError): validate(journal, migration)


def test_original_journal_hash_and_plan_fields_are_required():
    journal, migration = checkpoint()
    for patch in ({'journal_sha256': '0' * 64}, {'revision': '0' * 40}, {'force': True}):
        with pytest.raises(ValueError): validate(journal, migration, patch)


def test_recovery_does_not_include_ddl_or_application_or_static_activation():
    import ast
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not {'schema.migrate', 'schema.invoke', 'office.activate', 'static.activate',
        'cloud_backend.activate'}.intersection(calls)
    assert 'schema.resume_external' in calls and 'schema.resume_maintenance' in calls
    assert 'outbound_release.verify_completion' in calls


def test_actual_maintenance_resume_request_retains_original_pending_chain(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    sys.path.insert(0, str(SOURCE.parent))
    import schema_release as schema
    _, migration = checkpoint()
    state = tmp_path / 'state'
    (state / 'credentials').mkdir(parents=True)
    (state / 'credentials/migration.env').write_text('TEST_OWNED_PLACEHOLDER=1')
    (state / 'schema-writers.json').write_text(json.dumps({
        **migration, 'portal_maintenance': {'restored': False}}))
    monkeypatch.setattr(schema, 'STATE', state)
    monkeypatch.setattr(schema, 'ROOT', tmp_path)
    calls = []
    def run(args, **options):
        request = json.loads(options['input'])
        calls.append(request)
        assert request['action'] == 'resume-maintenance'
        assert request['schema'] == recovery.SCHEMA
        assert request['pending'] == ['203_perf_goals', recovery.SCHEMA]
        assert request['writers'] == []
        return SimpleNamespace(returncode=0, stdout='{"status":"restored"}')
    monkeypatch.setattr(schema.subprocess, 'run', run)
    schema.resume_maintenance(recovery.runtime_context('owned-python', 'owned-nssm', migration))
    assert len(calls) == 1


FREIGHT_REVISION = 'b817650a69a6865886c9f4d7a0c61bc1ec9ec807'
FREIGHT_RELEASE_ID = '6d6683095e704b818c90d3db43b1c57d'


def freight_checkpoint():
    journal, migration = checkpoint()
    for record in (journal, journal['outbound']):
        record.update(revision=FREIGHT_REVISION, release_id=FREIGHT_RELEASE_ID)
    migration.update(schema='247_sales_return_freight', database='246_domestic_followup',
                     pending=['247_sales_return_freight'])
    return journal, migration


def validate_freight(journal, migration, patch=None):
    raw = json.dumps(journal).encode()
    plan = {'revision': FREIGHT_REVISION, 'release_id': FREIGHT_RELEASE_ID,
            'journal_sha256': hashlib.sha256(raw).hexdigest(), **(patch or {})}
    return recovery.validate(plan, raw, migration)


def test_freight_checkpoint_retains_exact_original_application_and_migration():
    journal, migration = freight_checkpoint()
    before = copy.deepcopy((journal, migration))
    assert validate_freight(journal, migration) == journal
    assert (journal, migration) == before
    context = recovery.runtime_context('owned-python', 'owned-nssm', migration)
    assert context['schema'] == '247_sales_return_freight'
    assert context['pending'] == ['247_sales_return_freight']
    context['pending'].clear()
    assert migration['pending'] == ['247_sales_return_freight']


@pytest.mark.parametrize('section,field,value', [
    ('journal', 'revision', recovery.REVISION),
    ('journal', 'release_id', recovery.RELEASE_ID),
    ('journal', 'completed', recovery.COMPLETED[:-1]),
    ('journal', 'status', 'succeeded'),
    ('outbound', 'status', 'enabled'),
    ('outbound', 'release_confirmed', True),
    ('outbound', 'revision', recovery.REVISION),
    ('outbound', 'target_schedule', {'active': True, 'enabled': True}),
    ('migration', 'schema', recovery.SCHEMA),
    ('migration', 'database', '245_commerce_transition'),
    ('migration', 'pending', []),
    ('migration', 'status', 'completed'),
])
def test_freight_recovery_rejects_changed_checkpoint(section, field, value):
    journal, migration = freight_checkpoint()
    target = {'journal': journal, 'outbound': journal['outbound'], 'migration': migration}[section]
    target[field] = value
    with pytest.raises(RuntimeError):
        validate_freight(journal, migration)


def test_freight_plan_cannot_mix_reviewed_releases_or_ignore_journal_hash():
    journal, migration = freight_checkpoint()
    for patch in ({'revision': recovery.REVISION}, {'release_id': recovery.RELEASE_ID},
                  {'journal_sha256': '0' * 64}, {'force': True}):
        with pytest.raises(ValueError):
            validate_freight(journal, migration, patch)


def attempted_checkpoint(monkeypatch):
    journal, migration = freight_checkpoint()
    original = copy.deepcopy(journal)
    journal['recovery'] = {'phase': 'outbound-activate', 'status': 'running', 'controller': 'owned'}
    prior = {'status': 'started', 'original': original, 'migration': copy.deepcopy(migration),
             'remote': {'outbound': {'status': 'installed_paused'}}}
    raw, receipt = json.dumps(journal).encode(), json.dumps(prior).encode()
    pair = (hashlib.sha256(raw).hexdigest(), hashlib.sha256(receipt).hexdigest())
    monkeypatch.setattr(recovery, 'REVIEWED_RETRIES', {pair})
    return journal, migration, prior, raw, receipt


def test_first_attempt_rejects_missing_recovery_receipt():
    journal, migration = freight_checkpoint()
    assert recovery.inspect_previous_attempt(b'initial', None, journal, migration) is None
    journal['recovery'] = {'status': 'running'}
    with pytest.raises(RuntimeError, match='missing'):
        recovery.inspect_previous_attempt(b'initial', None, journal, migration)


def test_retry_requires_both_exact_immutable_snapshots(monkeypatch):
    journal, migration, _, raw, receipt = attempted_checkpoint(monkeypatch)
    assert recovery.inspect_previous_attempt(raw, receipt, journal, migration) == hashlib.sha256(receipt).hexdigest()
    for changed_raw, changed_receipt in [(raw+b' ', receipt), (raw, receipt+b' ')]:
        with pytest.raises(RuntimeError, match='inspected'):
            recovery.inspect_previous_attempt(changed_raw, changed_receipt, journal, migration)


@pytest.mark.parametrize('change', ['phase', 'status', 'migration', 'original', 'remote'])
def test_retry_rejects_progress_even_if_hash_was_reviewed(monkeypatch, change):
    journal, migration, prior, raw, receipt = attempted_checkpoint(monkeypatch)
    if change == 'phase': journal['recovery']['phase'] = 'writers-resume'
    elif change == 'status': prior['status'] = 'succeeded'
    elif change == 'migration': prior['migration']['status'] = 'completed'
    elif change == 'original': prior['original']['completed'] = []
    else: prior['remote']['outbound']['status'] = 'activated'
    raw, receipt = json.dumps(journal).encode(), json.dumps(prior).encode()
    monkeypatch.setattr(recovery, 'REVIEWED_RETRIES', {(hashlib.sha256(raw).hexdigest(), hashlib.sha256(receipt).hexdigest())})
    with pytest.raises(RuntimeError, match='progressed'):
        recovery.inspect_previous_attempt(raw, receipt, journal, migration)


def test_retry_archives_both_bytes_without_overwriting_evidence(tmp_path):
    receipt = tmp_path/'attempt.json'
    receipt.write_bytes(b'old receipt')
    recovery.archive_previous_attempt(receipt, b'old journal', b'old receipt', 'a'*64)
    assert receipt.read_bytes() == b'old receipt'
    archive = receipt.with_name('attempt-'+'a'*64+'-journal.json')
    assert archive.read_bytes() == b'old journal'
    recovery.archive_previous_attempt(receipt, b'old journal', b'old receipt', 'a'*64)
    with pytest.raises(RuntimeError, match='differs'):
        recovery.archive_previous_attempt(receipt, b'changed journal', b'old receipt', 'a'*64)
    assert archive.read_bytes() == b'old journal'
