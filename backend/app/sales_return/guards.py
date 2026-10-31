"""Commercial edits share existing document locks with return activation."""
from fastapi import HTTPException
from sqlalchemy import select

from app.sales_return.models import ReturnItem, ReturnOrderGuard, SalesReturn


def lock_order(db, order_id, invoice_id=None):
    if invoice_id is not None:
        from app.invoice.edit_authority import lock_document
        lock_document(db, invoice_id, force=True)
    row = db.scalar(select(ReturnOrderGuard).where(ReturnOrderGuard.order_id == str(order_id))
                    .with_for_update().execution_options(populate_existing=True))
    if row is None:
        # The authority barrier serializes creation, including historical orders.
        row = ReturnOrderGuard(order_id=str(order_id), version=1)
        db.add(row)
        db.flush()
    return row


def ensure_commercial_editable(db, order_id):
    if order_id and db.scalar(select(SalesReturn.id).where(
            SalesReturn.order_id == str(order_id), SalesReturn.status == "effective").limit(1)):
        raise HTTPException(409, "该订单存在已生效退货，请先核对净应收与退货；不能直接改价、删单或重新分配预售资金")


def ensure_outbound_editable(db, record):
    identity = record.get("outbound_invoice_id")
    if identity and db.scalar(select(ReturnItem.id).join(SalesReturn, SalesReturn.id == ReturnItem.return_id).where(
            ReturnItem.outbound_id == str(identity), SalesReturn.status == "effective").limit(1)):
        raise HTTPException(409, "该出库单已被生效退货引用，不能直接改量或删除；请先处理原退货单")


def require_legacy_order(db, order_id, invoice_id=None):
    """The existing return ledger owns only orders still on the legacy route."""
    from sqlalchemy import or_
    from app.invoice.models import Invoice
    from app.invoice.transition_gate import allow_route, require_invoice
    allow_route(db, "legacy")
    predicates = [Invoice.xiaoman_order_id == str(order_id)]
    if invoice_id is not None:
        predicates.append(Invoice.id == invoice_id)
    invoices = db.scalars(select(Invoice).where(or_(*predicates)).order_by(Invoice.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    for invoice in invoices:
        require_invoice(db, invoice, "legacy")
