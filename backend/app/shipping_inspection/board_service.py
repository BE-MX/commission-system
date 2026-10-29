"""Warehouse inspection board: pending outbound queue, today's results and recent workload.

Read-only aggregation for the big screen.
- Pending: mirrored OKKI outbound documents created inside a recent window whose
  inspection is not submitted (none or draft). Local push tasks are excluded because
  they cannot be printed or scanned yet.
- Done: submitted inspections grouped by Beijing calendar day of submission.
- Customer grade, new-deal and detail-inspection marks follow the same exact
  item -> order links as the printed outbound document (print_customer_service).
- Order amount uses the OKKI order mirror amount_usd, each order counted once.
"""
import logging
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import bindparam, text

from app.auth.models import ArkUser
from app.core.time import beijing_now, beijing_today
from app.invoice.models import CustomerProfile, Invoice
from app.invoice.order_notification_service import _is_new_sign
from app.shipping_inspection import constants as C
from app.shipping_inspection import outbound_service as records
from app.shipping_inspection import record_query_service
from app.shipping_inspection.models import ShippingInspection

logger = logging.getLogger(__name__)

PENDING_WINDOW_DAYS = 30
PENDING_LIMIT = 300
TREND_DAYS = 7
DONE_LIST_LIMIT = 40


def _text(value):
    return str(value) if value is not None and str(value) != "" else None


def _expanding(sql, *names):
    query = text(sql)
    return query.bindparams(*(bindparam(name, expanding=True) for name in names))


def _pending_rows(db, okki_user_id):
    """Newest-first pending record ids with their creation time, bounded by window and limit."""
    rm = records._record_columns(db)
    schema = records._schema()
    columns = records._table_columns(db, records.RECORDS_TABLE)
    # Age is measured from OKKI creation, not the planned warehouse date.
    created = "create_time" if "create_time" in columns else rm["outbound_date"]
    created_expr = f"r.`{created}`" if created else "NULL"
    clauses, params = records.record_list_filters(db, rm, okki_user_id=okki_user_id)
    rid = f"CAST(r.`{rm['id']}` AS CHAR)"
    if db.get_bind().dialect.name == "mysql":
        rid += " COLLATE utf8mb4_unicode_ci"
    clauses.append(
        "NOT EXISTS (SELECT 1 FROM ark_shipping_inspections si "
        f"WHERE si.outbound_record_id={rid} AND si.status='{C.STATUS_SUBMITTED}')"
    )
    # 历史单据（分界前出库）在出库单列表按已提交展示，不能再出现在待检队列。
    if rm.get("outbound_date"):
        clauses.append(f"(r.`{rm['outbound_date']}` IS NULL OR r.`{rm['outbound_date']}` >= :legacy_from)")
        params["legacy_from"] = C.LEGACY_OUTBOUND_BEFORE.isoformat()
    if created:
        clauses.append(f"{created_expr} >= :since")
        params["since"] = (beijing_today() - timedelta(days=PENDING_WINDOW_DAYS)).isoformat()
    rows = db.execute(text(f"""
        SELECT r.`{rm['id']}` AS rid, {created_expr} AS created_at
        FROM `{schema}`.`{records.RECORDS_TABLE}` r
        WHERE {' AND '.join(clauses)}
        ORDER BY {created_expr} DESC, r.`{rm['id']}` DESC
        LIMIT :limit
    """), {**params, "limit": PENDING_LIMIT + 1}).mappings().all()
    return rows[:PENDING_LIMIT], len(rows) > PENDING_LIMIT


def _mirror_facts(db, ids):
    """rid -> company id, detail line count and quantity straight from the item mirror."""
    if not ids:
        return {}
    link, rm, im = records._link(db)
    schema = records._schema()
    company = records._col(rm, "company_id", "r")
    join, lines, qty = "", "0", "0"
    if link:
        ik, rk = (im["invoice_id"], rm["invoice_id"]) if link == "invoice" else (im["record_id"], rm["id"])
        join = f"LEFT JOIN `{schema}`.`{records.ITEMS_TABLE}` i ON i.`{ik}`=r.`{rk}`"
        lines = f"COUNT(i.`{im['id']}`)"
        qty = f"SUM(i.`{im['quantity']}`)" if im["quantity"] else "0"
    rows = db.execute(_expanding(f"""
        SELECT r.`{rm['id']}` AS rid, MAX({company}) AS company_id,
               {lines} AS line_count, {qty} AS qty
        FROM `{schema}`.`{records.RECORDS_TABLE}` r {join}
        WHERE r.`{rm['id']}` IN :ids
        GROUP BY r.`{rm['id']}`
    """, "ids"), {"ids": ids}).mappings().all()
    return {str(row["rid"]): {"company_id": _text(row["company_id"]),
                              "item_count": int(row["line_count"] or 0),
                              "total_qty": records._num(row["qty"]) or 0} for row in rows}


def _mirror_order_usd(db, order_ids):
    """order_id -> (company_id, amount_usd) from the OKKI order mirror."""
    if not order_ids:
        return {}
    rows = db.execute(_expanding(
        f"SELECT order_id, company_id, amount_usd FROM `{records._schema()}`.okki_orders WHERE order_id IN :ids",
        "ids"), {"ids": list(order_ids)}).mappings().all()
    return {str(row["order_id"]): (_text(row["company_id"]), row["amount_usd"]) for row in rows}


def _grades(db, companies):
    if not companies:
        return {}
    return dict(db.query(CustomerProfile.customer_id, CustomerProfile.customer_grade)
                .filter(CustomerProfile.customer_id.in_(companies)).all())


class _Marks:
    """Batch resolver for grade / new deal / detail inspection / salesperson per record."""

    def __init__(self, db, ids, company_by_id):
        self.db = db
        self.company = company_by_id
        self.links = records.order_ids_for_records(db, ids)
        order_ids = {order for values in self.links.values() for order in values}
        invoices = db.query(Invoice).filter(Invoice.xiaoman_order_id.in_(order_ids)).all() if order_ids else []
        self.invoices = {str(invoice.xiaoman_order_id): invoice for invoice in invoices}
        self.grades = _grades(db, {value for value in company_by_id.values() if value})
        self.salespeople = record_query_service.salesperson_names(db, ids)
        self._new_sign = {}

    def _own_invoices(self, rid):
        company = self.company.get(rid)
        # The customer check stops another customer's order from lending its marks.
        return [invoice for order in self.links.get(rid, [])
                if (invoice := self.invoices.get(order)) is not None
                and (company is None or str(invoice.customer_id) == company)]

    def _is_new(self, invoice):
        if invoice.id not in self._new_sign:
            self._new_sign[invoice.id] = _is_new_sign(self.db, {"id": invoice.id, "okki_new_deal": invoice.okki_new_deal})
        return self._new_sign[invoice.id]

    def of(self, rid):
        own = self._own_invoices(rid)
        company = self.company.get(rid)
        sales = self.salespeople.get(rid) or "、".join(dict.fromkeys(
            str(invoice.sales_user_name) for invoice in own if invoice.sales_user_name)) or None
        return {
            "customer_grade": self.grades.get(company) if company else None,
            "is_new_deal": any(self._is_new(invoice) for invoice in own),
            "inspection_requirement": "detail" if any(
                invoice.inspection_requirement == "detail" for invoice in own) else "single",
            "salesperson_name": sales,
        }


def _pending(db, okki_user_id):
    rows, truncated = _pending_rows(db, okki_user_id)
    ids = [str(row["rid"]) for row in rows]
    if not ids:
        return [], truncated
    created = {str(row["rid"]): _text(row["created_at"]) for row in rows}
    # Reuse the queue reader so verified header/detail overlays match the printed document.
    listed, _ = records.list_outbound_records(db, record_ids=ids, page_size=len(ids), count_total=False)
    by_id = {row["outbound_record_id"]: row for row in listed}
    drafts = {rid for (rid,) in db.query(ShippingInspection.outbound_record_id).filter(
        ShippingInspection.outbound_record_id.in_(ids), ShippingInspection.status == C.STATUS_DRAFT)}
    marks = _Marks(db, ids, {rid: _text(row.get("company_id")) for rid, row in by_id.items()})
    result = []
    for rid in ids:
        row = by_id.get(rid)
        if row is None:
            continue  # Deleted or filtered between the two reads.
        result.append({
            "outbound_record_id": rid,
            "outbound_no": row["outbound_no"],
            "customer_name": row["customer_name"],
            "created_at": created.get(rid) or row.get("outbound_date"),
            "item_count": row["item_count"],
            "total_qty": row["total_qty"],
            "inspecting": rid in drafts,
            **marks.of(rid),
        })
    return result, truncated


def _done(db, okki_user_id, since):
    query = (db.query(ShippingInspection, ArkUser.real_name)
             .outerjoin(ArkUser, ArkUser.id == ShippingInspection.submitted_by)
             .filter(ShippingInspection.status == C.STATUS_SUBMITTED, ShippingInspection.submitted_at >= since))
    if okki_user_id is not None:
        query = query.filter(ShippingInspection.outbound_record_id.in_(
            records.scoped_record_ids_query(db, okki_user_id)))
    return query.order_by(ShippingInspection.submitted_at.desc(), ShippingInspection.id.desc()).all()


def _today_amount(db, done_ids, facts):
    """Distinct linked orders of today's inspected documents; unknown amounts are counted, not guessed."""
    links = records.order_ids_for_records(db, done_ids)
    owner = {}
    for rid in done_ids:
        for order in links.get(rid, []):
            owner.setdefault(order, (facts.get(rid) or {}).get("company_id"))
    amounts = _mirror_order_usd(db, owner.keys())
    total, missing = Decimal("0"), 0
    for order, company in owner.items():
        found = amounts.get(order)
        if found is None or found[1] is None or (company and found[0] and found[0] != company):
            missing += 1
            continue
        total += Decimal(str(found[1]))
    return float(total.quantize(Decimal("0.01"))), missing


def build_board(db, okki_user_id=None):
    now = beijing_now()
    today = beijing_today()
    today_start = datetime.combine(today, time.min)
    trend_start = today_start - timedelta(days=TREND_DAYS - 1)

    pending, truncated = _pending(db, okki_user_id)
    done_rows = _done(db, okki_user_id, trend_start)
    done_ids = list(dict.fromkeys(str(insp.outbound_record_id) for insp, _ in done_rows))
    facts = _mirror_facts(db, done_ids)

    trend = {(today - timedelta(days=offset)).isoformat(): {"orders": 0, "qty": 0}
             for offset in range(TREND_DAYS - 1, -1, -1)}
    today_rows = []
    for insp, name in done_rows:
        day = insp.submitted_at.date().isoformat()
        if day in trend:
            trend[day]["orders"] += 1
            trend[day]["qty"] += (facts.get(str(insp.outbound_record_id)) or {}).get("total_qty", 0)
        if insp.submitted_at >= today_start:
            today_rows.append((insp, name))

    today_ids = [str(insp.outbound_record_id) for insp, _ in today_rows]
    amount, missing = _today_amount(db, today_ids, facts)
    customers = {(facts.get(rid) or {}).get("company_id") or f"name:{insp.customer_name}"
                 for (insp, _), rid in zip(today_rows, today_ids)}
    salespeople = record_query_service.salesperson_names(db, today_ids[:DONE_LIST_LIMIT])
    grades = _grades(db, {f["company_id"] for f in facts.values() if f["company_id"]})

    return {
        "server_time": now.isoformat(timespec="seconds"),
        "pending_window_days": PENDING_WINDOW_DAYS,
        "pending_truncated": truncated,
        "pending": pending,
        "today": {
            "orders": len(today_rows),
            "qty": sum((facts.get(rid) or {}).get("total_qty", 0) for rid in today_ids),
            "customers": len(customers),
            "amount_usd": amount,
            "amount_missing_orders": missing,
        },
        "inspectors": [{"name": name, "count": count} for name, count in
                       Counter(name or "未知" for _, name in today_rows).most_common()],
        "done": [{
            "outbound_record_id": rid,
            "outbound_no": insp.outbound_no,
            "customer_name": insp.customer_name,
            "customer_grade": grades.get((facts.get(rid) or {}).get("company_id")),
            "salesperson_name": salespeople.get(rid),
            "submitted_at": insp.submitted_at.isoformat(sep=" ", timespec="seconds"),
            "inspector_name": name,
        } for (insp, name), rid in list(zip(today_rows, today_ids))[:DONE_LIST_LIMIT]],
        "trend": [{"date": day, **values} for day, values in trend.items()],
    }
