"""Recover the inspected partial 166 DDL, then apply corrected 166 and 167."""

import json
from pathlib import Path

PARENT = "164_battle_posters"
TARGET = "167_invoice_merchandiser"
PENDING = ["166_presale_settlement", TARGET]
TAG = "invoice-166-collation"
CREATED = {
    "ark_shipment_settlements": {
        "id", "invoice_id", "sequence", "settlement_no", "state", "is_final",
        "quote", "quote_hash", "request_key", "request_hash", "version",
        "created_by", "created_at", "updated_at",
    },
    "ark_shipment_settlement_items": {
        "id", "settlement_id", "invoice_item_id", "quantity", "line_amount", "snapshot",
    },
    "ark_receivables": {
        "id", "invoice_id", "settlement_id", "business_key", "kind", "amount",
        "handling_amount", "currency", "customer_id", "remote_order_id",
        "remote_status", "created_at",
    },
    "ark_receipt_batches": {
        "id", "batch_no", "customer_id", "currency", "gross_amount",
        "bank_charge_total", "collection_date", "payment_type", "remark",
        "status", "request_key", "request_hash", "version", "created_by", "created_at",
    },
}
DROP_ORDER = [
    "ark_shipment_settlement_items", "ark_receivables",
    "ark_receipt_batches", "ark_shipment_settlements",
]
LATER = {
    "ark_receipt_batch_attachments", "ark_settlement_applications",
    "ark_shipment_outbounds", "ark_settlement_events",
}
FOREIGN_KEYS = {
    "ark_shipment_settlements": {("invoice_id", "ark_invoices", "id")},
    "ark_shipment_settlement_items": {
        ("invoice_item_id", "ark_invoice_items", "id"),
        ("settlement_id", "ark_shipment_settlements", "id"),
    },
    "ark_receivables": {
        ("invoice_id", "ark_invoices", "id"),
        ("settlement_id", "ark_shipment_settlements", "id"),
    },
    "ark_receipt_batches": set(),
}


def _canonical(items):
    return sorted(json.dumps(item, sort_keys=True) for item in items)


def read_record(path, writers):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    original = record.get("recovery_original", record)
    if (original.get("status") != "failed-after-ddl"
            or original.get("database") != PARENT
            or original.get("schema") != TARGET
            or original.get("pending") != PENDING):
        raise RuntimeError("Recovery does not match the inspected partial 166 migration")
    if record is not original and (record.get("recovery") != TAG
                                   or record.get("status") != "dropping-partial"):
        raise RuntimeError("Recovery journal is not resumable")
    baseline = original.get("writers", [])
    if (len(baseline) != 5 or any(entry.get("before") != "running" for entry in baseline)
            or _canonical([entry["writer"] for entry in baseline]) != _canonical(writers)
            or _canonical(original.get("stopped", [])) != _canonical(writers)):
        raise RuntimeError("Writer baseline or stop evidence differs from the incident")
    return record, original


def inspect_partial(connection, record):
    from sqlalchemy import inspect, text

    revision = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if revision != [PARENT]:
        raise RuntimeError("Database revision changed during recovery")
    inspector = inspect(connection)
    present = set(inspector.get_table_names())
    if present & LATER:
        raise RuntimeError("Later 166 tables exist; partial state needs separate inspection")
    remaining = [name for name in DROP_ORDER if name in present]
    dropped = record.get("dropped", [])
    expected = DROP_ORDER[len(dropped):]
    next_drop = record.get("next_drop")
    if (dropped != DROP_ORDER[:len(dropped)]
            or (next_drop and (not expected or next_drop != expected[0]))
            or remaining not in ([expected, expected[1:]] if next_drop else [expected])):
        raise RuntimeError("Partial table inventory differs from recorded drop progress")
    for name in remaining:
        if {column["name"] for column in inspector.get_columns(name)} != CREATED[name]:
            raise RuntimeError("Partial table columns differ: " + name)
        actual_fks = {
            (fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0])
            for fk in inspector.get_foreign_keys(name)
        }
        if actual_fks != FOREIGN_KEYS[name]:
            raise RuntimeError("Partial table foreign keys differ: " + name)
        if connection.execute(text("SELECT COUNT(*) FROM " + name)).scalar() != 0:
            raise RuntimeError("Partial table contains business data: " + name)
    inbound = connection.execute(text(
        "SELECT TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA='commission_db' AND REFERENCED_TABLE_SCHEMA='commission_db' "
        "AND REFERENCED_TABLE_NAME IN "
        "('ark_shipment_settlements','ark_shipment_settlement_items','ark_receivables','ark_receipt_batches') "
        "AND TABLE_NAME NOT IN "
        "('ark_shipment_settlements','ark_shipment_settlement_items','ark_receivables','ark_receipt_batches')"
    )).scalars().all()
    if inbound:
        raise RuntimeError("Unexpected inbound foreign key references a partial table")
    receipt_columns = {column["name"]: column for column in inspector.get_columns("ark_receipts")}
    if ({"batch_id", "receivable_id", "purpose"} & receipt_columns.keys()
            or receipt_columns["xiaoman_order_id"]["nullable"]):
        raise RuntimeError("Receipt schema already has later 166 changes")
    invoice_columns = {column["name"] for column in inspector.get_columns("ark_invoices")}
    if {"merchandiser_id", "merchandiser_name"} & invoice_columns:
        raise RuntimeError("Invoice schema already has 167 columns")
    parent_collation = connection.execute(text(
        "SELECT COLLATION_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA='commission_db' AND TABLE_NAME='ark_receipt_attachments' "
        "AND COLUMN_NAME='id'"
    )).scalar()
    if parent_collation != "utf8mb4_0900_ai_ci":
        raise RuntimeError("Attachment ID collation differs from the corrected migration")
    return remaining


def execute(request, connection, settings):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    import app.core.config as config_module
    from publish import atomic_json
    from schema_release import writer_state

    journal = Path(request["journal_path"])
    record, original = read_record(journal, request["writers"])
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    if (script.get_heads() != [TARGET]
            or script.get_revision("166_presale_settlement").down_revision != PARENT
            or script.get_revision(TARGET).down_revision != "166_presale_settlement"
            or request["schema"] != TARGET or request["pending"] != PENDING):
        raise RuntimeError("Recovery candidate chain differs from the inspected 164 to 167 path")
    inspect_partial(connection, record)
    if any(writer_state(writer, request["nssm"]) != "stopped" for writer in request["writers"]):
        raise RuntimeError("Every recorded writer must remain stopped")
    if request["action"] == "check":
        return {"status": "recovery-ready", "schema": TARGET}
    if request["action"] != "apply":
        raise RuntimeError("Unsupported recovery action")
    if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
        raise RuntimeError("Another database release owns the lock")
    try:
        record, original = read_record(journal, request["writers"])
        inspect_partial(connection, record)
        if any(writer_state(writer, request["nssm"]) != "stopped" for writer in request["writers"]):
            raise RuntimeError("Writer changed state before recovery DDL")
        if record is original:
            record = {**record, "recovery": TAG, "recovery_original": original,
                      "status": "dropping-partial", "dropped": []}
            atomic_json(journal, record)
        if record.get("next_drop") and record["next_drop"] not in inspect_partial(connection, record):
            record["dropped"].append(record.pop("next_drop"))
            atomic_json(journal, record)
        for name in DROP_ORDER[len(record["dropped"]):]:
            inspect_partial(connection, record)
            record["next_drop"] = name
            atomic_json(journal, record)
            connection.execute(text("DROP TABLE " + name))
            connection.commit()
            record["dropped"].append(name)
            record.pop("next_drop")
            atomic_json(journal, record)
        inspect_partial(connection, record)
        record["status"] = "running-ddl"
        atomic_json(journal, record)
        previous_settings = config_module.get_settings
        try:
            config_module.get_settings = lambda: settings
            command.upgrade(config, TARGET)
        finally:
            config_module.get_settings = previous_settings
        connection.commit()
        if list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) != [TARGET]:
            raise RuntimeError("Recovery did not reach invoice revision 167")
        record["status"] = "upgraded"
        atomic_json(journal, record)
        return {"schema": TARGET, "stopped": [entry["writer"] for entry in original["writers"]]}
    except Exception:
        # DDL may have committed. Leave every writer stopped and preserve the journal.
        raise
    finally:
        connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
