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
