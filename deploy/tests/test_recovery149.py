"""Isolated incident recovery tests. No database, network, or service access."""

import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import migration_recovery149 as recovery
import schema_release


@pytest.fixture
def incident(tmp_path):
    writers = [
        {"host": "office", "kind": "nssm", "service": "CommissionSystem"},
        {"host": "office", "kind": "nssm", "service": "WhatsAppConnector"},
        {"host": "ubuntu@154.8.205.162", "kind": "systemd", "service": "ark-backend"},
        {"host": "root@119.28.107.92", "kind": "pm2", "service": "shipment-tracking-mcp",
         "executable": "/root/.nvm/versions/node/v22.22.1/bin/pm2"},
    ]
    original = {"status": "failed-after-ddl", "schema": recovery.OLD,
                "database": "147_customer_media_directories", "pending": [recovery.PREVIOUS, recovery.OLD],
                "stopped": writers, "writers": [{"writer": w, "before": "running"} for w in writers]}
    path = tmp_path / "schema-writers.json"
    path.write_text(json.dumps(original))
    request = {"journal_path": str(path), "writers": writers, "schema": recovery.NEW,
               "pending": [recovery.NEW], "action": "apply", "nssm": "mock", "recover_149": True}
    return path, original, request


def test_normal_retry_stays_blocked_and_incident_specific_flag_preserves_evidence(incident):
    path, original, request = incident
    with pytest.raises(RuntimeError, match="requires inspection"):
        schema_release.check_recovery(path)
    schema_release.check_recovery(path, recover_149=True)
    assert recovery.read_record(path, request["writers"]) == (original, original)
    assert json.loads(path.read_text()) == original


@pytest.mark.parametrize("mutation", ["schema", "pending", "status", "baseline", "stopped", "duplicate"])
def test_unrelated_or_incomplete_evidence_is_rejected(incident, mutation):
    path, original, _ = incident
    row = copy.deepcopy(original)
    if mutation in {"schema", "status"}:
        row[mutation] = "unrelated"
    elif mutation == "pending":
        row["pending"] = [recovery.OLD]
    elif mutation == "baseline":
        row["writers"][0]["before"] = "stopped"
    elif mutation == "stopped":
        row["stopped"] = []
    else:
        row["writers"].append(row["writers"][0])
    path.write_text(json.dumps(row))
    with pytest.raises(RuntimeError):
        recovery.read_record(path)


def test_changed_inventory_is_rejected(incident):
    path, _, request = incident
    with pytest.raises(RuntimeError, match="inventory"):
        recovery.read_record(path, request["writers"][:-1])


@pytest.fixture
def execution(incident, monkeypatch):
    from alembic import command
    path, original, request = incident
    events = []
    state = {w["service"]: "stopped" for w in request["writers"]}
    connection = Mock()
    def sql(statement):
        events.append(str(statement))
        result = Mock()
        result.scalar.return_value = 1
        result.scalars.return_value = [recovery.NEW]
        return result
    connection.execute.side_effect = sql
    connection.commit.side_effect = lambda: events.append('commit')
    inspect = Mock(return_value=("alembic", [recovery.PREVIOUS]))
    monkeypatch.setattr(recovery, "inspect_database", inspect)
    def control(writer, action, nssm):
        assert json.loads(path.read_text())["recovery_original"] == original
        events.append(action + ':' + writer["service"])
        state[writer["service"]] = 'stopped' if action == 'stop' else 'running'
    monkeypatch.setattr(schema_release, "control", Mock(side_effect=control))
    monkeypatch.setattr(schema_release, "writer_state", lambda writer, _: state[writer["service"]])
    upgrade = Mock(side_effect=lambda *_: events.append('upgrade'))
    monkeypatch.setattr(command, "upgrade", upgrade)
    monkeypatch.setattr(command, "stamp", Mock(side_effect=AssertionError('must not stamp')))
    import app.core.config as config
    monkeypatch.setattr(config, "get_settings", lambda: "original-settings")
    return SimpleNamespace(path=path, original=original, request=request, events=events,
                           connection=connection, inspect=inspect, upgrade=upgrade)


def test_prepare_only_is_read_only(execution):
    x = execution
    result = recovery.execute({**x.request, "action": "check"}, x.connection, "settings")
    assert result["status"] == "recovery-ready"
    assert json.loads(x.path.read_text()) == x.original
    assert x.events == []
    x.upgrade.assert_not_called()


def test_recovery_keeps_original_baseline_until_full_publish_completes(execution):
    x = execution
    result = recovery.execute(x.request, x.connection, "settings")
    record = json.loads(x.path.read_text())
    assert record["recovery_original"] == x.original
    assert record["status"] == "upgraded"
    assert result["stopped"] == x.original["stopped"]
    assert len([e for e in x.events[:x.events.index('upgrade')] if e.startswith('stop:')]) == 4
    assert not any(e.startswith('start:') for e in x.events)
    assert x.events.index('upgrade') < x.events.index('commit') < next(
        i for i, value in enumerate(x.events) if 'SELECT version_num' in value)
    assert 'RELEASE_LOCK' in x.events[-1]
    assert recovery.read_record(x.path)[1] == x.original
    with pytest.raises(RuntimeError, match="requires inspection"):
        schema_release.check_recovery(x.path)


def test_recovery_failure_never_restarts_old_code(execution):
    x = execution
    x.upgrade.side_effect = RuntimeError('migration error')
    with pytest.raises(RuntimeError):
        recovery.execute(x.request, x.connection, 'settings')
    record = json.loads(x.path.read_text())
    assert record["recovery_original"] == x.original
    assert record["status"] == 'failed-after-ddl'
    assert not any(e.startswith('start:') for e in x.events)
    assert 'RELEASE_LOCK' in x.events[-1]


def test_schema_mismatch_fails_before_service_control(execution):
    x = execution
    x.inspect.side_effect = RuntimeError('schema mismatch')
    with pytest.raises(RuntimeError):
        recovery.execute(x.request, x.connection, 'settings')
    assert json.loads(x.path.read_text()) == x.original
    assert not any(e.startswith(('start:', 'stop:')) for e in x.events)


def test_database_lock_contention_does_not_change_evidence(execution):
    x = execution
    x.connection.execute.side_effect = lambda _: SimpleNamespace(scalar=lambda: 0)
    with pytest.raises(RuntimeError, match='owns the lock'):
        recovery.execute(x.request, x.connection, 'settings')
    assert json.loads(x.path.read_text()) == x.original
    x.upgrade.assert_not_called()


@pytest.mark.parametrize('current,pending,complete', [
    (recovery.PREVIOUS, [recovery.NEW], False), (recovery.NEW, [], True),
])
def test_database_probe_validates_actual_head_pending_and_complete_schema(monkeypatch, current, pending, complete):
    from alembic.script import ScriptDirectory
    validator = Mock()
    script = SimpleNamespace(get_heads=lambda: [recovery.NEW],
                             get_revision=lambda _: SimpleNamespace(path='reviewed-migration.py'))
    monkeypatch.setattr(ScriptDirectory, 'from_config', lambda _: script)
    spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: setattr(module, 'validate_existing', validator)))
    monkeypatch.setattr(recovery.importlib.util, 'spec_from_file_location', lambda *_: spec)
    monkeypatch.setattr(recovery.importlib.util, 'module_from_spec', lambda _: SimpleNamespace())
    connection = Mock()
    connection.execute.return_value.scalars.return_value = [current]
    recovery.inspect_database(connection, {'schema': recovery.NEW, 'pending': pending})
    validator.assert_called_once_with(connection, require_complete=complete)
    with pytest.raises(RuntimeError, match='changed since preparation'):
        recovery.inspect_database(connection, {'schema': recovery.NEW, 'pending': ['unexpected']})
    with pytest.raises(RuntimeError, match='corrected 149'):
        recovery.inspect_database(connection, {'schema': recovery.OLD, 'pending': pending})
