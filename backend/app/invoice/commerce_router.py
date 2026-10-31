"""Local transaction endpoints sharing invoice identity, visibility and exports."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission, require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import commerce_service, service
from app.invoice.commerce_schemas import LocalInvoiceDraft, LocalInvoiceAction, LocalInvoiceAmend
from app.invoice.native_authority import require_write
from app.invoice.read_authority import current_user as current_reader

from app.invoice.local_fulfillment_router import router as fulfillment_router

router = APIRouter()
router.include_router(fulfillment_router)
logger = logging.getLogger(__name__)


@router.get("/invoices")
def list_orders(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                keyword: str | None = Query(None, max_length=200), commerce_status: str | None = None,
                order_type: str | None = None, local_customer_id: int | None = Query(None, gt=0),
                db: Session = Depends(get_db), user=Depends(require_any_permission("invoice:read", "invoice:write"))):
    user = current_reader(db, user, "invoice:read", "invoice:write")
    from app.invoice.commerce_query_service import list_orders as query
    return ok(query(db, user, page=page, page_size=page_size, keyword=keyword, commerce_status=commerce_status,
                    order_type=order_type, local_customer_id=local_customer_id))


@router.get("/customer-options")
def customer_options(keyword: str | None = Query(None, max_length=200), page: int = Query(1, ge=1),
                     page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                     user=Depends(require_permission("invoice:write"))):
    user = current_reader(db, user, "invoice:write")
    from app.customer.option_service import options
    return ok(options(db, user, permissions=["invoice:write"], keyword=keyword, page=page, page_size=page_size))


@router.get("/reference-data")
def reference_data(db: Session = Depends(get_db), user=Depends(require_permission("invoice:write"))):
    user = current_reader(db, user, "invoice:write")
    from app.invoice.commerce_query_service import reference_data as query
    return ok(query(db))


def _write(db, command, user=None):
    try:
        invoice = command()
        invoice_id = invoice.id
        db.commit()
        return ok(service.serialize_detail(service.get_invoice(db, invoice_id), db, user))
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        from app.commerce_shadow.hooks import record_after_rollback
        record_after_rollback(db, exc)
        logger.warning("Local invoice command rejected: %s", type(exc).__name__)
        print(f"Local invoice command rejected: {type(exc).__name__}", flush=True)
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "订单编号或关联数据冲突，请刷新后重试") from exc
    except Exception as exc:
        db.rollback()
        from app.commerce_shadow.hooks import record_after_rollback
        record_after_rollback(db, exc)
        logger.exception("Local invoice command failed")
        print("Local invoice command failed; transaction rolled back", flush=True)
        raise


@router.post("/invoices", status_code=201)
def create(body: LocalInvoiceDraft, db: Session = Depends(get_db),
           user=Depends(require_permission("invoice:write"))):
    user = require_write(db, user, "invoice:write")
    return _write(db, lambda: commerce_service.create_draft(db, body, user), user)


@router.put("/invoices/{invoice_id}")
def update(invoice_id: int, body: LocalInvoiceDraft, db: Session = Depends(get_db),
           user=Depends(require_permission("invoice:write"))):
    user = require_write(db, user, "invoice:write")
    return _write(db, lambda: commerce_service.update_draft(db, invoice_id, body, user), user)


@router.post("/invoices/{invoice_id}/confirm")
def confirm(invoice_id: int, body: LocalInvoiceAction, db: Session = Depends(get_db),
            user=Depends(require_permission("invoice:write"))):
    user = require_write(db, user, "invoice:write")
    return _write(db, lambda: commerce_service.confirm(db, invoice_id, body, user), user)


@router.post("/invoices/{invoice_id}/cancel")
def cancel(invoice_id: int, body: LocalInvoiceAction, db: Session = Depends(get_db),
           user=Depends(require_permission("invoice:write"))):
    user = require_write(db, user, "invoice:write")
    return _write(db, lambda: commerce_service.cancel(db, invoice_id, body, user), user)


@router.post("/invoices/{invoice_id}/amend")
def amend(invoice_id: int, body: LocalInvoiceAmend, db: Session = Depends(get_db),
          user=Depends(require_permission("invoice:write"))):
    user = require_write(db, user, "invoice:write")
    return _write(db, lambda: commerce_service.amend(db, invoice_id, body, user), user)
