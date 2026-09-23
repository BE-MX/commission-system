"""Authenticated receipt API; the domain service owns business decisions."""
import logging
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.core.config import get_settings
from app.invoice.models import Invoice
from app.receipt import access, attachments, remote, service, storage_proxy, sync_service
from app.receipt.models import ReceiptAttachment, ReceiptIntent
from app.receipt.schemas import ReceiptCreate, ReceiptUpdate, Reason, Resolution

router = APIRouter()
logger = logging.getLogger(__name__)


def execute(db, fn):
    try:
        result = fn()
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        logger.warning("receipt request rejected (%s)", type(exc).__name__)
        print(f"[receipt] request rejected ({type(exc).__name__})", flush=True)
        raise HTTPException(409, "数据已被更新或提交，请刷新确认原单" if isinstance(exc, IntegrityError) else str(exc)) from exc


@router.get("", summary="List receipts within invoice ownership scope")
def list_rows(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              keyword: str = Query("", max_length=100), sync_status: str = "", source: str = "", status: str = "",
              date_from: date | None = None, date_to: date | None = None,
              db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin"))):
    data = service.list_receipts(db, user, page, page_size, keyword, sync_status, source, status, date_from, date_to)
    data["delivery_enabled"] = get_settings().RECEIPT_SYNC_ENABLED
    return ok(data)


@router.get("/order-options", summary="Search available invoice associations")
def options(keyword: str = Query("", max_length=100), page: int = Query(1, ge=1),
            customer_id: str = "", currency: str = "",
            db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin"))):
    return ok(service.order_options(db, user, keyword, page, customer_id, currency))


@router.get("/types", summary="Read receipt payment methods from OKKI")
def types(db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin", "invoice:read", "invoice:write", "invoice:sync"))):
    return execute(db, lambda: remote.receipt_types(db))


@router.get("/order-balance/{invoice_id}", summary="Get verified original-currency balance")
def order_balance(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin"))):
    invoice = db.get(Invoice, invoice_id)
    access.ensure_invoice(db, invoice, user)
    return execute(db, lambda: service.order_balance(db, invoice))


@router.post("/attachments", summary="Upload private payment screenshot")
async def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                 user=Depends(require_any_permission("receipt:write", "invoice:write"))):
    content = await file.read(attachments.MAX_BYTES + 1)
    if not content or len(content) > attachments.MAX_BYTES:
        raise HTTPException(413, "图片为空或超过 10MB")
    proxied = await run_in_threadpool(storage_proxy.forward, request, "/api/receipts/attachments", content, file.filename)
    if proxied is not None:
        return proxied
    return execute(db, lambda: attachments.describe(attachments.upload(db, content, file.filename, access.user_id(user))))


@router.get("/attachments/{identity}", summary="Read permission-checked receipt image")
def proof(identity: str, request: Request, db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin", "invoice:read", "invoice:write", "invoice:sync"))):
    row = db.get(ReceiptAttachment, identity)
    if not row:
        raise HTTPException(404, "凭证不存在")
    from app.invoice.settlement_models import BatchAttachment, ReceiptBatch
    from app.receipt.batch_service import ensure_batch_access
    linked_batch = db.query(BatchAttachment).filter_by(attachment_id=row.id).first()
    if linked_batch:
        if "super_admin" not in user.get("roles", []) and not any(
            p in user.get("permissions", []) for p in ("receipt:read", "receipt:write", "receipt:admin")
        ):
            raise HTTPException(404, "凭证不存在")
        ensure_batch_access(db, db.get(ReceiptBatch, linked_batch.batch_id), user)
    elif row.invoice_id:
        invoice = db.get(Invoice, row.invoice_id)
        permissions = user.get("permissions", [])
        has_receipt_access = "super_admin" in user.get("roles", []) or any(p in permissions for p in ("receipt:read", "receipt:write", "receipt:admin"))
        intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == row.invoice_id).first()
        invoice_proof = intent and identity in intent.attachment_ids and any(p in permissions for p in ("invoice:read", "invoice:write", "invoice:sync"))
        if row.receipt_id:
            if not has_receipt_access:
                raise HTTPException(404, "凭证不存在")
            access.ensure_invoice(db, invoice, user)
        elif has_receipt_access:
            try:
                access.ensure_invoice(db, invoice, user)
            except HTTPException:
                if not invoice_proof:
                    raise
                access.ensure_invoice(db, invoice, user, invoice_context=True)
        elif invoice_proof:
            access.ensure_invoice(db, invoice, user, invoice_context=True)
        else:
            raise HTTPException(404, "凭证不存在")
    elif row.created_by != access.user_id(user):
        raise HTTPException(404, "凭证不存在")
    proxied = storage_proxy.forward(request, f"/api/receipts/attachments/{row.id}")
    if proxied is not None:
        return proxied
    path = attachments.path_for(row)
    if not path.is_file():
        raise HTTPException(404, "凭证文件不存在")
    return FileResponse(path, media_type=row.content_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("", summary="Create receipt and queue delivery with idempotency")
def create(body: ReceiptCreate, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    return execute(db, lambda: service.describe(db, service.create(db, body, user), detail=True))


@router.get("/{identity}", summary="Read receipt and audit trail")
def detail(identity: int, db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:read", "receipt:write", "receipt:admin"))):
    row, invoice = service.get(db, identity, user)
    return ok(service.describe(db, row, invoice, detail=True))


@router.patch("/{identity}", summary="Correct a receipt before remote acceptance")
def edit(identity: int, body: ReceiptUpdate, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    def apply():
        row, invoice = service.get(db, identity, user, lock=True)
        service.change(db, row, invoice, body, access.user_id(user))
        return service.describe(db, row, invoice, detail=True)
    return execute(db, apply)


@router.post("/{identity}/retry", summary="Retry only a definitively rejected receipt")
def retry(identity: int, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    def apply():
        row, invoice = service.get(db, identity, user, lock=True)
        service.retry(db, row, access.user_id(user))
        return service.describe(db, row, invoice, detail=True)
    return execute(db, apply)


@router.post("/{identity}/void", summary="Void a local receipt with no remote effect")
def void(identity: int, body: Reason, db: Session = Depends(get_db), user=Depends(require_permission("receipt:write"))):
    def apply():
        row, invoice = service.get(db, identity, user, lock=True)
        service.void(db, row, body.reason, access.user_id(user))
        return service.describe(db, row, invoice, detail=True)
    return execute(db, apply)


@router.post("/{identity}/reconcile", summary="Read remote result without sending another receipt")
def reconcile(identity: int, db: Session = Depends(get_db), user=Depends(require_any_permission("receipt:write", "receipt:admin"))):
    def apply():
        row, invoice = service.get(db, identity, user, lock=True)
        candidates = sync_service.reconcile(db, row, access.user_id(user))
        return {"receipt": service.describe(db, row, invoice, detail=True), "candidates": candidates}
    return execute(db, apply)


@router.post("/{identity}/resolve", summary="Resolve unknown outcome using administrator evidence")
def resolve(identity: int, body: Resolution, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    def apply():
        row, invoice = service.get(db, identity, user, lock=True)
        sync_service.resolve(db, row, body, access.user_id(user))
        return service.describe(db, row, invoice, detail=True)
    return execute(db, apply)


@router.get("/{identity}/remote-change", summary="Preview verified remote receipt changes")
def remote_change_preview(identity: int, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    from app.receipt import remote_change_service
    row, _ = service.get(db, identity, user, lock=True)
    return execute(db, lambda: remote_change_service.evidence(db, row))


from app.receipt.schemas import RemoteChange


@router.post("/{identity}/remote-change", summary="Accept reviewed remote receipt changes with audit")
def accept_remote_change(identity: int, body: RemoteChange, db: Session = Depends(get_db), user=Depends(require_permission("receipt:admin"))):
    from app.receipt import remote_change_service
    def apply():
        row, invoice = service.get(db, identity, user, lock=True)
        remote_change_service.accept(db, row, body, access.user_id(user))
        return service.describe(db, row, invoice, detail=True)
    return execute(db, apply)
