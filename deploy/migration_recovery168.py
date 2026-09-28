"""Recover only the 2026-09-25 mixed-collation migration 168 incident."""
import hashlib
import json
from pathlib import Path

PREVIOUS = "167_invoice_merchandiser"
NEW = "168_customer_media_customer_tags"
CHAIN = [NEW]
TAG = "migration-168-collation"
FAILED_REVISION = "284c399b41b2570d91b778ad0a0c114eaa1fecc0"
RELEASE_ID = "ed95cba16bf44357bbc6f08a9662011b"
TABLE = "ark_customer_media_customer_tags"


def canonical(rows):
    return sorted(json.dumps(row, sort_keys=True) for row in rows)


def read_record(path, writers=None):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    original = record.get("recovery_original", record)
    if (original.get("status") != "failed-after-ddl" or original.get("schema") != NEW
            or original.get("database") != PREVIOUS or original.get("pending") != CHAIN):
        raise RuntimeError("Recovery 168 does not match the original failed migration")
    if record is not original and (record.get("recovery") != TAG or record.get("status") not in {
            "stopping", "running-ddl", "failed-after-ddl", "upgraded", "completed"}):
        raise RuntimeError("Recovery 168 journal is not resumable")
    baseline = original.get("writers", [])
    expected = {("office", "nssm", "CommissionSystem"): "running",
                ("office", "nssm", "WhatsAppConnector"): "running",
                ("ubuntu@154.8.205.162", "systemd", "ark-backend"): "running",
                ("root@119.28.107.92", "pm2", "shipment-tracking-mcp"): "running",
                ("root@119.28.107.92", "systemd_timer", "ark-okki-outbound-poller"): "stopped"}
    actual = {(e["writer"].get("host"), e["writer"].get("kind"), e["writer"].get("service")): e.get("before") for e in baseline}
    if len(baseline) != 5 or actual != expected:
        raise RuntimeError("Recovery 168 writer baseline differs")
    if canonical(original.get("stopped", [])) != canonical([e["writer"] for e in baseline if e["before"] == "running"]):
        raise RuntimeError("Recovery 168 original stop evidence is incomplete")
    if writers is not None and canonical(writers) != canonical([e["writer"] for e in baseline]):
        raise RuntimeError("Recovery 168 current writer inventory differs")
    return record, original


def validate_existing(connection):
    from sqlalchemy import inspect, text
    inspector = inspect(connection)
    columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
    expected = {"customer_id", "dimension_id", "tag_value_id", "created_by", "created_at"}
    if set(columns) != expected:
        raise RuntimeError("Recovery 168 target columns differ")
    for name in ("dimension_id", "tag_value_id", "created_by"):
        col = columns[name]
        if col["type"].__class__.__name__ != "INTEGER" or not getattr(col["type"], "unsigned", False) or col["nullable"] != (name == "created_by"):
            raise RuntimeError("Recovery 168 target integer type/nullability differs")
    if (columns["customer_id"]["type"].__class__.__name__ != "VARCHAR"
            or getattr(columns["customer_id"]["type"], "length", None) != 64
            or columns["customer_id"]["nullable"] or columns["created_at"]["nullable"]
            or columns["created_at"]["type"].__class__.__name__ != "DATETIME"):
        raise RuntimeError("Recovery 168 target customer/time columns differ")
    if inspector.get_pk_constraint(TABLE)["constrained_columns"] != ["customer_id", "dimension_id", "tag_value_id"]:
        raise RuntimeError("Recovery 168 target primary key differs")
    fks = inspector.get_foreign_keys(TABLE)
    expected_fks = {("dimension_id", "ark_tag_dimensions"), ("tag_value_id", "ark_tag_values"), ("created_by", "ark_users")}
    actual_fks = {(f["constrained_columns"][0], f["referred_table"]) for f in fks
                  if len(f["constrained_columns"]) == 1 and f["referred_columns"] == ["id"] and not f.get("options")}
    if len(fks) != 3 or actual_fks != expected_fks:
        raise RuntimeError("Recovery 168 target foreign keys differ")
    if not any(i["name"] == "idx_customer_media_customer_tag_value" and not i["unique"]
               and i["column_names"] == ["tag_value_id", "customer_id"] for i in inspector.get_indexes(TABLE)):
        raise RuntimeError("Recovery 168 target index is missing")
    rows = dict(connection.execute(text("SELECT TABLE_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND COLUMN_NAME='customer_id' AND TABLE_NAME IN ('ark_customer_media_customer_tags','ark_customer_media_batches')")).all())
    if rows != {TABLE: "utf8mb4_0900_ai_ci", "ark_customer_media_batches": "utf8mb4_unicode_ci"}:
        raise RuntimeError("Recovery 168 collation evidence changed")


def inspect_database(connection, request):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if (script.get_heads() != [NEW] or request["schema"] != NEW
            or len(current) != 1 or current[0] not in {PREVIOUS, NEW}
            or script.get_revision(NEW).down_revision != PREVIOUS):
        raise RuntimeError("Recovery 168 requires database 167/168 and code head 168")
    if request["pending"] != ([NEW] if current == [PREVIOUS] else []):
        raise RuntimeError("Recovery 168 database changed since preparation")
    validate_existing(connection)
    if current == [PREVIOUS] and connection.execute(text("SELECT COUNT(*) FROM " + TABLE)).scalar() != 0:
        raise RuntimeError("Recovery 168 requires the inspected empty partial table")
    if current == [NEW]:
        missing = connection.execute(text("""
            SELECT COUNT(*) FROM ark_customer_media_asset_tags t
            JOIN ark_customer_media_assets a ON a.id=t.asset_id
            JOIN ark_customer_media_batches b ON b.id=a.batch_id
            LEFT JOIN ark_customer_media_customer_tags existing
              ON existing.customer_id COLLATE utf8mb4_unicode_ci = b.customer_id COLLATE utf8mb4_unicode_ci
             AND existing.dimension_id=t.dimension_id AND existing.tag_value_id=t.tag_value_id
            WHERE a.deleted_at IS NULL AND existing.customer_id IS NULL
        """)).scalar()
        if missing != 0:
            raise RuntimeError("Recovery 168 completed revision has missing backfill rows")
    return config, current


def prepare_release(state, source, revision, journal):
    """Retain the existing outbound transaction; never rewrite its frozen lease."""
    from publish import atomic_json, run
    from okki_outbound_release import artifact
    archive = Path(state) / "recovery-168-original-publish.json"
    original = json.loads(archive.read_text()) if archive.exists() else journal
    if (original.get("revision") != FAILED_REVISION or original.get("release_id") != RELEASE_ID
            or original.get("scope") != "office-and-cloud" or original.get("status") != "failed"
            or original.get("completed") != [] or original.get("outbound", {}).get("status") != "frozen"
            or original["outbound"].get("schedule") != {"active": True, "enabled": True}):
        raise RuntimeError("Recovery 168 original publish evidence differs")
    if archive.exists() and journal.get("revision") not in {FAILED_REVISION, revision}:
        raise RuntimeError("Recovery 168 candidate changed since preparation")
    if journal.get("release_id") != RELEASE_ID or journal.get("status") == "succeeded":
        raise RuntimeError("Recovery 168 release is not resumable")
    run(["git", "merge-base", "--is-ancestor", FAILED_REVISION, revision], cwd=source, capture=True)
    changed = run(["git", "diff", "--name-only", FAILED_REVISION, revision], cwd=source, capture=True).splitlines()
    exact = {"backend/alembic/versions/168_customer_media_customer_tags.py", "backend/tests/test_customer_media_customer_tags_migration.py", "docs/handoff.md"}
    if any(name not in exact and not name.startswith(("deploy/", "docs/reports/")) for name in changed):
        raise RuntimeError("Recovery 168 includes unrelated application changes")
    files = artifact(Path(source) / "deploy")
    digest = hashlib.sha256(json.dumps({n: v["sha256"] for n,v in sorted(files.items())}).encode()).hexdigest()
    if digest != original["outbound"]["digest"]:
        raise RuntimeError("Recovery 168 outbound artifact changed")
    if not archive.exists():
        atomic_json(archive, original)
    return original


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
        raise RuntimeError("Recovery 168 requires check or apply action")
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
            raise RuntimeError("Recovery 168 requires every registered writer to be stopped")
        record["status"] = "running-ddl"
        atomic_json(path, record)
        previous_settings = config_module.get_settings
        try:
            config_module.get_settings = lambda: settings
            if current == [PREVIOUS]:
                command.upgrade(alembic, NEW)
        finally:
            config_module.get_settings = previous_settings
        connection.commit()
        if list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) != [NEW]:
            raise RuntimeError("Recovery 168 revision verification failed")
        inspect_database(connection, {**request, "pending": []})
        record["status"] = "upgraded"
        atomic_json(path, record)
        return {"schema": NEW, "stopped": original["stopped"]}
    except Exception as error:
        if record.get("recovery") == TAG:
            record.update(status="failed-after-ddl", error_type=type(error).__name__)
            atomic_json(path, record)
        # No rollback/start: the original incident already crossed MySQL DDL.
        raise
    finally:
        connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
