"""Whitelisted SQL values for merged outbound sorting before pagination."""
from sqlalchemy import literal_column

from app.shipping_inspection import outbound_service as records, record_query_service

QUEUE_SORT_FIELDS = frozenset(("outbound_no", "order_id", "customer_name", "outbound_date",
                               "item_count", "outbound_state", "status", "photo_count"))


def _json(db, expression, path):
    value = f"JSON_EXTRACT({expression}, '{path}')"
    return f"NULLIF(JSON_UNQUOTE({value}), 'null')" if db.get_bind().dialect.name == "mysql" else value


def mirror_sort_value(db, field, rm, im, link, schema):
    rid = f"CAST(r.`{rm['id']}` AS CHAR)"
    if db.get_bind().dialect.name == "mysql":
        rid += " COLLATE utf8mb4_unicode_ci"
    inspection = f"FROM ark_shipping_inspections si WHERE si.outbound_record_id={rid}"
    if field == "status":
        return f"COALESCE((SELECT si.status {inspection}), 'none')"
    if field == "photo_count":
        return f"COALESCE((SELECT CASE WHEN si.status='draft' THEN (SELECT COUNT(*) FROM ark_shipping_inspection_photos p WHERE p.inspection_id=si.id AND p.media_type='image') ELSE si.photo_count END {inspection}), 0)"
    if field == "outbound_state":
        return "'ready'"
    if field in ("customer_name", "outbound_date"):
        return records._col(rm, field, "r")
    if link:
        ik, rk = (im["invoice_id"], rm["invoice_id"]) if link == "invoice" else (im["record_id"], rm["id"])
        item_from = f"FROM `{schema}`.`{records.ITEMS_TABLE}` i WHERE i.`{ik}`=r.`{rk}`"
    else:
        item_from = None
    if field == "order_id":
        return f"(SELECT MIN(CAST(i.order_id AS CHAR)) {item_from})" if item_from and 'order_id' in records._table_columns(db, records.ITEMS_TABLE) else "NULL"
    if field not in ("outbound_no", "item_count"):
        return "NULL"
    # apply_header shows a verified snapshot while the business mirror catches up.
    # At equal timestamps an identical snapshot gives the same header/count;
    # a different snapshot remains visible, so <= matches either case.
    event_from = f"FROM ark_shipping_operation_events e WHERE e.scope='outbound-invoice-sync' AND e.request_id={rid}"
    snapshot_time = f"(SELECT {_json(db, 'e.result', '$.verified.update_time')} {event_from})"
    mirror_time = records._col(rm, "updated_at", "r")
    eligible = f"({snapshot_time} IS NOT NULL AND ({mirror_time} IS NULL OR {mirror_time}<={snapshot_time}))"
    if field == "outbound_no":
        serial = f"(SELECT {_json(db, 'e.result', '$.verified.serial_id')} {event_from})"
        base = records._col(rm, "outbound_no", "r")
        return f"CASE WHEN {eligible} THEN COALESCE(NULLIF({serial}, ''), {base}) ELSE {base} END"
    count_fn = "JSON_LENGTH" if db.get_bind().dialect.name == "mysql" else "JSON_ARRAY_LENGTH"
    count = f"(SELECT {count_fn}(JSON_EXTRACT(e.result, '$.verified.items')) {event_from})"
    base = f"(SELECT COUNT(*) {item_from})" if item_from else "0"
    return f"CASE WHEN {eligible} THEN COALESCE({count}, 0) ELSE {base} END"


def local_sort_value(field):
    return {
        "outbound_no": "f.invoice_no", "order_id": "CAST(t.order_id AS CHAR)",
        "customer_name": "f.customer_name", "outbound_date": "DATE(t.created_at)",
        "item_count": "(SELECT COUNT(*) FROM ark_invoice_items i WHERE i.invoice_id=f.id)",
        "outbound_state": "CASE WHEN t.status IN ('done','skipped') THEN 'awaiting_sync' ELSE t.status END",
        "status": "NULL", "photo_count": "NULL",
    }.get(field, "NULL")


def inspection_link_sort_values(db):
    """Read exact item associations; never infer a salesperson from API creator."""
    link, rm, im = records._link(db)
    outer = "ark_shipping_inspections.outbound_record_id"
    if not link:
        return {"order_id": literal_column("NULL"), "salesperson_name": literal_column("NULL")}
    ik, rk = (im["invoice_id"], rm["invoice_id"]) if link == "invoice" else (im["record_id"], rm["id"])
    schema = records._schema()
    item_from = f"FROM `{schema}`.`{records.RECORDS_TABLE}` r JOIN `{schema}`.`{records.ITEMS_TABLE}` i ON i.`{ik}`=r.`{rk}` WHERE r.`{rm['id']}`={outer}"
    order = f"(SELECT MIN(CAST(i.order_id AS CHAR)) {item_from})" if 'order_id' in records._table_columns(db, records.ITEMS_TABLE) else "NULL"
    source = record_query_service._source(db)
    if source is None:
        return {"order_id": literal_column(order), "salesperson_name": literal_column("NULL")}
    _, joins = source
    display = "COALESCE(NULLIF(TRIM(u.full_name), ''), NULLIF(TRIM(u.nickname), ''))"
    local = "NULLIF(TRIM(a.real_name), '')"
    if db.get_bind().dialect.name == "mysql":
        combined = f"CONCAT({display}, '（', {local}, '）')"
    else:
        combined = f"({display} || '（' || {local} || '）')"
    label = f"CASE WHEN {display} IS NOT NULL AND {local} IS NOT NULL AND {display}<>{local} THEN {combined} ELSE COALESCE({display}, {local}) END"
    sales = f"(SELECT MIN({label}) {joins} WHERE r.`{rm['id']}`={outer})"
    return {"order_id": literal_column(order), "salesperson_name": literal_column(sales)}
