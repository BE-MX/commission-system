"""Migration-only release safety; no real services or database connections."""

from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migration_only
import publish
import schema_release


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
                "pending": [migration_only.TARGET], "events": ["existing_event"]}
    baseline = {migration_only.writer_key(w): "running" for w in writers}
    baseline[migration_only.writer_key(writers[1])] = "stopped"
    monkeypatch.setattr(migration_only, "load_plan", lambda *_: (plan, source, prepared))
    monkeypatch.setattr(migration_only, "check_applications", Mock())
    monkeypatch.setattr(migration_only, "snapshot_writers", lambda *_: dict(baseline))
    health = Mock()
    monkeypatch.setattr(migration_only, "check_health", health)
    monkeypatch.setattr(publish, "deployment_lock", nullcontext)
    monkeypatch.setattr(schema_release, "preflight", Mock())
    migrate = Mock(return_value=[writers[0], writers[2]])
    monkeypatch.setattr(schema_release, "migrate", migrate)
    monkeypatch.setattr(schema_release, "database_lock", lambda *_: nullcontext())
    monkeypatch.setattr(schema_release, "schema_check", Mock(return_value={"schema": migration_only.TARGET, "database": migration_only.TARGET, "pending": []}))
    control = Mock(return_value=True)
    monkeypatch.setattr(schema_release, "control", control)
    monkeypatch.setattr(publish, "ROOT", source)
    monkeypatch.setattr(publish, "STATE", state)
    monkeypatch.setattr(schema_release, "STATE", state)
    return SimpleNamespace(plan=plan, writers=writers, prepared=prepared, baseline=baseline,
                           state=state, migrate=migrate, control=control, health=health)


def test_prepare_only_does_not_stop_or_migrate(migration):
    migration_only.execute("plan.json", "protected.env", prepare_only=True)
    migration.migrate.assert_not_called()
    migration.control.assert_not_called()
    assert json.loads((migration.state / "migration-138-current.json").read_text())["status"] == "prepared"


def test_success_restores_only_writers_stopped_by_this_run(migration):
    migration_only.execute("plan.json", "protected.env")
    assert [c.args[0]["service"] for c in migration.control.call_args_list] == ["ark-backend", "CommissionSystem"]
    assert all(c.args[1] == "start" for c in migration.control.call_args_list)
    record = json.loads((migration.state / "migration-138-current.json").read_text())
    assert record["status"] == "succeeded"
    assert not (migration.state / "publish-success.json").exists()


@pytest.mark.parametrize("failure_stage", ["migrate", "verify"])
def test_ddl_or_verification_failure_does_not_restore_writers(migration, failure_stage):
    if failure_stage == "migrate":
        migration.migrate.side_effect = RuntimeError("DDL failed")
    else:
        schema_release.schema_check.side_effect = RuntimeError("version mismatch")
    with pytest.raises(RuntimeError):
        migration_only.execute("plan.json", "protected.env")
    migration.control.assert_not_called()
    assert json.loads((migration.state / "migration-138-current.json").read_text())["status"] == "failed"


def test_restore_failure_still_attempts_other_stopped_writers(migration):
    migration.control.side_effect = [RuntimeError("start failed"), True]
    with pytest.raises(RuntimeError, match="restore"):
        migration_only.execute("plan.json", "protected.env")
    assert migration.control.call_count == 2


def test_already_current_does_not_repeat_ddl(migration):
    migration.prepared["pending"] = []
    migration_only.execute("plan.json", None)
    migration.migrate.assert_not_called()
    migration.control.assert_not_called()


def test_unreviewed_migration_bytes_are_rejected(tmp_path):
    script = tmp_path / "138_public_pool_rules.py"
    script.write_text("def upgrade(): pass\n")
    with pytest.raises(RuntimeError, match="reviewed"):
        migration_only.check_migration_file(script)


def test_failed_restore_preserves_original_baseline_on_rerun(migration):
    journal = migration.state / "migration-138-current.json"
    original = json.dumps({"status": "failed", "failed_phase": "restoring",
                           "writer_states_before": migration.baseline})
    journal.write_text(original)
    migration.prepared["pending"] = []
    migration.baseline = {k: "stopped" for k in migration.baseline}
    with pytest.raises(RuntimeError, match="Recovery required"):
        migration_only.execute("plan.json", None)
    assert journal.read_text() == original
    migration.control.assert_not_called()
    migration.migrate.assert_not_called()


def test_success_closes_shared_schema_journal(migration):
    migration.prepared.update(schema=migration_only.TARGET, schema_changed=True)
    journal = migration.state / "schema-writers.json"
    def migrated(*args):
        journal.write_text(json.dumps({"status": "upgraded", "schema": migration_only.TARGET}))
        return [migration.writers[0], migration.writers[2]]
    migration.migrate.side_effect = migrated
    migration_only.execute("plan.json", "protected.env")
    assert json.loads(journal.read_text())["status"] == "completed"


def test_already_current_preserves_unresolved_shared_journal(migration):
    migration.prepared["pending"] = []
    journal = migration.state / "schema-writers.json"
    original = json.dumps({"status": "failed-after-ddl", "schema": migration_only.TARGET})
    journal.write_text(original)
    with pytest.raises(RuntimeError, match="inspection"):
        migration_only.execute("plan.json", None)
    assert journal.read_text() == original
    migration.control.assert_not_called()
