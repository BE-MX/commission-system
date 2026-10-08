"""Read-only invoice panels and whole-scope navigation alerts."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.core.time import beijing_now
from app.invoice import detail_access, detail_receipts, detail_outbounds, document_anomalies, service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/document-anomalies", summary="Scoped whole-domain document anomaly overview")
def anomalies(db: Session = Depends(get_db), user=Depends(require_any_permission(
    *detail_access.PERMISSIONS["order"], *detail_access.PERMISSIONS["receipt"], *detail_access.PERMISSIONS["outbound"]))):
    return ok(document_anomalies.summary(db, user))


@router.get("/invoices/{invoice_id}/related-detail", summary="Saved invoice snapshot for the read-only viewer")
def header(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission("invoice:read", "invoice:write", "invoice:sync"))):
    invoice = detail_access.get_order(db, invoice_id, user)
    # Do not include the converted receipt draft or editor-only fund snapshots.
    data = service.serialize_detail(invoice)
    for key in ("receipt_draft", "internal_received", "internal_balance"):
        data.pop(key, None)
    document_anomalies.annotate(db, user, [data])
    return ok({"order": data, "checked_at": beijing_now()})


def panel(db, user, identity, reader):
    invoice = detail_access.get_order(db, identity, user)
    try:
        data = reader(db, invoice, user)
        db.commit()  # Persist only existing OAuth/index read-cache housekeeping.
    except HTTPException as exc:
        db.rollback()
        if exc.status_code not in (403, 404, 422):
            raise
        data = {"state": "restricted", "message": "相关单据不在当前查看权限或归属范围内", "items": [], "summary": None, "checked_at": None}
    except Exception as exc:
        db.rollback()
        logger.warning("invoice related panel failed invoice=%s: %s", identity, type(exc).__name__)
        print(f"[invoice_detail] related panel failed invoice={identity}: {type(exc).__name__}", flush=True)
        data = {"state": "unverified", "message": "关联单据核验失败，请重试", "items": [], "summary": None, "checked_at": None}
    return ok(data)


@router.get("/invoices/{invoice_id}/related-detail/receipts", summary="Scoped verified invoice funds and receipt documents")
def receipts(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission("invoice:read", "invoice:write", "invoice:sync"))):
    return panel(db, user, invoice_id, detail_receipts.read)


@router.get("/invoices/{invoice_id}/related-detail/outbounds", summary="Scoped verified actual outbound quantities and related documents")
def outbounds(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_any_permission("invoice:read", "invoice:write", "invoice:sync"))):
    return panel(db, user, invoice_id, detail_outbounds.read)
