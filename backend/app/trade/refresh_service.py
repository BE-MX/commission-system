"""Select unfinished projections from source versions, never from wall time."""
from datetime import timedelta
from sqlalchemy import and_, exists, func, or_, select
from app.core.time import beijing_now, to_beijing_time
from app.aftersales.models import AfterSalesCase, AfterSalesExecution
from app.customer.models import CustomerAccount, CustomerObjectOwnership, CustomerOrder, CustomerSourceRecord, CustomerSyncCursor
from app.finance.models import FinanceEvent
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import Receivable
from app.trade.models import TradeProjection


def pending_invoices():
    finance_changed = exists(select(FinanceEvent.id).join(Receivable, Receivable.id == FinanceEvent.receivable_id)
        .where(Receivable.invoice_id == Invoice.id, FinanceEvent.id > TradeProjection.finance_event_id))
    aftersales_changed = exists(select(AfterSalesExecution.id)
        .join(AfterSalesCase, AfterSalesCase.id == AfterSalesExecution.case_id)
        .join(InvoiceItem, InvoiceItem.id == AfterSalesCase.local_invoice_item_id)
        .where(InvoiceItem.invoice_id == Invoice.id, AfterSalesExecution.id > TradeProjection.aftersales_execution_id))
    replacement_changed = exists(select(AfterSalesExecution.id).where(AfterSalesExecution.related_invoice_id == Invoice.id,
        AfterSalesExecution.id > TradeProjection.aftersales_execution_id))
    return (select(Invoice.id).outerjoin(TradeProjection, TradeProjection.invoice_id == Invoice.id)
        .outerjoin(CustomerOrder, CustomerOrder.id == TradeProjection.customer_order_id)
        .outerjoin(CustomerObjectOwnership, (CustomerObjectOwnership.object_type == "order") &
                   (CustomerObjectOwnership.object_id == CustomerOrder.id))
        .outerjoin(CustomerSourceRecord, CustomerSourceRecord.id == CustomerOrder.source_record_id)
        .outerjoin(CustomerAccount, CustomerAccount.id == CustomerSourceRecord.customer_id)
        .where(Invoice.transaction_mode == "local", Invoice.commerce_status.notin_(["draft", "opening"]),
            # Cancelled drafts have no commercial history to project.
            or_(Invoice.commerce_status != "cancelled", Invoice.local_rate_to_usd.is_not(None)),
            or_(TradeProjection.invoice_id.is_(None), Invoice.commerce_version != TradeProjection.invoice_version,
                finance_changed, aftersales_changed, replacement_changed,
                CustomerSourceRecord.customer_id != func.coalesce(CustomerObjectOwnership.current_customer_id, CustomerOrder.customer_id),
                CustomerAccount.record_status != "active")))


def projection_status(db, *, owner_ids=None, date_from=None, date_to=None):
    pending_query = pending_invoices()
    completed_query = select(func.max(TradeProjection.projected_at))
    if owner_ids is not None or date_from is not None or date_to is not None:
        def scope(owner, day):
            clauses = [owner.in_(owner_ids)] if owner_ids is not None else []
            if date_from is not None:
                clauses.append(day >= date_from)
            if date_to is not None:
                clauses.append(day <= date_to)
            return and_(*clauses)
        # Check both the current source and previous fact. A moved order must
        # invalidate its old report until the stale contribution is removed.
        within_scope = or_(scope(Invoice.sales_user_id, Invoice.invoice_date),
            scope(CustomerOrder.owner_user_id, CustomerOrder.account_date))
        pending_query = pending_query.where(within_scope)
        completed_query = (completed_query.join(Invoice, Invoice.id == TradeProjection.invoice_id)
            .join(CustomerOrder, CustomerOrder.id == TradeProjection.customer_order_id).where(within_scope))
    pending = db.scalar(select(func.count()).select_from(pending_query.subquery()))
    from app.commerce_transition.models import TransferPreparation
    transfers = db.scalars(select(TransferPreparation).where(TransferPreparation.state != 'completed')).all()
    frozen_ids = {identity for row in transfers for identity in row.manifest['invoice_ids']}
    relevant = select(Invoice.id).where(Invoice.id.in_(frozen_ids))
    if owner_ids is not None or date_from is not None or date_to is not None:
        # A frozen source can still contribute to its previous customer report
        # until activation rewrites that same row. Invalidate both dimensions,
        # including waiting preparations that have not attached the local ID.
        relevant = relevant.outerjoin(CustomerOrder, or_(CustomerOrder.local_invoice_id == Invoice.id,
            and_(CustomerOrder.source_system == 'okki', CustomerOrder.external_order_id == Invoice.xiaoman_order_id)))
        relevant = relevant.where(or_(scope(Invoice.sales_user_id, Invoice.invoice_date),
            scope(CustomerOrder.owner_user_id, CustomerOrder.account_date)))
    visible_frozen = set(db.scalars(relevant)) if frozen_ids else set()
    handover_pending = sum(bool(visible_frozen.intersection(row.manifest['invoice_ids'])) for row in transfers)
    completed = db.scalar(completed_query)
    local = {"source": "local", "basis": "invoice_finance_aftersales_versions", "pending_count": pending,
             "status": "pending" if pending else "current",
             "synced_through": to_beijing_time(completed).isoformat(timespec="seconds") if completed else None}
    sources = [local]
    from app.trade.service import consumer_phase
    if consumer_phase(db) == "transition":
        cursors = db.scalars(select(CustomerSyncCursor).where(CustomerSyncCursor.source_system == "okki",
            CustomerSyncCursor.resource_type == "orders").order_by(CustomerSyncCursor.scope_key)).all()
        now = beijing_now()
        scopes = [{"scope": c.scope_key, "synced_through": to_beijing_time(c.last_success_at).isoformat(timespec="seconds")
                   if c.last_success_at else None,
                   "status": "unknown" if c.last_success_at is None else
                       "incomplete" if c.sync_status != "idle" or (c.last_counts_json or {}).get("quarantined", 0) else
                       "stale" if now - c.last_success_at > timedelta(hours=24) else "current"}
                  for c in cursors]
        # One healthy account must not mask a second imported account with no
        # registered cursor. The default cursor represents the global importer.
        accounts = set(db.scalars(select(CustomerOrder.source_account_key).where(
            CustomerOrder.source_system == "okki", CustomerOrder.local_invoice_id.is_(None)).distinct()))
        known = {c.scope_key for c in cursors}
        if "default" not in known:
            scopes.extend({"scope": account, "synced_through": None, "status": "unknown"}
                          for account in sorted(accounts - known))
        stamps = [c.last_success_at for c in cursors if c.last_success_at]
        legacy_status = "current" if scopes and all(c["status"] == "current" for c in scopes) else "incomplete"
        sources.insert(0, {"source": "legacy", "basis": "customer_sync_cursor", "status": legacy_status,
            "synced_through": to_beijing_time(min(stamps)).isoformat(timespec="seconds")
                if len(stamps) == len(scopes) and stamps else None, "scopes": scopes})
    status = "current" if all(s["status"] == "current" for s in sources) else "pending" if pending else "incomplete"
    if handover_pending:
        status = 'pending'
        for source in sources:
            if source['source'] == 'legacy':
                source['handover_pending_count'], source['status'] = handover_pending, 'pending'
    watermarks = [s["synced_through"] for s in sources if s["synced_through"]]
    return {"pending_count": pending + handover_pending, "handover_pending_count": handover_pending,
            "last_projected_at": min(watermarks) if watermarks else None,
            "status": status, "data_complete": status == "current", "sources": sources,
            "coverage": {"date_from": str(date_from) if date_from else None, "date_to": str(date_to) if date_to else None}}
