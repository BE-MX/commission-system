"""Shared, scoped abnormal-state projection. Never infer failures from error text."""
import logging
from fastapi import HTTPException
from sqlalchemy import or_, literal_column
from app.core.time import beijing_now
from app.invoice import detail_access as access
from app.invoice.models import Invoice, OkkiOutboundTask
from app.invoice.settlement_models import ShipmentOutbound, ShipmentSettlement, Receivable
from app.receipt.models import Receipt
from app.receipt import access as receipt_access
from app.shipping_inspection.models import ShippingOperationEvent

logger = logging.getLogger(__name__)
ORDER_BAD = ("sync_failed", "sync_uncertain")
OUTBOUND_BAD = ("failed", "uncertain", "outbound_uncertain", "review_required")
RECEIPT_BAD = ("failed", "uncertain")
EVENT_BAD = ("sync_failed", "sync_uncertain", "recheck_required", "delete_uncertain", "delete_failed")


def collect(db, user, invoice_ids=None):
    """Whole accessible scope for navigation, or an ID-restricted batch for lists."""
    result = {key: {"state": "restricted", "invoice_ids": set(), "count": 0} for key in ("order", "outbound", "receipt")}
    def narrowed(query):
        return query.filter(Invoice.id.in_(invoice_ids)) if invoice_ids is not None else query
    if access.allowed(user, "order"):
        ids = {i for (i,) in narrowed(access.invoice_query(db, user)).filter(
            or_(Invoice.sync_status.in_(ORDER_BAD), Invoice.status.in_(ORDER_BAD))).with_entities(Invoice.id).all()}
        result["order"] = {"state": "ready", "invoice_ids": ids, "count": len(ids)}
    if access.allowed(user, "receipt"):
        rows = narrowed(access.receipt_query(db, user)).filter(Receipt.status == "active", Receipt.sync_status.in_(RECEIPT_BAD)).with_entities(Receipt.invoice_id).all()
        targets = narrowed(receipt_access.scope(db.query(Receivable.invoice_id).join(Invoice,
            Invoice.id == Receivable.invoice_id).join(ShipmentSettlement, ShipmentSettlement.id == Receivable.settlement_id), db, user)).filter(
                Receivable.kind == "freight", Receivable.remote_status.in_(RECEIPT_BAD), ShipmentSettlement.state != "cancelled").all()
        result["receipt"] = {"state": "ready", "invoice_ids": {i for (i,) in rows + targets}, "count": len(rows) + len(targets)}
    if access.allowed(user, "outbound"):
        try:
            scope = access.outbound_scope(db, user)
            from app.shipping_inspection.list_sort_service import local_retry_at
            retry_at = literal_column(local_retry_at(db).replace("t.", "ark_okki_outbound_tasks.").replace("f.", "ark_invoices."))
            tasks = narrowed(access.local_outbound_query(db.query(OkkiOutboundTask.invoice_id).join(
                Invoice, Invoice.id == OkkiOutboundTask.invoice_id), scope)).filter(
                    OkkiOutboundTask.order_id == Invoice.xiaoman_order_id, OkkiOutboundTask.status.in_(OUTBOUND_BAD), retry_at.is_(None)).all()
            batches = []
            if access.allowed(user, "shipment"):
                query = receipt_access.scope(db.query(ShipmentSettlement.invoice_id).join(
                    Invoice, Invoice.id == ShipmentSettlement.invoice_id).outerjoin(ShipmentOutbound,
                    ShipmentSettlement.id == ShipmentOutbound.settlement_id), db, user)
                batches = narrowed(access.local_outbound_query(query, scope)).filter(or_(ShipmentOutbound.status.in_(OUTBOUND_BAD), ShipmentSettlement.state.in_(OUTBOUND_BAD))).all()
            events = db.query(ShippingOperationEvent).filter(ShippingOperationEvent.action.in_(EVENT_BAD),
                ShippingOperationEvent.scope.in_(("outbound-invoice-sync", "outbound-delete")))
            if scope is not None:
                from app.shipping_inspection.outbound_service import scoped_record_ids_query
                events = events.filter(ShippingOperationEvent.outbound_record_id.in_(scoped_record_ids_query(db, scope)))
            event_rows = events.all()
            ids = {i for (i,) in tasks + batches}
            # Resolve event->invoice by exact mirror order links; no number/customer guessing.
            if event_rows:
                from app.shipping_inspection.outbound_service import order_ids_for_records
                links = order_ids_for_records(db, [e.outbound_record_id for e in event_rows])
                remote_ids = {oid for values in links.values() for oid in values}
                ids.update(i for (i,) in narrowed(db.query(Invoice.id)).filter(Invoice.xiaoman_order_id.in_(remote_ids)).all())
            result["outbound"] = {"state": "ready", "invoice_ids": ids, "count": len(tasks) + len(batches) + len(event_rows)}
        except Exception as exc:
            logger.warning("outbound anomaly scope unavailable: %s", type(exc).__name__)
            print(f"[invoice_detail] outbound anomaly scope unavailable: {type(exc).__name__}", flush=True)
            result["outbound"]["state"] = "unavailable" if not isinstance(exc, HTTPException) or exc.status_code != 403 else "restricted"
    return result


def summary(db, user):
    return {"domains": {k: {"state": v["state"], "has_anomaly": v["count"] > 0,
                            "count": v["count"] if v["state"] == "ready" else None}
                        for k, v in collect(db, user).items()}, "checked_at": beijing_now()}


def annotate(db, user, rows):
    domains = collect(db, user, [r["id"] for r in rows]) if rows else {}
    for row in rows:
        row["anomalies"] = [k for k, v in domains.items() if row["id"] in v["invoice_ids"]]
        row["anomaly_states"] = {k: v["state"] for k, v in domains.items()}
    return rows
