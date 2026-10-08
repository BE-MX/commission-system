"""Read-only local outbound previews, replaced by mirrored OKKI records on arrival."""
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import bindparam, text

from app.shipping_inspection import outbound_service as records
from app.shipping_inspection.list_sort_service import QUEUE_SORT_FIELDS, mirror_sort_value, local_sort_value, local_retry_at


def _queue_query(db, *, keyword, order_id, date_from, date_to, okki_user_id, sort_field=None,
                 outbound_state=None, inspection_status=None):
    rm = records._record_columns(db)
    schema = records._schema()
    clauses, params = records.record_list_filters(
        db, rm, keyword=keyword, order_id=order_id, date_from=date_from, date_to=date_to, okki_user_id=okki_user_id,
    )
    local_clauses = [
        "t.order_id = f.xiaoman_order_id",
        "(t.status IN ('pending','running','waiting_stock','done','failed','uncertain') "
        "OR (t.status='skipped' AND t.reason LIKE 'existing:%'))",
    ]
    if okki_user_id:
        local_clauses.append("""EXISTS (SELECT 1 FROM ark_user_external_bindings b
            WHERE b.ark_user_id=f.sales_user_id AND b.provider='okki'
              AND b.binding_status='active' AND b.deleted_at IS NULL
              AND b.external_account_id=:scope_okki_user_id)""")
    if keyword:
        local_clauses.append("(f.invoice_no LIKE :kw OR f.customer_name LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if order_id:
        local_clauses.append("t.order_id=:order_id")
        params["order_id"] = order_id
    if date_from:
        local_clauses.append("t.created_at >= :date_from")
        params["date_from"] = date_from.isoformat()
    if date_to:
        local_clauses.append("t.created_at < :date_to_next")
        params["date_to_next"] = (date_to + timedelta(days=1)).isoformat()

    # A header may sync before its items. Exact invoice number + customer suppresses
    # that transient duplicate; otherwise actual item order linkage is authoritative.
    dedup_clauses = []
    mysql = db.get_bind().dialect.name == "mysql"
    visible = f" AND {records._owner_scope_clause(db, rm)}" if okki_user_id else ""
    if rm.get("outbound_no") and rm.get("company_id"):
        number = f"r.`{rm['outbound_no']}`"
        if mysql:
            number += " COLLATE utf8mb4_unicode_ci"
        dedup_clauses.append(f"""NOT EXISTS (SELECT 1 FROM `{schema}`.`{records.RECORDS_TABLE}` r
            WHERE {number}=f.invoice_no AND r.`{rm['company_id']}`=f.customer_id{visible})""")
    link, _, im = records._link(db)
    # Match the same state expressions used for display/sorting, before COUNT/LIMIT.
    if outbound_state:
        clauses.append("'ready' = :outbound_state")
        local_clauses.append(f"({local_sort_value('outbound_state', db)}) = :outbound_state")
        params['outbound_state'] = outbound_state
    if inspection_status:
        status_value = mirror_sort_value(db, 'status', rm, im, link, schema)
        clauses.append(f"({status_value}) = :inspection_status")
        params['inspection_status'] = inspection_status
        # Local tasks display an em dash, not an uninspected outbound document.
        local_clauses.append('1=0')
    mirror_where = "WHERE " + " AND ".join(clauses) if clauses else ""
    if link and "order_id" in records._table_columns(db, records.ITEMS_TABLE):
        ik = im["invoice_id"] if link == "invoice" else im["record_id"]
        rk = rm["invoice_id"] if link == "invoice" else rm["id"]
        # Start from the indexed order_id, then resolve its mirrored header.
        # Combining this match with the number match using OR forced MySQL to
        # scan every mirrored header for each pending task.
        dedup_clauses.append(f"""NOT EXISTS (SELECT 1 FROM `{schema}`.`{records.ITEMS_TABLE}` i
            JOIN `{schema}`.`{records.RECORDS_TABLE}` r ON r.`{rk}`=i.`{ik}`
            WHERE i.order_id=t.order_id{visible})""")
    if not dedup_clauses:
        # Legacy schemas cannot safely deduplicate local entries; keep their
        # existing mirror-only view without granting any local queue access.
        local_clauses.append("1=0")
    else:
        local_clauses.extend(dedup_clauses)
    # Cast only identifiers (not business text) across UNION: database collations
    # differ between the Ark and business schemas on production MySQL.
    def key(expr):
        return f"CAST({expr} AS CHAR)" + (" COLLATE utf8mb4_unicode_ci" if mysql else "")
    date_col = records._col(rm, "outbound_date", "r")
    field = sort_field if sort_field in QUEUE_SORT_FIELDS else None
    mirror_value = mirror_sort_value(db, field, rm, im, link, schema) if field else "NULL"
    local_value = local_sort_value(field, db)
    if mysql and field in ("outbound_no", "order_id", "customer_name", "outbound_state", "status"):
        mirror_value, local_value = key(mirror_value), key(local_value)
    query = f"""
        SELECT {key('r.' + rm['id'])} AS entry_id, 0 AS local_entry,
               {date_col} AS sort_date, r.`{rm['id']}` AS sort_id, {mirror_value} AS sort_value
        FROM `{schema}`.`{records.RECORDS_TABLE}` r {mirror_where}
        UNION ALL
        SELECT {key('t.id')} AS entry_id, 1 AS local_entry, DATE(t.created_at) AS sort_date, t.id AS sort_id, {local_value} AS sort_value
        FROM ark_okki_outbound_tasks t JOIN ark_invoices f ON f.id=t.invoice_id
        WHERE {' AND '.join(local_clauses)}
    """
    return query, params


def _shortages(raw, items):
    """Only expose validated shortage fields, never internal executor errors."""
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("shortages"), list):
        return []
    names = {str(i["sku_id"]): i["product_name"] for i in items if i["sku_id"]}
    result = []
    for shortage in data["shortages"]:
        if not isinstance(shortage, dict):
            continue
        try:
            required = Decimal(str(shortage.get("required")))
            available = Decimal(str(shortage.get("available")))
            if not required.is_finite() or not available.is_finite() or required <= available or required <= 0:
                continue
        except InvalidOperation:
            continue
        sku = str(shortage.get("sku_id") or "")
        result.append({"product_name": names.get(sku, "商品信息待同步"), "sku_id": sku,
                       "required": float(required), "available": float(available),
                       "shortage": float(required - available)})
    return result


def _local_rows(db, ids):
    if not ids:
        return {}
    query = text(f"""SELECT t.id, t.invoice_id, t.order_id, t.status, t.last_error, t.processed_at, t.attempts,
        ({local_retry_at(db)}) AS retry_next_at,
        t.created_at, f.invoice_no, f.customer_name, f.sales_user_name
        FROM ark_okki_outbound_tasks t JOIN ark_invoices f ON f.id=t.invoice_id
        WHERE t.id IN :ids""").bindparams(bindparam("ids", expanding=True))
    tasks = db.execute(query, {"ids": ids}).mappings().all()
    item_query = text("""SELECT invoice_id,sku_id,product_name,quantity FROM ark_invoice_items
        WHERE invoice_id IN :ids ORDER BY sort_order,id""").bindparams(bindparam("ids", expanding=True))
    items_by_invoice = {}
    for item in db.execute(item_query, {"ids": [t["invoice_id"] for t in tasks]}).mappings():
        items_by_invoice.setdefault(item["invoice_id"], []).append(item)
    result = {}
    for task in tasks:
        items = items_by_invoice.get(task["invoice_id"], [])
        state = ("awaiting_sync" if task["status"] in ("done", "skipped") else
                 "retrying" if task["retry_next_at"] is not None else task["status"])
        result[str(task["id"])] = {
            "outbound_record_id": f"task:{task['id']}", "outbound_invoice_id": None,
            "outbound_no": task["invoice_no"], "customer_name": task["customer_name"],
            "order_id": str(task["order_id"]),
            "outbound_date": None, "requested_date": str(task["created_at"])[:10],
            "owner_name": task["sales_user_name"], "remark": None,
            "item_count": len(items), "total_qty": sum(i["quantity"] for i in items),
            "record_source": "ark_task", "outbound_state": state, "can_print": False,
            "retry_next_at": str(task["retry_next_at"]) if task["retry_next_at"] is not None else None,
            "retry_attempt": task["attempts"] + 1 if state == "retrying" else None,
            "stock_shortages": _shortages(task["last_error"], items) if state in ("waiting_stock", "running") else [],
            "stock_checked_at": str(task["processed_at"]) if task["processed_at"] else None,
        }
    return result


def list_outbound_records(db, *, keyword=None, order_id=None, date_from=None, date_to=None,
                          page=1, page_size=20, okki_user_id=None, sort_field=None, sort_order=None,
                          outbound_state=None, inspection_status=None):
    query, params = _queue_query(db, keyword=keyword, order_id=order_id, date_from=date_from,
                               date_to=date_to, okki_user_id=okki_user_id,
                               outbound_state=outbound_state, inspection_status=inspection_status,
                               sort_field=sort_field if sort_order in ("asc", "desc") else None)
    order_by = "sort_date DESC, local_entry DESC, sort_id DESC, entry_id DESC"
    if sort_field in QUEUE_SORT_FIELDS and sort_order in ("asc", "desc"):
        order_by = f"sort_value IS NULL ASC, sort_value {sort_order.upper()}, local_entry DESC, sort_id DESC, entry_id DESC"
    keys = db.execute(text(f"""SELECT q.*, COUNT(*) OVER () AS total FROM ({query}) q
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset"""),
        {**params, "limit": page_size, "offset": (page - 1) * page_size}).mappings().all()
    # An out-of-range page has no window row to carry the total.
    total = (keys[0]["total"] if keys else
             db.execute(text(f"SELECT COUNT(*) FROM ({query}) q"), params).scalar() or 0)
    mirror_ids = [k["entry_id"] for k in keys if not k["local_entry"]]
    mirror_rows = []
    if mirror_ids:
        mirror_rows, _ = records.list_outbound_records(
            db, record_ids=mirror_ids, page_size=page_size, okki_user_id=okki_user_id,
            count_total=False,
        )
    mirror = {r["outbound_record_id"]: {**r, "record_source": "okki", "outbound_state": "ready",
              "can_print": True, "stock_shortages": []} for r in mirror_rows}
    local = _local_rows(db, [k["entry_id"] for k in keys if k["local_entry"]])
    rows = []
    for key in keys:
        row = (local if key["local_entry"] else mirror).get(str(key["entry_id"]))
        if row:
            rows.append(row)
    return rows, int(total)
