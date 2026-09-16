"""Recover the inspected customer-tag FK incident, preserving its writer baseline."""

import importlib.util
import json
from pathlib import Path

PREVIOUS = "152_shipping_media_recall"
CHAIN = ["151_customer_media_tags", "153_shipping_station", "154_okki_outbound_tasks"]
NEW = CHAIN[-1]
TAG = "migration-151-unsigned-fk"


def read_record(path, writers=None):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    original = record.get("recovery_original", record)
    if (original.get("status") != "failed-after-ddl" or original.get("schema") != NEW
            or original.get("database") != PREVIOUS or original.get("pending") != CHAIN):
        raise RuntimeError("Recovery 151 does not match the original failed migration")
    if record is not original and (record.get("recovery") != TAG or record.get("status") not in {
            "stopping", "running-ddl", "failed-after-ddl", "upgraded"}):
        raise RuntimeError("Recovery 151 journal is not resumable")
    baseline = original.get("writers", [])
    expected = {("office", "nssm", "CommissionSystem"), ("office", "nssm", "WhatsAppConnector"),
                ("ubuntu@154.8.205.162", "systemd", "ark-backend"),
                ("root@119.28.107.92", "pm2", "shipment-tracking-mcp")}
    keys = [(e["writer"].get("host"), e["writer"].get("kind"), e["writer"].get("service")) for e in baseline]
    if len(keys) != 4 or set(keys) != expected or any(e.get("before") != "running" for e in baseline):
        raise RuntimeError("Recovery 151 writer baseline differs from the inspected incident")
    original_writers = [e["writer"] for e in baseline]
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    if canonical(original.get("stopped", [])) != canonical(original_writers):
        raise RuntimeError("Recovery 151 original stop evidence is incomplete")
    if writers is not None and canonical(writers) != canonical(original_writers):
        raise RuntimeError("Recovery 151 current writer inventory differs from the original baseline")
    return record, original


def _migration(script, revision):
    spec = importlib.util.spec_from_file_location("recovery151_" + revision, script.get_revision(revision).path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def validate_existing(connection, script, current):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    tag_migration = _migration(script, CHAIN[0])
    tag_migration._check_existing(inspector)
    if current != PREVIOUS:
        if ("tag_scope" not in {c["name"] for c in inspector.get_columns("ark_tag_dimensions")}
                or "idx_tag_dim_scope" not in {i["name"] for i in inspector.get_indexes("ark_tag_dimensions")}
                or "ark_customer_media_asset_tags" not in tables):
            raise RuntimeError("Recovery 151 completed revision has incomplete customer tag structures")
        seed = connection.execute(text(
            "SELECT tag_scope FROM ark_tag_dimensions WHERE name = :name"
        ), {"name": tag_migration.SEED_DIMENSION_NAME}).scalars().all()
        if seed != ["customer"]:
            raise RuntimeError("Recovery 151 completed revision has an invalid customer tag seed")

    station = {"ark_shipping_station_sessions", "ark_shipping_operation_events"}
    present = station & tables
    if present and present != station:
        raise RuntimeError("Recovery 151 found partial shipping station tables; inspect before retrying")
    if current in CHAIN[1:] or present:
        with Operations.context(MigrationContext.configure(connection)):
            _migration(script, CHAIN[1]).validate_schema()
        indexes = inspector.get_indexes("ark_shipping_operation_events")
        if not any(i["name"] == "idx_shipping_event_outbound" and not i["unique"]
                   and i["column_names"] == ["outbound_record_id", "id"] for i in indexes):
            raise RuntimeError("Recovery 151 shipping event index is incomplete")
    if current == NEW or "ark_okki_outbound_tasks" in tables:
        with Operations.context(MigrationContext.configure(connection)):
            _migration(script, NEW).validate_schema()
        indexes = inspector.get_indexes("ark_okki_outbound_tasks")
        if not any(i["name"] == "idx_okki_outbound_task_status" and not i["unique"]
                   and i["column_names"] == ["status", "id"] for i in indexes):
            raise RuntimeError("Recovery 151 outbound task index is incomplete")
        if not any(fk["constrained_columns"] == ["invoice_id"] and fk["referred_table"] == "ark_invoices"
                   and fk["referred_columns"] == ["id"]
                   and fk.get("options", {}).get("ondelete", "").upper() == "CASCADE"
                   for fk in inspector.get_foreign_keys("ark_okki_outbound_tasks")):
            raise RuntimeError("Recovery 151 outbound task foreign key is incomplete")


def inspect_database(connection, request):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    revisions = [PREVIOUS, *CHAIN]
    if (script.get_heads() != [NEW] or request["schema"] != NEW
            or len(current) != 1 or current[0] not in revisions):
        raise RuntimeError("Recovery 151 requires database 152/151/153/154 and code head 154")
    for parent, revision in zip(revisions, CHAIN):
        if script.get_revision(revision).down_revision != parent:
            raise RuntimeError("Recovery 151 candidate migration chain differs from the inspected incident")
    pending = revisions[revisions.index(current[0]) + 1:]
    if request["pending"] != pending:
        raise RuntimeError("Recovery 151 database changed since preparation")
    validate_existing(connection, script, current[0])
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
    if request["action"] != "apply":
        raise RuntimeError("Recovery 151 requires check or apply action")
    if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
        raise RuntimeError("Another database release owns the lock")
    try:
        record, original = read_record(path, request["writers"])
        alembic, current = inspect_database(connection, request)
        record = {**record, "recovery": TAG, "recovery_original": original,
                  "schema": NEW, "status": "stopping"}
        atomic_json(path, record)
        for writer in request["writers"]:
            control(writer, "stop", request["nssm"])
        if any(writer_state(w, request["nssm"]) != "stopped" for w in request["writers"]):
            raise RuntimeError("Recovery 151 requires every registered writer to be stopped")
        record["status"] = "running-ddl"
        atomic_json(path, record)
        previous_settings = config_module.get_settings
        try:
            config_module.get_settings = lambda: settings
            command.upgrade(alembic, NEW)
        finally:
            config_module.get_settings = previous_settings
        connection.commit()
        if list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) != [NEW]:
            raise RuntimeError("Recovery 151 revision verification failed")
        inspect_database(connection, {**request, "pending": []})
        record["status"] = "upgraded"
        atomic_json(path, record)
        return {"schema": NEW, "stopped": [entry["writer"] for entry in original["writers"]]}
    except Exception as error:
        if record.get("recovery") == TAG:
            record.update(status="failed-after-ddl", error_type=type(error).__name__)
            atomic_json(path, record)
        # No rollback/start: the original incident already crossed MySQL DDL.
        raise
    finally:
        connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
