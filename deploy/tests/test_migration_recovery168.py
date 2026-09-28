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
import migration_recovery168 as recovery
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
    stopped = list(writers)
    writers.append({"host": "root@119.28.107.92", "kind": "systemd_timer", "service": "ark-okki-outbound-poller", "timer": "ark-okki-outbound-poller.timer"})
    original = {"status": "failed-after-ddl", "schema": recovery.NEW,
                "database": recovery.PREVIOUS, "pending": recovery.CHAIN,
                "stopped": stopped, "writers": [{"writer": w, "before": "stopped" if w["kind"] == "systemd_timer" else "running"} for w in writers]}
    path = tmp_path / "schema-writers.json"
    path.write_text(json.dumps(original))
    request = {"journal_path": str(path), "writers": writers, "schema": recovery.NEW,
               "pending": recovery.CHAIN, "action": "apply", "nssm": "mock", "recover_168": True}
    return path, original, request


def test_normal_retry_stays_blocked_and_incident_specific_flag_preserves_evidence(incident):
    path, original, request = incident
    with pytest.raises(RuntimeError, match="requires inspection"):
        schema_release.check_recovery(path)
    schema_release.check_recovery(path, recover_168=True)
    assert recovery.read_record(path, request["writers"]) == (original, original)
    assert json.loads(path.read_text()) == original


@pytest.mark.parametrize("mutation", ["schema", "pending", "status", "baseline", "stopped", "duplicate"])
def test_unrelated_or_incomplete_evidence_is_rejected(incident, mutation):
    path, original, _ = incident
    row = copy.deepcopy(original)
    if mutation in {"schema", "status"}:
        row[mutation] = "unrelated"
    elif mutation == "pending":
        row["pending"] = ["other"]
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
    assert len([e for e in x.events[:x.events.index('upgrade')] if e.startswith('stop:')]) == 5
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


def test_incomplete_stop_blocks_ddl_and_never_starts_old_code(execution, monkeypatch):
    x = execution
    monkeypatch.setattr(schema_release, "writer_state", lambda *_: "running")
    with pytest.raises(RuntimeError, match="every registered writer"):
        recovery.execute(x.request, x.connection, "settings")
    x.upgrade.assert_not_called()
    assert json.loads(x.path.read_text())["recovery_original"] == x.original
    assert not any(e.startswith("start:") for e in x.events)


def test_retry_preserves_original_running_baseline(execution):
    x = execution
    x.upgrade.side_effect = RuntimeError("interrupted")
    with pytest.raises(RuntimeError):
        recovery.execute(x.request, x.connection, "settings")
    x.upgrade.side_effect = None
    result = recovery.execute(x.request, x.connection, "settings")
    assert json.loads(x.path.read_text())["recovery_original"] == x.original
    assert result["stopped"] == x.original["stopped"]
    assert not any(e.startswith("start:") for e in x.events)


@pytest.mark.parametrize("status", ["restored", "healthy", "unknown"])
def test_final_or_unknown_recovery_status_is_not_resumable(incident, status):
    path, original, _ = incident
    path.write_text(json.dumps({**original, "recovery_original": original,
                               "recovery": recovery.TAG, "status": status}))
    with pytest.raises(RuntimeError, match="not resumable"):
        recovery.read_record(path)


@pytest.mark.parametrize("current", [recovery.PREVIOUS, recovery.NEW])
def test_database_probe_checks_exact_pending_chain(monkeypatch, current):
    from alembic.script import ScriptDirectory
    script = SimpleNamespace(get_heads=lambda: [recovery.NEW], get_revision=lambda _: SimpleNamespace(down_revision=recovery.PREVIOUS))
    monkeypatch.setattr(ScriptDirectory, "from_config", lambda _: script)
    validator = Mock()
    monkeypatch.setattr(recovery, "validate_existing", validator)
    connection = Mock()
    connection.execute.return_value.scalars.return_value = [current]
    connection.execute.return_value.scalar.return_value = 0
    pending = [recovery.NEW] if current == recovery.PREVIOUS else []
    recovery.inspect_database(connection, {"schema": recovery.NEW, "pending": pending})
    validator.assert_called_once_with(connection)
    with pytest.raises(RuntimeError, match="changed since preparation"):
        recovery.inspect_database(connection, {"schema": recovery.NEW, "pending": ["unexpected"]})
    connection.execute.return_value.scalar.return_value = 1
    with pytest.raises(RuntimeError, match="empty partial table|missing backfill"):
        recovery.inspect_database(connection, {"schema": recovery.NEW, "pending": pending})


def test_release_reuses_frozen_identity_and_preserves_archive(tmp_path, monkeypatch):
    import hashlib
    import publish
    import okki_outbound_release
    files = {"worker": {"sha256": "abc"}}
    digest = hashlib.sha256(json.dumps({"worker": "abc"}).encode()).hexdigest()
    original = {"revision": recovery.FAILED_REVISION, "release_id": recovery.RELEASE_ID,
                "scope": "office-and-cloud", "status": "failed", "completed": [],
                "outbound": {"status": "frozen", "schedule": {"active": True, "enabled": True}, "digest": digest}}
    monkeypatch.setattr(okki_outbound_release, "artifact", lambda _: files)
    def run(args, **kwargs):
        return "backend/alembic/versions/168_customer_media_customer_tags.py" if args[1] == "diff" else ""
    monkeypatch.setattr(publish, "run", run)
    assert recovery.prepare_release(tmp_path, tmp_path, "a" * 40, original) == original
    resumed = {"revision": "a" * 40, "release_id": recovery.RELEASE_ID, "status": "prepared"}
    assert recovery.prepare_release(tmp_path, tmp_path, "a" * 40, resumed) == original
    assert json.loads((tmp_path / "recovery-168-original-publish.json").read_text()) == original
    with pytest.raises(RuntimeError, match="candidate changed"):
        recovery.prepare_release(tmp_path, tmp_path, "b" * 40, resumed)
    files["worker"]["sha256"] = "changed"
    with pytest.raises(RuntimeError, match="artifact changed"):
        recovery.prepare_release(tmp_path, tmp_path, "a" * 40, resumed)


def test_schema_shape_rejects_signed_ids(monkeypatch):
    import sqlalchemy
    from sqlalchemy.dialects.mysql import INTEGER, VARCHAR, DATETIME
    columns = [{"name": n, "type": INTEGER(unsigned=True), "nullable": n == "created_by"}
               for n in ["dimension_id", "tag_value_id", "created_by"]]
    columns += [{"name": "customer_id", "type": VARCHAR(64), "nullable": False},
                {"name": "created_at", "type": DATETIME(), "nullable": False}]
    inspector = Mock()
    inspector.get_columns.return_value = columns
    inspector.get_pk_constraint.return_value = {"constrained_columns": ["customer_id", "dimension_id", "tag_value_id"]}
    inspector.get_foreign_keys.return_value = [
        {"constrained_columns": [n], "referred_table": t, "referred_columns": ["id"], "options": {}}
        for n,t in [("dimension_id","ark_tag_dimensions"),("tag_value_id","ark_tag_values"),("created_by","ark_users")]]
    inspector.get_indexes.return_value = [{"name": "idx_customer_media_customer_tag_value", "unique": False, "column_names": ["tag_value_id", "customer_id"]}]
    monkeypatch.setattr(sqlalchemy, "inspect", lambda _: inspector)
    connection = Mock()
    connection.execute.return_value.all.return_value = [(recovery.TABLE,"utf8mb4_0900_ai_ci"),("ark_customer_media_batches","utf8mb4_unicode_ci")]
    recovery.validate_existing(connection)
    columns[0]["type"] = INTEGER(unsigned=False)
    with pytest.raises(RuntimeError, match="integer type"):
        recovery.validate_existing(connection)


def test_completed_schema_checkpoint_can_finalize_without_repeating_upgrade(execution):
    x = execution
    record = {**x.original, "recovery": recovery.TAG, "recovery_original": x.original, "status": "completed"}
    x.path.write_text(json.dumps(record))
    x.inspect.return_value = ("alembic", [recovery.NEW])
    recovery.execute({**x.request, "pending": []}, x.connection, "settings")
    x.upgrade.assert_not_called()
    assert json.loads(x.path.read_text())["recovery_original"] == x.original
