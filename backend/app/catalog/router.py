"""Catalog HTTP boundary; all mutations commit or roll back as one request."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.catalog import service
from app.catalog.schemas import ProductCreate, ProductUpdate, SkuCreate, SkuStatus
from app.core.database import get_db
from app.core.response import ok
from app.invoice.native_authority import require_write
from app.invoice.read_authority import current_user as current_reader

router = APIRouter()
logger = logging.getLogger(__name__)


def _write(db, fn, *args):
    try:
        result = fn(db, *args)
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        logger.warning("Catalog command rejected: %s", type(exc).__name__)
        print(f"Catalog command rejected: {type(exc).__name__}", flush=True)
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "编码或关联冲突，请刷新后重试") from exc
    except Exception:
        db.rollback()
        logger.exception("Catalog command failed")
        print("Catalog command failed; transaction rolled back", flush=True)
        raise


@router.get("/products")
def products(keyword: str | None = Query(None, max_length=128), active: bool | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
             db: Session = Depends(get_db),
             _user=Depends(require_any_permission("catalog:read", "invoice:write", "inventory:read", "production:write"))):
    _user = current_reader(db, _user, 'catalog:read', 'invoice:write', 'inventory:read', 'production:write')
    return ok(service.list_products(db, keyword, active, page, page_size))


@router.post("/products")
def create_product(body: ProductCreate, db: Session = Depends(get_db),
                   _user=Depends(require_permission("catalog:write"))):
    _user = require_write(db, _user, 'catalog:write')
    return _write(db, service.create_product, body)


@router.put("/products/{product_id}")
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db),
                   _user=Depends(require_permission("catalog:write"))):
    _user = require_write(db, _user, 'catalog:write')
    return _write(db, service.update_product, product_id, body)


@router.post("/products/{product_id}/skus")
def create_sku(product_id: int, body: SkuCreate, db: Session = Depends(get_db),
               _user=Depends(require_permission("catalog:write"))):
    _user = require_write(db, _user, 'catalog:write')
    return _write(db, service.create_sku, product_id, body)


@router.put("/skus/{sku_id}/status")
def sku_status(sku_id: int, body: SkuStatus, db: Session = Depends(get_db),
               _user=Depends(require_permission("catalog:write"))):
    _user = require_write(db, _user, 'catalog:write')
    return _write(db, service.set_sku_status, sku_id, body.active)


@router.put("/skus/{sku_id}")
def update_sku(sku_id: int, body: SkuCreate, db: Session = Depends(get_db),
               _user=Depends(require_permission("catalog:write"))):
    _user = require_write(db, _user, 'catalog:write')
    return _write(db, service.update_sku, sku_id, body)
