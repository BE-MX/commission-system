"""Current-authorized manual creation with original key replay and unlocked IO."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.core.storage.cos import StorageError
from app.invoice import okki_client
from app.invoice.edit_authority import lock_document
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from app.receipt import access, attachments, authority, edit_service, retry_service, service
from app.receipt.models import Receipt, ReceiptIntent


def fingerprint(body):
    return hashlib.sha256(body.model_dump_json(exclude={"balance_version"}).encode()).hexdigest()


def _replay(row, invoice, body, actor):
    hashes = {fingerprint(body)}
    if body.purpose == "ordinary" and row.purpose == "ordinary":
        hashes.add(hashlib.sha256(body.model_dump_json(exclude={"balance_version", "purpose"}).encode()).hexdigest())
    if (row.invoice_id != invoice.id or row.invoice_id != body.invoice_id
            or body.purpose == "ordinary" and row.purpose != "ordinary"
            or row.request_key != body.request_key or row.created_by != actor or row.request_hash not in hashes):
        raise HTTPException(409, "提交标识已用于其他回款，请勿复用")


def _authorize(db, body, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        current = authority.current_user(db, user, "receipt:write")
        locator = db.execute(select(Receipt.id, Receipt.invoice_id).where(
            Receipt.request_key == body.request_key)).first()
        invoice_id = locator.invoice_id if locator else body.invoice_id
        invoice = lock_document(db, invoice_id, force=True)
        access.ensure_invoice(db, invoice, current)
        existing = db.scalar(select(Receipt).where(Receipt.request_key == body.request_key)
            .with_for_update().execution_options(populate_existing=True))
        if locator and (existing is None or existing.id != locator.id):
            raise HTTPException(409, "回款提交标识关联已变化，请重新核对")
        if existing is not None:
            # Do not chase a changed target after taking this invoice's lock.
            _replay(existing, invoice, body, access.user_id(current))
        return invoice, current, existing
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "回款创建授权暂不可用",
            headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def _participants(db, invoice, body):
    service.ensure_order_ready(db, invoice, current=True)
    if invoice.order_type == "presale" and body.purpose not in {"presale_deposit", "presale_advance"}:
        raise ValueError("预售回款请选择资金池用途")
    if invoice.order_type == "presale":
        service.ensure_pool_registration(db, invoice, current=True)
    db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id).order_by(Receipt.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    if (intent and intent.eligible and intent.status in {"draft", "armed", "ready"}
            and set(body.attachment_ids).intersection(intent.attachment_ids)):
        raise ValueError("该截图已用于库存单的自动回款，请上传本次回款凭证")


def _binding(invoice):
    values = [getattr(invoice, column.name) for column in invoice.__table__.columns]
    return hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()


def create(db, body, user):
    invoice, current, existing = _authorize(db, body, user)
    if existing is not None:
        return existing, invoice
    _participants(db, invoice, body)
    expected = _binding(invoice)
    target = edit_service.OrderTarget(invoice.id, invoice.xiaoman_order_id, invoice.customer_id,
        invoice.currency, invoice.total_amount, invoice.surcharge_amount)
    files = attachments.capture_binding(db, body.attachment_ids, access.user_id(current), invoice.id, None)
    db.commit()  # Read-only capture; release every business lock before evidence IO.
    try:
        evidence = edit_service._evidence(db, target)
        proofs = attachments.verify_storage(files)
        db.commit()  # Provider token/cache work only, never a commercial row.
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, OSError, StorageError, HTTPException) as error:
        retry_service._unavailable(error, message="回款创建证据暂不可用，请核对原请求")
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    invoice, current, existing = _authorize(db, body, user)
    if existing is not None:
        return existing, invoice  # Same-key competing commit wins before stale evidence guards.
    if _binding(invoice) != expected:
        raise HTTPException(409, "订单在核验期间已变化，请重新读取")
    _participants(db, invoice, body)
    row = service._create(db, invoice, body, access.user_id(current), fingerprint(body),
        evidence.snapshot(), evidence.payment_types, proofs)
    return row, invoice


def result_unavailable(error):
    retry_service._unavailable(error, message="回款创建结果暂不能确认，请以原提交标识核对；勿更换标识重复提交")
