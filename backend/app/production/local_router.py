"""Local manufacturing and acceptance API, sharing existing production RBAC."""
import logging
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.auth.models import ArkUser
from app.core.database import get_db
from app.invoice.native_authority import require_write
from app.invoice.read_authority import current_user as read_current_user
from app.core.response import ok
from app.production import local_service as service
from app.production.local_receipt_service import reverse_receipt
from app.production.local_schemas import ProductionCreate, QuantityCommand, SupplyCreate, ReceiptCreate, MaterialCommand, Action, LocalReport
from app.production import local_read_service as reads

router = APIRouter()
logger = logging.getLogger(__name__)


def write(db, command, serialize):
    try:
        row = command()
        result = serialize(row)
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        logger.warning("Local production command rejected: %s", type(exc).__name__)
        print(f"Local production command rejected: {type(exc).__name__}", flush=True)
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "生产批次或关联数据冲突，请刷新核对") from exc
    except Exception:
        db.rollback()
        logger.exception("Local production command failed")
        print("Local production command failed; rolled back", flush=True)
        raise


@router.get("/orders")
def orders(keyword: str | None = Query(None, max_length=128), status: int | None = Query(None, ge=0, le=2),
           page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
           user=Depends(require_permission("production:read"))):
    user = read_current_user(db, user, 'production:read')
    return ok(reads.list_orders(db, keyword, status, page, page_size))


@router.get('/reference-data')
def reference(db: Session = Depends(get_db), user=Depends(require_permission('production:read'))):
    user = read_current_user(db, user, 'production:read')
    return ok(reads.reference_data(db))


@router.get('/supply-options')
def supply_options(item_id: int = Query(..., gt=0), keyword: str | None = Query(None, max_length=128),
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                   db: Session = Depends(get_db), user=Depends(require_permission('production:write'))):
    user = read_current_user(db, user, 'production:write')
    return ok(reads.supply_options(db, item_id, user, keyword, page, page_size))


@router.get('/material-options')
def material_options(item_id: int | None = Query(None, gt=0), keyword: str | None = Query(None, max_length=128),
                     page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
                     db: Session = Depends(get_db), user=Depends(require_permission('semifinished:write'))):
    user = read_current_user(db, user, 'semifinished:write')
    return ok(reads.material_options(db, keyword, item_id, page, page_size))


@router.get("/orders/{order_id}")
def order(order_id: int, db: Session = Depends(get_db), user=Depends(require_permission("production:read"))):
    user = read_current_user(db, user, 'production:read')
    return ok(service.describe(db, order_id))


@router.post("/orders", status_code=201)
def create(body: ProductionCreate, db: Session = Depends(get_db), user=Depends(require_permission("production:write"))):
    user = require_write(db, user, 'production:write')
    return write(db, lambda: service.create(db, body, user), lambda row: service.describe(db, row.id))


@router.get("/in-transit")
def transit(db: Session = Depends(get_db), user=Depends(require_permission("production:read"))):
    user = read_current_user(db, user, 'production:read')
    return ok({"items": service.in_transit(db)})


@router.post("/items/{item_id}/complete")
def complete(item_id: int, body: QuantityCommand, db: Session = Depends(get_db), user=Depends(require_permission("production:admin"))):
    user = require_write(db, user, 'production:admin')
    return write(db, lambda: service.complete(db, item_id, body, user), lambda row: service.describe(db, row.order_id))


@router.post("/items/{item_id}/terminate")
def terminate(item_id: int, body: Action, db: Session = Depends(get_db), user=Depends(require_permission("production:admin"))):
    user = require_write(db, user, 'production:admin')
    return write(db, lambda: service.terminate(db, item_id, body, user), lambda row: service.describe(db, row.order_id))


@router.post("/items/{item_id}/supplies")
def link_supply(item_id: int, body: SupplyCreate, db: Session = Depends(get_db), user=Depends(require_permission("production:write"))):
    user = require_write(db, user, 'production:write')
    return write(db, lambda: service.link_supply(db, item_id, body, user), lambda row: {"id": row.id})


@router.post("/supplies/{supply_id}/release")
def release_supply(supply_id: int, body: QuantityCommand, db: Session = Depends(get_db), user=Depends(require_permission("production:write"))):
    user = require_write(db, user, 'production:write')
    return write(db, lambda: service.release_supply(db, supply_id, body, user), lambda row: {"id": row.id})


@router.post("/items/{item_id}/receive")
def receive(item_id: int, body: ReceiptCreate, db: Session = Depends(get_db), user=Depends(require_permission("inventory:write"))):
    user = require_write(db, user, 'inventory:write')
    return write(db, lambda: service.receive(db, item_id, body, user), lambda row: service.describe(db, row.order_id))


@router.post("/items/{item_id}/materials/{kind}")
def material(item_id: int, kind: Literal["issue", "return", "loss"], body: MaterialCommand, db: Session = Depends(get_db),
             user=Depends(require_permission("semifinished:write"))):
    user = require_write(db, user, 'semifinished:write')
    return write(db, lambda: service.material(db, item_id, kind, body, user), lambda row: service.describe(db, row.order_id))


@router.post("/receipts/{event_id}/reverse")
def reverse(event_id: int, body: Action, db: Session = Depends(get_db), user=Depends(require_permission("inventory:admin"))):
    user = require_write(db, user, 'inventory:admin')
    return write(db, lambda: reverse_receipt(db, event_id, body, user), lambda row: service.describe(db, row.order_id))


@router.post("/report")
def report(body: LocalReport, db: Session = Depends(get_db), user=Depends(require_permission("production:write"))):
    user = require_write(db, user, 'production:write')
    from app.production.local_report_service import submit
    worker = db.get(ArkUser, int(user["sub"]))
    if worker is None or not worker.is_active:
        raise HTTPException(403, "报工用户不存在或已停用")
    return write(db, lambda: submit(db, body.progress_id, body.item_id, worker), lambda result: result)
