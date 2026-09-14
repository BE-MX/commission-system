"""Explicit recovery for the inspected 149 revision overflow; never discard the writer baseline."""

import importlib.util
import json
from pathlib import Path

OLD = "149_domestic_order_review_columns"
NEW = "149_dom_order_review_columns"
PREVIOUS = "148_domestic_customer_requests"
TAG = "revision-149-overflow"


def read_record(path, writers=None):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    original = record.get("recovery_original", record)
    if (original.get("status") != "failed-after-ddl" or original.get("schema") != OLD
            or original.get("database") != "147_customer_media_directories"
            or original.get("pending") != [PREVIOUS, OLD]):
        raise RuntimeError("Recovery 149 does not match the original failed migration")
    if record is not original and (record.get("recovery") != TAG or record.get("status") not in {
            "stopping", "running-ddl", "failed-after-ddl", "upgraded"}):
        raise RuntimeError("Recovery 149 journal is not resumable")
    baseline = original.get("writers", [])
    expected = {("office", "nssm", "CommissionSystem"), ("office", "nssm", "WhatsAppConnector"),
                ("ubuntu@154.8.205.162", "systemd", "ark-backend"),
                ("root@119.28.107.92", "pm2", "shipment-tracking-mcp")}
    keys = [(e["writer"].get("host"), e["writer"].get("kind"), e["writer"].get("service")) for e in baseline]
    if len(keys) != 4 or set(keys) != expected or any(e.get("before") != "running" for e in baseline):
        raise RuntimeError("Recovery 149 writer baseline differs from the inspected incident")
    original_writers = [e["writer"] for e in baseline]
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    if canonical(original.get("stopped", [])) != canonical(original_writers):
        raise RuntimeError("Recovery 149 original stop evidence is incomplete")
    if writers is not None and canonical(writers) != canonical(original_writers):
        raise RuntimeError("Recovery 149 current writer inventory differs from the original baseline")
    return record, original


def inspect_database(connection, request):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if script.get_heads() != [NEW] or request["schema"] != NEW or current not in [[PREVIOUS], [NEW]]:
        raise RuntimeError("Recovery 149 requires database 148/149 and the corrected 149 code head")
    pending = [NEW] if current == [PREVIOUS] else []
    if request["pending"] != pending:
        raise RuntimeError("Recovery 149 database changed since preparation")
    revision = script.get_revision(NEW)
    spec = importlib.util.spec_from_file_location("recovery149_migration", revision.path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.validate_existing(connection, require_complete=current == [NEW])
    return config, current


def execute(request, connection, settings):
    from sqlalchemy import text
    from alembic import command
    import app.core.config as config_module
    from publish import atomic_json
    from schema_release import control, writer_state

    path = Path(request["journal_path"])
    record, original = read_record(path, request["writers"])
    if request["action"] == "check":
        inspect_database(connection, request)
        for writer in request["writers"]:
            writer_state(writer, request["nssm"])
        return {"status": "recovery-ready", "schema": NEW}
    if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
        raise RuntimeError("Another database release owns the lock")
    try:
        # Re-read the persisted incident under the release lock; preserve it intact.
        record, original = read_record(path, request["writers"])
        alembic, current = inspect_database(connection, request)
        record = {**record, "recovery": TAG, "recovery_original": original,
                  "schema": NEW, "status": "stopping"}
        atomic_json(path, record)
        for writer in request["writers"]:
            control(writer, "stop", request["nssm"])
        if any(writer_state(w, request["nssm"]) != "stopped" for w in request["writers"]):
            raise RuntimeError("Recovery 149 requires every registered writer to be stopped")
        record["status"] = "running-ddl"
        atomic_json(path, record)
        config_module.get_settings = lambda: settings
        command.upgrade(alembic, NEW)
        connection.commit()
        if list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) != [NEW]:
            raise RuntimeError("Recovery 149 revision verification failed")
        inspect_database(connection, {**request, "pending": []})
        record["status"] = "upgraded"
        atomic_json(path, record)
        return {"schema": NEW, "stopped": [entry["writer"] for entry in original["writers"]]}
    except Exception as error:
        if record.get("recovery") == TAG:
            record.update(status="failed-after-ddl", error_type=type(error).__name__)
            atomic_json(path, record)
        # The incident already crossed DDL; never restart old applications here.
        raise
    finally:
        connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
