"""Short authorized local edits; remote receipt evidence is read outside authority."""
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.invoice import delegation_service, okki_client, service
from app.invoice.models import InvoiceLinkedSync
from app.portal.order_models import Conversion, OrderRequest
from app.portal import authority
from app.portal.upstream_authority import begin_employee_document_write
from app.receipt import remote

logger = logging.getLogger(__name__)


def _visible(db, invoice, user):
    if invoice is None:
        raise HTTPException(404, "发票不存在")
    if "super_admin" in user.get("roles", []) or "invoice:read_all" in user.get("permissions", []):
        return
    actor = user.get("id") or user.get("sub")
    if not actor or not delegation_service.can_access_invoice(db, int(actor), invoice):
        raise HTTPException(404, "发票不存在")


def lock_document(db, invoice_id, *, force=False):
    """Lock portal lineage before its invoice; caller already holds authority."""
    if force or authority.get_settings().PORTAL_ENABLED:
        with db.no_autoflush:
            identity = db.execute(select(Conversion.id, Conversion.request_id)
                .where(Conversion.invoice_id == invoice_id)).first()
            if identity is not None:
                db.scalar(select(OrderRequest).where(OrderRequest.id == identity.request_id)
                    .with_for_update().execution_options(populate_existing=True))
                db.scalar(select(Conversion).where(Conversion.id == identity.id)
                    .with_for_update().execution_options(populate_existing=True))
    return service.get_invoice(db, invoice_id, for_update=True)


def prepare_local(db, invoice_id, user, *permissions, any_permission=False):
    """First DB work for local-only mutations, without external evidence reads."""
    enabled = authority.get_settings().PORTAL_ENABLED
    if enabled and (db.in_transaction() or db.new or db.dirty or db.deleted):
        raise HTTPException(409, "发票授权必须从新事务开始，请重新读取")
    if enabled:
        db.expire_all()  # Prior committed identity-map entries are not current reads.
    required = () if any_permission else permissions
    user = begin_employee_document_write(db, user, *required)
    if enabled and any_permission and "super_admin" not in user.get("roles", []):
        if not set(permissions).intersection(user.get("permissions", [])):
            raise HTTPException(403, "当前账号无权执行此发票操作")
    invoice = lock_document(db, invoice_id)
    _visible(db, invoice, user)
    return invoice, user


def _binding(db, invoice):
    from app.invoice.linked_sync_service import edit_version
    task = None
    if invoice.linked_sync_id:
        row = db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.id == invoice.linked_sync_id)
            .with_for_update().execution_options(populate_existing=True))
        if row is not None:
            task = (row.id, row.invoice_id, row.status, row.run_token, row.lease_until)
    return (invoice.id, invoice.portal_document_version, edit_version(invoice),
            invoice.xiaoman_order_id, invoice.sync_status, invoice.linked_sync_id, task)


def _has_replay(db, invoice, user, body):
    if body is None:
        return False
    from app.invoice import linked_sync_service
    try:
        existing, _ = linked_sync_service.replay(db, invoice, body, int(user["id"]))
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    return existing is not None


def prepare(db, invoice_id, user, *permissions, linked_body=None):
    """First endpoint DB work; returns a locked PI, current user and receipt rows.

    Disabled mode keeps the prior transaction/remote behavior. Enabled mode
    commits only its initial read-only authorization/capture before remote I/O,
    then starts a new transaction, rechecks live scope and exact PI binding,
    and leaves all local receipt guards to the actual edit service.
    """
    enabled = authority.get_settings().PORTAL_ENABLED
    if enabled and (db.in_transaction() or db.new or db.dirty or db.deleted):
        raise HTTPException(409, "编辑取证前存在未提交修改，请重新读取")
    if enabled:
        db.expire_all()
    user = begin_employee_document_write(db, user, *permissions)
    invoice = lock_document(db, invoice_id)
    _visible(db, invoice, user)
    if not enabled:
        return invoice, user, None
    if _has_replay(db, invoice, user, linked_body):
        return invoice, user, []  # Authorized original command needs no new evidence.
    if not invoice.xiaoman_order_id:
        return invoice, user, []
    expected = _binding(db, invoice)
    order_id = invoice.xiaoman_order_id
    db.commit()  # Capture/auth transaction has no commercial writes.
    try:
        rows = remote.order_receipts(db, order_id)
        if not isinstance(rows, list):
            raise ValueError("Incomplete receipt evidence")
    except (ValueError, okki_client.OkkiApiError):
        logger.warning("Invoice edit remote receipt evidence unavailable")
        print("Invoice edit remote receipt evidence unavailable", flush=True)
        raise HTTPException(503, "回款证据暂不可用，请稍后重试") from None
    finally:
        db.rollback()  # Discard read snapshots before current authorization.
        db.expire_all()  # Also refresh when the external fast path opened no transaction.
    user = begin_employee_document_write(db, user, *permissions)
    invoice = lock_document(db, invoice_id)
    _visible(db, invoice, user)
    if _has_replay(db, invoice, user, linked_body):
        return invoice, user, []  # A concurrent identical command may have committed.
    if _binding(db, invoice) != expected:
        raise HTTPException(409, "发票在回款核对期间已变化，请重新读取后编辑")
    return invoice, user, rows



def prepare_recovery(db, invoice_id, user, *permissions):
    """Fresh short recovery phase, retaining enabled authority after flag changes."""
    from app.portal.access_policy import employee_principal
    from app.portal.errors import PortalError
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409, "发票核对必须从新事务开始")
    db.expire_all()
    authority.lock_authority(db, force=True)
    try:
        current = employee_principal(db, int(user.get("id") or user.get("sub") or 0), *permissions)
    except (ValueError, TypeError):
        raise HTTPException(403, "无法确认当前操作人") from None
    except PortalError as error:
        raise HTTPException(error.status, "当前账号无权核对此发票") from None
    invoice = lock_document(db, invoice_id, force=True)
    _visible(db, invoice, current)
    return invoice, current
