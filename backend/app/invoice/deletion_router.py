"""Single-confirmation invoice deletion with complete related-document checks."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import deletion_service, okki_client

router = APIRouter()
logger = logging.getLogger(__name__)


class DeleteConfirmation(BaseModel):
    expected_version: str = Field(min_length=64, max_length=64)
    confirmed: bool = False


def _scope(db, identity, user):
    from app.invoice.router import _linked_scope
    invoice, _, _ = _linked_scope(db, identity, user)
    return invoice


def _reject(db, exc):
    db.rollback()
    logger.warning("Invoice deletion rejected (%s)", type(exc).__name__)
    print(f"[invoice-deletion] rejected ({type(exc).__name__})", flush=True)
    raise HTTPException(409, str(exc)) from exc


@router.get("/invoices/{invoice_id}/deletion", summary="Preview related documents for one-confirmation deletion")
def preview(invoice_id: int, db: Session = Depends(get_db), user=Depends(require_permission("invoice:admin"))):
    invoice = _scope(db, invoice_id, user)
    try:
        return ok(deletion_service.preview(db, invoice, user))
    except (ValueError, okki_client.OkkiApiError) as exc:
        _reject(db, exc)


@router.post("/invoices/{invoice_id}/deletion", summary="Delete reviewed related documents and archive invoice")
def delete(invoice_id: int, body: DeleteConfirmation, db: Session = Depends(get_db),
           user=Depends(require_permission("invoice:admin"))):
    _scope(db, invoice_id, user)
    if not body.confirmed:
        raise HTTPException(409, "请确认删除订单及关联单据")
    try:
        return ok(deletion_service.run(db, invoice_id, user, body.expected_version))
    except (ValueError, okki_client.OkkiApiError) as exc:
        _reject(db, exc)
