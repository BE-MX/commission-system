"""Migration-only release safety; no real services or database connections."""

from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import invoice_schema_repair
import publish
import schema_release

real_check_health = invoice_schema_repair.check_health


@pytest.fixture
def migration(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    state = tmp_path / ".deploy_state"
    state.mkdir()
    writers = [
        {"kind": "nssm", "host": "office", "service": "CommissionSystem"},
        {"kind": "nssm", "host": "office", "service": "WhatsAppConnector"},
        {"kind": "systemd", "host": "ubuntu@154.8.205.162", "service": "ark-backend"},
    ]
    plan = {"live_root": str(tmp_path), "source": str(source), "revision": "a" * 40,
            "migration_writers_verified": True, "migration_writers": writers,
            "reviewed_unaffected_events": ["existing_event"]}
    prepared = {"python": "isolated-python", "nssm": "mock-nssm", "port": 8001,
                "pending": invoice_schema_repair.PENDING, "events": ["existing_event"]}
    baseline = {invoice_schema_repair.writer_key(w): "running" for w in writers}
    baseline[invoice_schema_repair.writer_key(writers[1])] = "stopped"
    monkeypatch.setattr(invoice_schema_repair, "load_plan", lambda *_: (plan, source, prepared))
    monkeypatch.setattr(invoice_schema_repair, "check_applications", Mock())
    monkeypatch.setattr(invoice_schema_repair, "snapshot_writers", lambda *_: dict(baseline))
    health = Mock()
    monkeypatch.setattr(invoice_schema_repair, "check_health", health)
    monkeypatch.setattr(invoice_schema_repair, "verify_invoice_columns", Mock())
    monkeypatch.setattr(publish, "deployment_lock", nullcontext)
    monkeypatch.setattr(schema_release, "preflight", Mock())
    migrate = Mock(return_value=[writers[0], writers[2]])
    monkeypatch.setattr(schema_release, "migrate", migrate)
    monkeypatch.setattr(schema_release, "database_lock", lambda *_: nullcontext())
    monkeypatch.setattr(schema_release, "schema_check", Mock(return_value={"schema": invoice_schema_repair.TARGET, "database": invoice_schema_repair.TARGET, "pending": []}))
    control = Mock(return_value=True)
    monkeypatch.setattr(schema_release, "control", control)
    monkeypatch.setattr(publish, "ROOT", source)
    monkeypatch.setattr(publish, "STATE", state)
    monkeypatch.setattr(schema_release, "STATE", state)
    return SimpleNamespace(plan=plan, writers=writers, prepared=prepared, baseline=baseline,
                           state=state, migrate=migrate, control=control, health=health)


def test_prepare_only_does_not_stop_or_migrate(migration):
    invoice_schema_repair.execute("plan.json", "protected.env", prepare_only=True)
    migration.migrate.assert_not_called()
    migration.control.assert_not_called()
    assert json.loads((migration.state / "migration-167-current.json").read_text())["status"] == "prepared"


def test_success_restores_only_writers_stopped_by_this_run(migration):
    invoice_schema_repair.execute("plan.json", "protected.env")
    assert [c.args[0]["service"] for c in migration.control.call_args_list] == ["ark-backend", "CommissionSystem"]
    assert all(c.args[1] == "start" for c in migration.control.call_args_list)
    record = json.loads((migration.state / "migration-167-current.json").read_text())
    assert record["status"] == "succeeded"
    assert not (migration.state / "publish-success.json").exists()


@pytest.mark.parametrize("failure_stage", ["migrate", "verify"])
def test_ddl_or_verification_failure_does_not_restore_writers(migration, failure_stage):
    if failure_stage == "migrate":
        migration.migrate.side_effect = RuntimeError("DDL failed")
    else:
        schema_release.schema_check.side_effect = RuntimeError("version mismatch")
    with pytest.raises(RuntimeError):
        invoice_schema_repair.execute("plan.json", "protected.env")
    migration.control.assert_not_called()
    assert json.loads((migration.state / "migration-167-current.json").read_text())["status"] == "failed"


def test_restore_failure_still_attempts_other_stopped_writers(migration):
    migration.control.side_effect = [RuntimeError("start failed"), True]
    with pytest.raises(RuntimeError, match="restore"):
        invoice_schema_repair.execute("plan.json", "protected.env")
    assert migration.control.call_count == 2


def test_already_current_does_not_repeat_ddl(migration):
    migration.prepared["pending"] = []
    invoice_schema_repair.execute("plan.json", None)
    migration.migrate.assert_not_called()
    migration.control.assert_not_called()


def test_unreviewed_migration_bytes_are_rejected(tmp_path):
    folder = tmp_path / "backend" / "alembic" / "versions"
    folder.mkdir(parents=True)
    for name in invoice_schema_repair.MIGRATIONS:
        (folder / name).write_text("def upgrade(): pass\n")
    with pytest.raises(RuntimeError, match="reviewed"):
        invoice_schema_repair.check_migration_files(tmp_path)


def test_application_versions_are_pinned_on_both_servers(monkeypatch):
    plan = {"live_root": "D:/commission-system",
            "application_revisions": dict(invoice_schema_repair.COMPATIBLE_REVISIONS)}
    actual = [invoice_schema_repair.COMPATIBLE_REVISIONS["office"],
              invoice_schema_repair.COMPATIBLE_REVISIONS["beijing"]]
    runner = Mock(side_effect=actual)
    monkeypatch.setattr(publish, "run", runner)
    invoice_schema_repair.check_applications(plan)
    runner.side_effect = [actual[0], "b" * 40]
    with pytest.raises(RuntimeError, match="beijing"):
        invoice_schema_repair.check_applications(plan)


def test_health_checks_business_schema_on_both_backends(migration, monkeypatch):
    baseline = {
        "nssm:office:CommissionSystem": "running",
        "systemd:ubuntu@154.8.205.162:ark-backend": "running",
    }
    monkeypatch.setattr(invoice_schema_repair, "snapshot_writers", lambda *_: baseline)
    runner = Mock(return_value="")
    monkeypatch.setattr(publish, "run", runner)
    monkeypatch.setattr(invoice_schema_repair, "health", Mock())
    real_check_health(
        {"source": str(migration.state.parent)}, {"python": "candidate-python", "port": 8001}, baseline
    )
    commands = [str(call.args[0]) for call in runner.call_args_list]
    assert sum("lsordertest.user_rel_team" in command for command in commands) == 2


def test_failed_restore_preserves_original_baseline_on_rerun(migration):
    journal = migration.state / "migration-167-current.json"
    original = json.dumps({"status": "failed", "failed_phase": "restoring",
                           "writer_states_before": migration.baseline})
    journal.write_text(original)
    migration.prepared["pending"] = []
    migration.baseline = {k: "stopped" for k in migration.baseline}
    with pytest.raises(RuntimeError, match="Recovery required"):
        invoice_schema_repair.execute("plan.json", None)
    assert journal.read_text() == original
    migration.control.assert_not_called()
    migration.migrate.assert_not_called()


def test_success_closes_shared_schema_journal(migration):
    migration.prepared.update(schema=invoice_schema_repair.TARGET, schema_changed=True)
    journal = migration.state / "schema-writers.json"
    def migrated(*args):
        journal.write_text(json.dumps({"status": "upgraded", "schema": invoice_schema_repair.TARGET}))
        return [migration.writers[0], migration.writers[2]]
    migration.migrate.side_effect = migrated
    invoice_schema_repair.execute("plan.json", "protected.env")
    assert json.loads(journal.read_text())["status"] == "completed"


def test_already_current_preserves_unresolved_shared_journal(migration):
    migration.prepared["pending"] = []
    journal = migration.state / "schema-writers.json"
    original = json.dumps({"status": "failed-after-ddl", "schema": invoice_schema_repair.TARGET})
    journal.write_text(original)
    with pytest.raises(RuntimeError, match="inspection"):
        invoice_schema_repair.execute("plan.json", None)
    assert journal.read_text() == original
    migration.control.assert_not_called()
