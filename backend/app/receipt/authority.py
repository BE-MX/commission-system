"""Current employee authorization for receipt reads and local cancellation.

No remote I/O belongs in this module. The current release requires the migrated
portal schema even when storefront submission is disabled; permanent invoice
lineage must therefore keep its lock protocol after that switch is turned off.
"""
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice.edit_authority import lock_document
from app.portal.authority import lock_authority
from app.portal.access_policy import employee_principal
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access
from app.receipt.models import Receipt


logger = logging.getLogger(__name__)


def unavailable(error):
    # Diagnostics must not replace the controlled response. Preserve failures
    # as an internal cause; process cancellation/termination still propagates.
    diagnostics = []
    try:
        logger.warning("Receipt authorization database unavailable (%s)", type(error).__name__)
    except Exception as failure:
        diagnostics.append(failure)
    try:
        print("[receipt] authorization database unavailable", flush=True)
    except Exception as failure:
        diagnostics.append(failure)
    response = HTTPException(503, "回款授权服务暂不可用，请稍后重试",
        headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"})
    if diagnostics:
        raise response from ExceptionGroup("Receipt authorization diagnostics failed", diagnostics)
    raise response from None



READ_PERMISSIONS = ("receipt:read", "receipt:write", "receipt:admin")
AUXILIARY_READ_PERMISSIONS = READ_PERMISSIONS + ("invoice:read", "invoice:write", "invoice:sync")


def fresh_boundary(db):
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409, "回款授权必须从新事务开始，请重新读取")
    db.expire_all()


def current_user(db, user, *permissions, any_permission=False):
    try:
        actor = int(user.get("sub") or user.get("id") or 0)
        if actor < 1:
            raise ValueError("Invalid identity")
    except (TypeError, ValueError):
        raise HTTPException(403, "无法确认当前操作人") from None
    try:
        current = employee_principal(db, actor, *(() if any_permission else permissions))
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "当前账号无权执行此回款操作") from None
    except SQLAlchemyError as error:
        unavailable(error)
    if any_permission and "super_admin" not in current["roles"]:
        if not set(permissions).intersection(current["permissions"]):
            raise HTTPException(403, "当前账号无权执行此回款操作")
    return current


def read_user(db, user, *permissions):
    """The request's first business read; ordinary read authorization point."""
    fresh_boundary(db)
    return current_user(db, user, *(permissions or READ_PERMISSIONS), any_permission=True)


def local_receipt(db, identity, user, *permissions):
    """Fresh authority -> lineage -> invoice -> receipt, until caller commit."""
    fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = current_user(db, user, *permissions)
        invoice_id = db.scalar(select(Receipt.invoice_id).where(Receipt.id == identity))
        if invoice_id is None:
            raise HTTPException(404, "订单或回款单不存在")
        invoice = lock_document(db, invoice_id, force=True)
        access.ensure_invoice(db, invoice, current)
        row = db.scalar(select(Receipt).where(Receipt.id == identity).with_for_update()
            .execution_options(populate_existing=True))
        if row is None:
            raise HTTPException(404, "订单或回款单不存在")
        if row.invoice_id != invoice_id:
            raise HTTPException(409, "回款关联已变化，请重新读取")
        access.ensure_invoice(db, invoice, current)
        return row, invoice, current
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "回款授权服务暂不可用",
            headers={"Cache-Control":"private, no-store", "Pragma":"no-cache"}) from None
    except SQLAlchemyError as error:
        unavailable(error)


def local_group(db, identity, user, *permissions, any_permission=False):
    """Authorize a receipt group: all lineage, sorted invoices, batch, receipts."""
    from app.invoice.models import Invoice
    from app.invoice.settlement_models import ReceiptBatch
    from app.portal.models import Conversion, OrderRequest
    fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = current_user(db, user, *(permissions or ("receipt:write",)), any_permission=any_permission)
        locator = db.execute(select(Receipt.invoice_id, Receipt.batch_id).where(Receipt.id == identity)).first()
        if locator is None:
            raise HTTPException(404, "订单或回款单不存在")
        invoice_id, batch_id = locator
        members = db.execute(select(Receipt.id, Receipt.invoice_id).where(
            Receipt.batch_id == batch_id).order_by(Receipt.id)).all() if batch_id else [(identity, invoice_id)]
        invoice_ids = sorted({member[1] for member in members})
        lineage = db.execute(select(Conversion.id, Conversion.request_id).where(
            Conversion.invoice_id.in_(invoice_ids))).all()
        if lineage:
            db.scalars(select(OrderRequest).where(OrderRequest.id.in_({x[1] for x in lineage}))
                .order_by(OrderRequest.id).with_for_update().execution_options(populate_existing=True)).all()
            db.scalars(select(Conversion).where(Conversion.id.in_({x[0] for x in lineage}))
                .order_by(Conversion.id).with_for_update().execution_options(populate_existing=True)).all()
        invoices = {row.id: row for row in db.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids))
            .order_by(Invoice.id).with_for_update().execution_options(populate_existing=True))}
        if len(invoices) != len(invoice_ids):
            raise HTTPException(404, "订单或回款单不存在")
        batch = db.scalar(select(ReceiptBatch).where(ReceiptBatch.id == batch_id).with_for_update()
            .execution_options(populate_existing=True)) if batch_id else None
        if batch_id and batch is None:
            raise HTTPException(404, "回款批次不存在")
        predicate = Receipt.batch_id == batch_id if batch_id else Receipt.id == identity
        children = db.scalars(select(Receipt).where(predicate).order_by(Receipt.id).with_for_update()
            .execution_options(populate_existing=True)).all()
        if [(row.id, row.invoice_id) for row in children] != [tuple(x) for x in members]:
            raise HTTPException(409, "回款批次成员已变化，请重新读取")
        row = next((child for child in children if child.id == identity), None)
        if row is None or row.invoice_id != invoice_id or row.batch_id != batch_id:
            raise HTTPException(409, "回款关联已变化，请重新读取")
        for child in children:
            access.ensure_invoice(db, invoices[child.invoice_id], current)
        return row, invoices[invoice_id], current, batch, children
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "回款授权服务暂不可用",
            headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"}) from None
    except SQLAlchemyError as error:
        unavailable(error)


def local_batch(db, identity, user, *permissions):
    """Batch identity is authoritative; lock and authorize every current member."""
    from app.invoice.models import Invoice
    from app.invoice.settlement_models import ReceiptBatch
    from app.portal.models import Conversion, OrderRequest
    fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = current_user(db, user, *permissions)
        members = db.execute(select(Receipt.id, Receipt.invoice_id).where(Receipt.batch_id == identity)
            .order_by(Receipt.id)).all()
        if not members:
            raise HTTPException(404, "回款批次不存在")
        invoice_ids = sorted({member[1] for member in members})
        lineage = db.execute(select(Conversion.id, Conversion.request_id).where(
            Conversion.invoice_id.in_(invoice_ids))).all()
        if lineage:
            db.scalars(select(OrderRequest).where(OrderRequest.id.in_({x[1] for x in lineage}))
                .order_by(OrderRequest.id).with_for_update().execution_options(populate_existing=True)).all()
            db.scalars(select(Conversion).where(Conversion.id.in_({x[0] for x in lineage}))
                .order_by(Conversion.id).with_for_update().execution_options(populate_existing=True)).all()
        invoices = {row.id: row for row in db.scalars(select(Invoice).where(Invoice.id.in_(invoice_ids))
            .order_by(Invoice.id).with_for_update().execution_options(populate_existing=True))}
        if len(invoices) != len(invoice_ids):
            raise HTTPException(404, "订单或回款单不存在")
        batch = db.scalar(select(ReceiptBatch).where(ReceiptBatch.id == identity).with_for_update()
            .execution_options(populate_existing=True))
        if batch is None:
            raise HTTPException(404, "回款批次不存在")
        children = db.scalars(select(Receipt).where(Receipt.batch_id == identity).order_by(Receipt.id)
            .with_for_update().execution_options(populate_existing=True)).all()
        if [(row.id, row.invoice_id) for row in children] != [tuple(x) for x in members]:
            raise HTTPException(409, "回款批次成员已变化，请重新读取")
        for child in children:
            access.ensure_invoice(db, invoices[child.invoice_id], current)
        return batch, children, current
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "回款授权服务暂不可用",
            headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"}) from None
    except SQLAlchemyError as error:
        unavailable(error)
