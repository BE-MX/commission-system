"""Read one consistent local commercial snapshot under the accounting lock.

Contract GMV includes packaging and contract freight, excludes customer payment
charges and later presale freight targets. Cash reversal alone does not cancel a
sale. Only explicit receivable adjustments change its commercial value.
"""
from decimal import Decimal
from sqlalchemy import select
from app.aftersales.models import AfterSalesCase, AfterSalesExecution
from app.commerce_migration.models import MigrationRecord
from app.finance.models import FinanceEvent
from app.finance.service import book, lock, money
from app.invoice.models import Invoice, InvoiceItem, InvoiceCommerceEvent
from app.invoice.settlement_models import Receivable


def _current(query):
    # Acquiring the book does not refresh an already established MySQL RR view.
    return query.with_for_update().execution_options(populate_existing=True)


def build_snapshot(db, invoice_id):
    book(db)
    invoice = lock(db, Invoice, invoice_id)
    if invoice is None or invoice.transaction_mode != "local":
        raise ValueError("本地订单不存在")
    if invoice.commerce_status in {"draft", "opening"} or (
        invoice.commerce_status == "cancelled" and invoice.local_rate_to_usd is None
    ):
        # A cancelled draft never became a commercial order and has no FX.
        return None
    if invoice.local_rate_to_usd is None or invoice.local_commercial is None:
        raise ValueError("订单缺少已核验的经营快照或确认汇率")
    items = db.scalars(_current(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
        .order_by(InvoiceItem.id))).all()
    families = {}
    if 'opening_valid_business_order' in invoice.local_commercial:
        proof = db.scalar(_current(select(MigrationRecord).where(MigrationRecord.local_invoice_id == invoice.id,
            MigrationRecord.object_type == 'order_binding', MigrationRecord.role == 'opening')))
        if proof is None:
            raise ValueError('历史经营快照缺少完整订单承接凭证')
        families = {link['invoice_item_id']: source['product_family'] for link, source in zip(
            proof.snapshot['_original_links']['items'], proof.snapshot['items'], strict=True)}
    targets = db.scalars(_current(select(Receivable).where(Receivable.invoice_id == invoice.id)
        .order_by(Receivable.id))).all()
    commercial_target_ids = {row.id for row in targets if not (row.kind == "freight" and row.settlement_id is not None)}
    events = db.scalars(_current(select(FinanceEvent).join(Receivable, Receivable.id == FinanceEvent.receivable_id)
        .where(Receivable.invoice_id == invoice.id).order_by(FinanceEvent.id))).all()
    executions = db.scalars(_current(select(AfterSalesExecution).join(AfterSalesCase, AfterSalesCase.id == AfterSalesExecution.case_id)
        .join(InvoiceItem, InvoiceItem.id == AfterSalesCase.local_invoice_item_id)
        .where(InvoiceItem.invoice_id == invoice.id).order_by(AfterSalesExecution.id))).all()
    replacement = db.scalar(_current(select(AfterSalesExecution).where(AfterSalesExecution.related_invoice_id == invoice.id)))
    adjustment = sum((row.adjustment_amount for row in targets if row.id in commercial_target_ids), Decimal(0))
    contract_events = set(db.scalars(_current(select(InvoiceCommerceEvent.id).where(
        InvoiceCommerceEvent.invoice_id == invoice.id, InvoiceCommerceEvent.action.in_(['amend', 'opening_order'])))))
    contract_adjustments = [row for row in events if row.receivable_id in commercial_target_ids
        and row.action in {'adjust_receivable', 'opening_adjustment'} and row.payload.get('contract_change_event_id') is not None]
    if any(row.payload['contract_change_event_id'] not in contract_events for row in contract_adjustments):
        raise ValueError('合同差额缺少同单实际变更依据')
    # Current invoice lines already include contract amendments. Their AR
    # delta preserves the original receivable face, not a second sale.
    adjustment -= sum((row.amount for row in contract_adjustments), Decimal(0))
    refunded_charge = sum((Decimal(row.payload["released_bank_charge"]) for row in events
        if row.action in {"aftersales_release", "opening_adjustment"}
        and row.payload.get("released_bank_charge") is not None and row.receivable_id in commercial_target_ids), Decimal(0))
    amount = max(Decimal(0), money(invoice.total_amount - invoice.surcharge_amount + adjustment + refunded_charge))
    private = bool(invoice.local_commercial.get("is_private_order"))
    free_sample = (invoice.total_amount - invoice.surcharge_amount == 0 and adjustment == 0
        and bool(items) and all(row.commercial_kind == "sample" for row in items) and replacement is None)
    valid = invoice.commerce_status in {"confirmed", "partially_shipped", "shipped", "closed"} and (amount > 0 or free_sample) and not private
    if 'opening_valid_business_order' in invoice.local_commercial:
        source_zero = Decimal(invoice.local_commercial['opening_business_amount_original']) == 0
        valid = (invoice.commerce_status in {'confirmed', 'partially_shipped', 'shipped', 'closed'}
            and invoice.local_commercial['opening_valid_business_order'] and not private
            and (amount > 0 or source_zero))
    amount_usd = money(amount * invoice.local_rate_to_usd)
    return {
        "schema_version": "local_order_v1", "invoice_id": invoice.id,
        "invoice_version": invoice.commerce_version,
        "finance_event_id": max((row.id for row in events), default=0),
        "aftersales_execution_id": max([row.id for row in executions] + [replacement.id if replacement else 0]),
        "customer_id": invoice.local_customer_id, "order_no": invoice.invoice_no,
        "status": invoice.commerce_status, "account_date": invoice.local_commercial.get("account_date", invoice.invoice_date.isoformat()),
        "currency": invoice.currency, "rate_to_usd": str(invoice.local_rate_to_usd),
        "amount_original": str(amount), "amount_usd": str(amount_usd),
        "contract_amount": str(invoice.total_amount), "customer_payment_charge": str(invoice.surcharge_amount),
        "commercial_adjustment": str(adjustment), "refunded_customer_charge": str(refunded_charge),
        "is_valid_business_order": valid,
        "is_free_sample": free_sample, "replacement_execution_id": replacement.id if replacement else None,
        "invalid_reason": None if valid else "cancelled" if invoice.commerce_status == "cancelled" else "private_order" if private else "zero_commercial_value",
        "owner_user_id": invoice.sales_user_id, "commercial": dict(invoice.local_commercial),
        # Physical returns remain separate facts: a returned item may be replaced
        # without cancellation of its original commercial contract.
        "aftersales": [{"id": row.id, "action": row.action, "quantity": row.quantity,
            "business_date": row.business_date.isoformat(), "case_id": row.case_id} for row in executions],
        "items": [{"item_id": str(row.id), "sku_id": f"ark:{row.local_sku_id}" if row.local_sku_id else None,
            "product_name": row.product_name, "product_family": families.get(row.id, row.product_display), "model": row.model,
            "color": row.color, "length": row.length, "quantity": str(row.quantity), "quantity_unit": "piece",
            "unit_price": str(row.price_per_piece) if row.price_per_piece is not None else None,
            "line_amount": str(row.total_price), "item_type": row.commercial_kind or "unknown"} for row in items],
    }
