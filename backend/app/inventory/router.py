"""Warehouse and stock posting endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.invoice.native_authority import require_write
from app.invoice.read_authority import current_user as read_current_user
from app.core.response import ok
from app.inventory import service
from app.inventory.schemas import DocumentCreate, ReversalCreate, WarehouseCreate

router = APIRouter()
logger = logging.getLogger(__name__)


def _write(db, operation):
    try:
        result = operation()
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        logger.warning("Inventory command rejected: %s", type(exc).__name__)
        print(f"Inventory command rejected: {type(exc).__name__}", flush=True)
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "库存关联冲突，请刷新后重试") from exc
    except Exception:
        db.rollback()
        logger.exception("Inventory command failed")
        print("Inventory command failed; transaction rolled back", flush=True)
        raise


@router.get("/warehouses")
def warehouses(db: Session = Depends(get_db), _user=Depends(require_permission("inventory:read"))):
    _user = read_current_user(db, _user, 'inventory:read')
    return ok(service.list_warehouses(db))


@router.post("/warehouses")
def create_warehouse(body: WarehouseCreate, db: Session = Depends(get_db),
                     _user=Depends(require_permission("inventory:admin"))):
    _user = require_write(db, _user, 'inventory:admin')
    return _write(db, lambda: service.create_warehouse(db, body))


@router.get("/balances")
def balances(warehouse_id: int | None = Query(None, gt=0), sku_id: int | None = Query(None, gt=0),
             offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
             db: Session = Depends(get_db), _user=Depends(require_permission("inventory:read"))):
    _user = read_current_user(db, _user, 'inventory:read')
    return ok(service.list_balances(db, warehouse_id=warehouse_id, sku_id=sku_id, offset=offset, limit=limit))


@router.get("/documents")
def documents(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
              db: Session = Depends(get_db), _user=Depends(require_permission("inventory:read"))):
    _user = read_current_user(db, _user, 'inventory:read')
    return ok(service.list_documents(db, offset, limit))


@router.get("/ledger")
def ledger(warehouse_id: int | None = Query(None, gt=0), sku_id: int | None = Query(None, gt=0),
           offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
           db: Session = Depends(get_db), _user=Depends(require_permission("inventory:read"))):
    _user = read_current_user(db, _user, 'inventory:read')
    return ok(service.list_ledger(db, warehouse_id=warehouse_id, sku_id=sku_id, offset=offset, limit=limit))


@router.get("/documents/{document_id}")
def document(document_id: int, db: Session = Depends(get_db),
             _user=Depends(require_permission("inventory:read"))):
    _user = read_current_user(db, _user, 'inventory:read')
    try:
        return ok(service.get_document(db, document_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/documents")
def post(body: DocumentCreate, db: Session = Depends(get_db),
         user=Depends(require_permission("inventory:write"))):
    user = require_write(db, user, 'inventory:write')
    if body.kind in {"opening", "adjustment", "count"}:
        require_permission("inventory:admin")(user)
    return _write(db, lambda: service.document_dict(service.post_document(db, body, actor_id=int(user["sub"]))))


@router.post("/documents/{document_id}/reversal")
def reversal(document_id: int, body: ReversalCreate, db: Session = Depends(get_db),
             user=Depends(require_permission("inventory:admin"))):
    user = require_write(db, user, 'inventory:admin')
    return _write(db, lambda: service.document_dict(service.reverse_document(
        db, document_id, body.idempotency_key, body.reason, int(user["sub"]))))
