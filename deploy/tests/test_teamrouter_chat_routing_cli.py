"""CLI and durable receipts, without network or production effects."""
import ast
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
routing = importlib.import_module('teamrouter_chat_routing')


@pytest.fixture
def harness(tmp_path, monkeypatch, capsys):
    def atomic(path, value):
        path.write_text(json.dumps(value), encoding='utf8')
    monkeypatch.setitem(sys.modules, 'publish', SimpleNamespace(STATE=tmp_path, atomic_json=atomic))
    monkeypatch.setenv('ARK_TEAMROUTER_CHAT_VERIFIER', 'x' * 22)
    (tmp_path / 'nginx').mkdir()
    (tmp_path / 'nginx' / 'teamrouter-chat.conf').write_text('fixed template')
    monkeypatch.setattr(routing, 'HERE', tmp_path)
    calls = []
    result = {'baseline': 'a' * 64, 'candidate': 'b' * 64}
    def remote(target, script, request, **kwargs):
        calls.append((target, script, request, kwargs))
        status = {'prepare': 'prepared', 'activate': 'activated', 'rollback': 'rolled_back'}[request['action']]
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': status, **result}))
    monkeypatch.setattr(routing, 'remote_python', remote)
    return tmp_path / 'teamrouter-chat-route.json', calls, result


def test_prepare_activate_rollback_retains_original_baseline(harness, capsys):
    record, calls, result = harness
    routing.execute('prepare')
    routing.execute('activate')
    routing.execute('rollback')
    saved = json.loads(record.read_text())
    assert saved['status'] == 'rolled_back'
    assert saved['baseline'] == 'a' * 64
    assert all(call[0] == 'root@119.28.107.92' for call in calls)
    assert calls[1][2]['baseline'] == calls[2][2]['baseline'] == 'a' * 64
    assert 'x' * 22 not in capsys.readouterr().out


def test_failure_keeps_recovery_evidence(harness, monkeypatch):
    record, calls, result = harness
    routing.execute('prepare')
    monkeypatch.setattr(routing, 'remote_python', lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match='Remote TeamRouter'):
        routing.execute('activate')
    saved = json.loads(record.read_text())
    assert saved['status'] == 'activate_failed'
    assert saved['baseline'] == 'a' * 64
    assert saved['candidate'] == 'b' * 64


def test_bad_receipt_is_not_success(harness):
    record, calls, result = harness
    result['candidate'] = 'invalid'
    with pytest.raises(RuntimeError, match='Invalid TeamRouter'):
        routing.execute('prepare')
    assert json.loads(record.read_text())['status'] == 'prepare_failed'


def test_remote_failure_status_cannot_be_marked_prepared(harness):
    record, calls, result = harness
    result['status'] = 'failed'
    with pytest.raises(RuntimeError, match='did not confirm success'):
        routing.execute('prepare')
    assert json.loads(record.read_text())['status'] == 'prepare_failed'


def test_changed_remote_baseline_preserves_original(harness):
    record, calls, result = harness
    routing.execute('prepare')
    result['baseline'] = 'c' * 64
    with pytest.raises(RuntimeError, match='differs from prepared baseline'):
        routing.execute('activate')
    assert json.loads(record.read_text())['baseline'] == 'a' * 64


def test_bad_verifier_never_contacts_remote(harness, monkeypatch):
    record, calls, result = harness
    monkeypatch.setenv('ARK_TEAMROUTER_CHAT_VERIFIER', 'not-a-verifier')
    with pytest.raises(RuntimeError, match='22 base64url'):
        routing.execute('prepare')
    assert not calls
    assert not record.exists()


def test_failed_prepare_retry_preserves_evidence(harness):
    record, calls, result = harness
    result['candidate'] = 'invalid'
    with pytest.raises(RuntimeError):
        routing.execute('prepare')
    result['candidate'] = 'b' * 64
    routing.execute('prepare')
    assert json.loads(record.read_text())['previous']['status'] == 'prepare_failed'


def test_remote_diagnostics_are_allowlisted(harness, monkeypatch, capsys):
    record, calls, result = harness
    response = SimpleNamespace(returncode=1, stdout=json.dumps({
        'error_type': 'RuntimeError', 'stage': 'nginx_reload', 'message': 'private upstream detail'}))
    monkeypatch.setattr(routing, 'remote_python', lambda *a, **k: response)
    with pytest.raises(RuntimeError, match='stage=nginx_reload'):
        routing.execute('prepare')
    saved = json.loads(record.read_text())
    assert saved['remote_error'] == {'error_type': 'RuntimeError', 'stage': 'nginx_reload'}
    assert 'private upstream detail' not in record.read_text()
    assert not capsys.readouterr().out


def test_reprepare_same_verifier_updates_only_candidate_and_preserves_previous(harness):
    record, calls, result = harness
    routing.execute('prepare')
    result['candidate'] = 'c' * 64
    routing.execute('prepare')
    saved = json.loads(record.read_text())
    assert calls[-1][2]['expected_baseline'] == 'a' * 64
    assert saved['candidate'] == 'c' * 64
    assert saved['previous']['candidate'] == 'b' * 64
    assert saved['baseline'] == saved['previous']['baseline']


@pytest.mark.parametrize('failure', ['drift', 'remote'])
def test_reprepare_failure_restores_prepared_receipt(harness, monkeypatch, failure):
    record, calls, result = harness
    routing.execute('prepare')
    if failure == 'drift':
        result['baseline'] = 'c' * 64
    else:
        monkeypatch.setattr(routing, 'remote_python', lambda *a, **k: SimpleNamespace(returncode=1, stdout='{}'))
    with pytest.raises(RuntimeError):
        routing.execute('prepare')
    saved = json.loads(record.read_text())
    assert saved['status'] == 'prepared'
    assert saved['baseline'] == 'a' * 64 and saved['candidate'] == 'b' * 64
    assert 'reprepare_error' in saved


def test_reprepare_rejects_changed_verifier_or_active_receipt(harness, monkeypatch):
    record, calls, result = harness
    routing.execute('prepare')
    monkeypatch.setenv('ARK_TEAMROUTER_CHAT_VERIFIER', 'y' * 22)
    with pytest.raises(RuntimeError, match='same Singapore'):
        routing.execute('prepare')
    assert len(calls) == 1
    monkeypatch.setenv('ARK_TEAMROUTER_CHAT_VERIFIER', 'x' * 22)
    routing.execute('activate')
    with pytest.raises(RuntimeError, match='Existing TeamRouter'):
        routing.execute('prepare')


@pytest.mark.parametrize('other,value', [('whatsapp_connector_only', 'plan.json'), ('revision', 'a'*40),
                                        ('prepare_only', True), ('office_beijing_ingress', 'prepare')])
def test_exclusive_scope_checked_before_other_dispatch(other, value):
    source = DEPLOY / 'publish.py'
    tree = ast.parse(source.read_text(encoding='utf8'))
    main = next(node for node in tree.body if isinstance(node, ast.If)
                and ast.unparse(node.test) == "__name__ == '__main__'")
    guarded = next(node for node in main.body if isinstance(node, ast.Try))
    # The parse and first dispatch must reject mixed scopes before reaching any
    # connector, application, migration or other special release entry.
    statements = guarded.body[:2]
    assert 'teamrouter_chat_route' in ast.unparse(statements[1].test)
    args = SimpleNamespace(teamrouter_chat_route='prepare')
    setattr(args, other, value)
    parser = SimpleNamespace(parse_args=lambda: args)
    with pytest.raises(RuntimeError, match='TeamRouter route accepts only'):
        exec(compile(ast.Module(body=statements, type_ignores=[]), str(source), 'exec'), {'parser': parser})
