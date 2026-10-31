"""Local fulfillment endpoints reuse existing shipment and inspection rights."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission, require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.invoice import commerce_service, local_fulfillment as service, read_authority
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentSettlement
from app.invoice.local_fulfillment_schemas import LocalShipmentQuote, LocalShipmentCreate, LocalShipmentAction
from app.receipt.router import execute
from app.invoice.native_authority import require_write

router = APIRouter()


@router.get('/shipments')
def list_shipments(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
                   keyword: str | None = Query(None, max_length=200), invoice_id: int | None = Query(None, gt=0),
                   state: str | None = Query(None, max_length=32), db: Session = Depends(get_db),
                   user=Depends(require_any_permission('invoice:read', 'shipment:read', 'shipment:write'))):
    user = read_authority.current_user(db, user, 'invoice:read', 'shipment:read', 'shipment:write')
    from app.invoice.service import _visible_invoice_query
    all_access = 'super_admin' in user['roles'] or 'invoice:read_all' in user['permissions']
    visible = _visible_invoice_query(db, viewer_user_id=None if all_access else int(user['sub'])).with_entities(Invoice.id)
    from app.invoice.native_visibility import local_invoice_scope
    visible = visible.filter(local_invoice_scope(db, user, read_permissions=('invoice:read', 'shipment:read', 'shipment:write')))
    query = db.query(ShipmentSettlement).join(Invoice, Invoice.id == ShipmentSettlement.invoice_id).filter(
        Invoice.transaction_mode == 'local', Invoice.id.in_(visible.statement))
    if keyword:
        term = f'%{keyword.strip()}%'
        query = query.filter(Invoice.invoice_no.ilike(term) | Invoice.customer_name.ilike(term) |
                             ShipmentSettlement.settlement_no.ilike(term))
    if invoice_id is not None:
        query = query.filter(Invoice.id == invoice_id)
    if state:
        query = query.filter(ShipmentSettlement.state == state)
    total = query.count()
    rows = query.order_by(ShipmentSettlement.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok({'items': [service.describe(db, row, user) for row in rows], 'total': total,
               'page': page, 'page_size': page_size})


@router.post("/invoices/{invoice_id}/shipment-quotes")
def quote(invoice_id: int, body: LocalShipmentQuote, db: Session = Depends(get_db),
          user=Depends(require_any_permission("shipment:read", "shipment:write"))):
    user = require_write(db, user, "shipment:read", "shipment:write", any_permission=True)
    return execute(db, lambda: service.quote(db, invoice_id, body, user))


@router.post("/invoices/{invoice_id}/shipments", dependencies=[Depends(require_permission("invoice:write"))])
def create(invoice_id: int, body: LocalShipmentCreate, db: Session = Depends(get_db),
           user=Depends(require_permission("shipment:write"))):
    user = require_write(db, user, "shipment:write", "invoice:write")
    return execute(db, lambda: service.describe(db, service.create(db, invoice_id, body, user), user))


@router.get("/invoices/{invoice_id}/shipments")
def for_order(invoice_id: int, db: Session = Depends(get_db),
              user=Depends(require_any_permission("shipment:read", "shipment:write"))):
    user = read_authority.current_user(db, user, "shipment:read", "shipment:write")
    def read():
        commerce_service._get(db, invoice_id, user)
        rows = db.scalars(select(ShipmentSettlement).where(ShipmentSettlement.invoice_id == invoice_id)
                          .order_by(ShipmentSettlement.sequence.desc())).all()
        return {"items": [service.describe(db, row, user) for row in rows]}
    return execute(db, read)


@router.post("/shipments/{identity}/{operation}")
def action(identity: int, operation: str, body: LocalShipmentAction, db: Session = Depends(get_db),
           user=Depends(require_permission("shipment:write"))):
    if operation not in {"ready", "release_funding", "cancel", "ship"}:
        raise HTTPException(404, "发货动作不存在")
    user = require_write(db, user, "shipment:write", *(("inventory:write", "invoice:write") if operation == "ship" else ()))
    return execute(db, lambda: service.describe(db, service.act(db, identity, body, user, operation), user))
