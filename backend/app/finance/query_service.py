"""Current local AR aging and accounting conservation diagnostics."""
from decimal import Decimal
from sqlalchemy import select, func, or_
from app.core.time import beijing_today
from app.customer.access_service import apply_customer_scope
from app.customer.models import CustomerAccount
from app.finance.models import FinanceEvent
from app.finance.service import money
from app.invoice.models import Invoice
from app.invoice.settlement_models import Receivable, ReceiptBatch
from app.receipt import access
from app.receipt.models import Receipt
from app.invoice.native_visibility import local_invoice_scope, customer_scope_predicate


def order_options(db, user, *, keyword=None, customer_id=None, currency=None, page=1, page_size=30):
    query = access.scope(db.query(Invoice).filter(Invoice.transaction_mode == "local",
        Invoice.commerce_status.notin_(["draft", "opening", "cancelled"])), db, user)
    query = query.filter(local_invoice_scope(db, user, read_permissions=("receipt:read", "receipt:write", "receipt:admin")))
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.filter(or_(Invoice.invoice_no.ilike(term), Invoice.customer_name.ilike(term)))
    if customer_id is not None:
        query = query.filter(Invoice.local_customer_id == customer_id)
    if currency:
        query = query.filter(Invoice.currency == currency.upper())
    total = query.count()
    rows = query.order_by(Invoice.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{"id": row.id, "invoice_no": row.invoice_no, "customer_name": row.customer_name,
        "local_customer_id": row.local_customer_id, "currency": row.currency, "order_type": row.order_type,
        "commerce_status": row.commerce_status} for row in rows], "total": total, "page": page, "page_size": page_size}


def allocations(db, batch_id, user):
    query = access.scope(db.query(Receipt, Invoice).join(Invoice, Invoice.id == Receipt.invoice_id).filter(
        Receipt.batch_id == batch_id, Receipt.source == "local"), db, user)
    query = query.filter(local_invoice_scope(db, user, read_permissions=("receipt:read", "receipt:admin")))
    return [{"id": row.id, "version": row.version, "invoice_id": invoice.id, "invoice_no": invoice.invoice_no,
        "receivable_id": row.receivable_id, "purpose": row.purpose, "currency": row.currency,
        "amount": str(row.amount), "reversed_amount": str(row.reversed_amount), "effective_amount": str(row.effective_amount),
        "bank_charge": str(row.bank_charge), "reversed_bank_charge": str(row.reversed_bank_charge),
        "effective_bank_charge": str(row.effective_bank_charge), "status": row.status}
        for row, invoice in query.order_by(Receipt.id.desc())]


def aging(db, user):
    query = db.query(Receivable, Invoice).join(Invoice, Invoice.id == Receivable.invoice_id).filter(
        Invoice.transaction_mode == "local", Invoice.commerce_status.notin_(["draft", "opening", "cancelled"]))
    query = access.scope(query, db, user)
    query = query.filter(local_invoice_scope(db, user, read_permissions=("receipt:read", "receipt:admin")))
    totals, rows = {}, []
    today = beijing_today()
    for target, invoice in query.order_by(Receivable.id):
        remaining = money(target.amount + target.adjustment_amount - target.paid_amount)
        if remaining <= 0:
            continue
        late = (today - target.due_date).days if target.due_date else None
        bucket = ("undated" if late is None else "not_due" if late <= 0 else
                  "1_30" if late <= 30 else "31_60" if late <= 60 else "61_90" if late <= 90 else "over_90")
        currency = totals.setdefault(target.currency, {name: Decimal("0.00") for name in
                                    ("undated", "not_due", "1_30", "31_60", "61_90", "over_90", "total")})
        currency[bucket] += remaining
        currency["total"] += remaining
        rows.append({"receivable_id": target.id, "invoice_id": invoice.id, "invoice_no": invoice.invoice_no,
                     "customer_name": invoice.customer_name, "kind": target.kind, "currency": target.currency,
                     "due_date": target.due_date, "overdue_days": max(0, late) if late is not None else None,
                     "bucket": bucket, "remaining_amount": str(remaining)})
    return {"business_date": today, "by_currency": {code: {key: str(value) for key, value in values.items()}
                                                    for code, values in totals.items()}, "items": rows}


def reconcile(db, user):
    # Read-only RR snapshot: all projections and events are committed atomically.
    query = select(ReceiptBatch).where(ReceiptBatch.transaction_mode == "local")
    query = query.where(customer_scope_predicate(db, user, ReceiptBatch.local_customer_id,
        read_permissions=("receipt:read", "receipt:admin")))
    batches = db.scalars(query).all()
    ids = [batch.id for batch in batches]
    allocations = dict(db.execute(select(Receipt.batch_id, func.sum(Receipt.amount - Receipt.reversed_amount)).where(
        Receipt.batch_id.in_(ids), Receipt.source == "local", Receipt.status == "active").group_by(Receipt.batch_id)).all())
    allocation_fees = dict(db.execute(select(Receipt.batch_id, func.sum(Receipt.bank_charge - Receipt.reversed_bank_charge)).where(
        Receipt.batch_id.in_(ids), Receipt.source == "local", Receipt.status == "active").group_by(Receipt.batch_id)).all())
    refunds = dict(db.execute(select(FinanceEvent.batch_id, func.sum(FinanceEvent.amount)).where(
        FinanceEvent.batch_id.in_(ids), FinanceEvent.action.in_(["refund", "opening_refund"])).group_by(FinanceEvent.batch_id)).all())
    allocation_events = dict(db.execute(select(FinanceEvent.batch_id, func.sum(FinanceEvent.amount)).where(
        FinanceEvent.batch_id.in_(ids), FinanceEvent.action.in_(["allocate", "opening_allocation", "reverse_allocation"]))
        .group_by(FinanceEvent.batch_id)).all())
    differences = []
    for row in batches:
        expected = {"net_amount": money(row.gross_amount - row.actual_bank_fee),
                    "allocated_amount": money(allocations.get(row.id, 0)),
                    "bank_charge_total": money(allocation_fees.get(row.id, 0)),
                    "refunded_amount": -money(refunds.get(row.id, 0))}
        for name, amount in expected.items():
            if getattr(row, name) != amount:
                differences.append({"batch_id": row.id, "field": name, "actual": str(getattr(row, name)), "expected": str(amount)})
        if money(allocation_events.get(row.id, 0)) != row.allocated_amount:
            differences.append({"batch_id": row.id, "field": "allocation_events", "actual": str(row.allocated_amount),
                                "expected": str(money(allocation_events.get(row.id, 0)))})
        if row.allocated_amount + row.refunded_amount > row.gross_amount:
            differences.append({"batch_id": row.id, "field": "overdrawn"})
    ar_query = access.scope(db.query(Receivable).join(Invoice, Invoice.id == Receivable.invoice_id).filter(
        Invoice.transaction_mode == "local"), db, user)
    ar_query = ar_query.filter(local_invoice_scope(db, user, read_permissions=("receipt:read", "receipt:admin")))
    targets = ar_query.all()
    target_ids = [row.id for row in targets]
    ar_paid = dict(db.execute(select(FinanceEvent.receivable_id, func.sum(FinanceEvent.amount)).where(
        FinanceEvent.receivable_id.in_(target_ids), FinanceEvent.action.in_(["allocate", "opening_allocation", "reverse_allocation"]))
        .group_by(FinanceEvent.receivable_id)).all())
    ar_adjusted = dict(db.execute(select(FinanceEvent.receivable_id, func.sum(FinanceEvent.amount)).where(
        FinanceEvent.receivable_id.in_(target_ids), FinanceEvent.action.in_(["adjust_receivable", "opening_adjustment"]))
        .group_by(FinanceEvent.receivable_id)).all())
    for row in targets:
        for field, values in (("paid_amount", ar_paid), ("adjustment_amount", ar_adjusted)):
            expected = money(values.get(row.id, 0))
            if getattr(row, field) != expected:
                differences.append({"receivable_id": row.id, "field": field, "actual": str(getattr(row, field)), "expected": str(expected)})
    return {"checked_payments": len(batches), "checked_receivables": len(targets), "differences": differences}
