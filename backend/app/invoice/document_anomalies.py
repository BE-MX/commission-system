"""Shared, scoped abnormal-state projection. Never infer failures from error text."""
import logging
from fastapi import HTTPException
from sqlalchemy import literal_column, text, bindparam
from app.core.time import beijing_now
from app.invoice import detail_access as access
from app.invoice.models import Invoice, OkkiOutboundTask
from app.receipt.models import Receipt

logger = logging.getLogger(__name__)
ORDER_BAD = ("sync_failed", "sync_uncertain")
OUTBOUND_BAD = ("failed", "uncertain")
RECEIPT_BAD = ("failed", "uncertain")


def _outbound_sources(db, user, invoice_ids=None):
    """One set of predicates for the badge and its explorable problem list."""
    if not access.allowed(user, "outbound"):
        raise HTTPException(403, "无出库单查看权限")
    scope = access.outbound_scope(db, user)
    def narrowed(query):
        return query.filter(Invoice.id.in_(invoice_ids)) if invoice_ids is not None else query
    from app.shipping_inspection.list_sort_service import local_sort_value
    from app.shipping_inspection.outbound_queue_service import local_unmirrored_clauses
    state = literal_column(local_sort_value("outbound_state", db).replace("t.", "ark_okki_outbound_tasks.").replace("f.", "ark_invoices."))
    unmirrored = local_unmirrored_clauses(db, scope)
    if not unmirrored:
        raise RuntimeError("Cannot verify outbound task replacement")
    task_filter = text(" AND ".join(unmirrored).replace("t.", "ark_okki_outbound_tasks.").replace("f.", "ark_invoices."))
    if scope is not None:
        task_filter = task_filter.bindparams(scope_okki_user_id=scope)
    tasks = narrowed(access.local_outbound_query(db.query(OkkiOutboundTask, Invoice).join(
        Invoice, Invoice.id == OkkiOutboundTask.invoice_id), scope)).filter(
            OkkiOutboundTask.order_id == Invoice.xiaoman_order_id,
            state.in_(bindparam("bad_outbound_states", value=OUTBOUND_BAD, expanding=True)), task_filter).all()
    return tasks


def collect(db, user, invoice_ids=None):
    """Whole accessible scope for navigation, or an ID-restricted batch for lists."""
    result = {key: {"state": "restricted", "invoice_ids": set(), "count": 0} for key in ("order", "outbound", "receipt")}
    def narrowed(query):
        return query.filter(Invoice.id.in_(invoice_ids)) if invoice_ids is not None else query
    if access.allowed(user, "order"):
        ids = {i for (i,) in narrowed(access.invoice_query(db, user)).filter(
            Invoice.status.in_(ORDER_BAD)).with_entities(Invoice.id).all()}
        result["order"] = {"state": "ready", "invoice_ids": ids, "count": len(ids)}
    if access.allowed(user, "receipt"):
        rows = narrowed(access.receipt_query(db, user)).filter(Receipt.status == "active", Receipt.sync_status.in_(RECEIPT_BAD)).with_entities(Receipt.invoice_id).all()
        result["receipt"] = {"state": "ready", "invoice_ids": {i for (i,) in rows}, "count": len(rows)}
    if access.allowed(user, "outbound"):
        try:
            tasks = _outbound_sources(db, user, invoice_ids)
            result["outbound"] = {"state": "ready", "invoice_ids": {invoice.id for _, invoice in tasks}, "count": len(tasks)}
        except Exception as exc:
            logger.warning("outbound anomaly scope unavailable: %s", type(exc).__name__)
            print(f"[invoice_detail] outbound anomaly scope unavailable: {type(exc).__name__}", flush=True)
            result["outbound"]["state"] = "unavailable" if not isinstance(exc, HTTPException) or exc.status_code != 403 else "restricted"
    return result


def summary(db, user):
    return {"domains": {k: {"state": v["state"], "has_anomaly": v["count"] > 0,
                            "count": v["count"] if v["state"] == "ready" else None}
                        for k, v in collect(db, user).items()}, "checked_at": beijing_now()}


def outbound_problems(db, user, *, page=1, page_size=20):
    """Read-only, scoped explanations; never expose executor logs or financial data."""
    tasks = _outbound_sources(db, user)
    items = [{"key": f"task:{task.id}", "number": invoice.invoice_no,
        "customer_name": invoice.customer_name, "state": task.status,
        "problem": "生成失败" if task.status == "failed" else "待核对",
        "guidance": "请进入出库单列表查看当前状态并处理。",
        "updated_at": task.updated_at, "target": {"order_id": task.order_id}}
        for task, invoice in tasks]
    items.sort(key=lambda item: (str(item["updated_at"] or ""), item["key"]), reverse=True)
    return {"items": items[(page - 1) * page_size:page * page_size], "total": len(items),
            "page": page, "page_size": page_size, "checked_at": beijing_now()}


def annotate(db, user, rows):
    domains = collect(db, user, [r["id"] for r in rows]) if rows else {}
    for row in rows:
        row["anomalies"] = [k for k, v in domains.items() if row["id"] in v["invoice_ids"]]
        row["anomaly_states"] = {k: v["state"] for k, v in domains.items()}
    return rows
