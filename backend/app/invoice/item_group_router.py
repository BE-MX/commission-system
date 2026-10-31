"""Authenticated local-only edits to invoice item presentation groups."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import item_group_service, service
from app.invoice.schemas import InvoiceItemGroupsUpdate

router = APIRouter()


@router.patch("/invoices/{invoice_id}/item-groups", summary="Edit display-only invoice item groups without resending")
def update_item_groups(invoice_id: int, body: InvoiceItemGroupsUpdate, db: Session = Depends(get_db),
                       user=Depends(require_permission("invoice:write"))):
    try:
        invoice = item_group_service.update_local(db, invoice_id, body, user)
        db.commit()
        invoice = service.get_invoice(db, invoice.id)
        return ok(service.serialize_detail(invoice, db))
    except HTTPException:
        db.rollback()
        raise
    except ValueError as error:
        db.rollback()
        raise HTTPException(409, str(error)) from None
    except IntegrityError as error:
        db.rollback()
        logger.warning("invoice item group unique conflict: %s", error)
        print(f"[invoice] item group integrity error: {error}", flush=True)
        raise HTTPException(409, "分组键或名称已被占用，请刷新后重试") from None
    except Exception:
        db.rollback()
        raise
