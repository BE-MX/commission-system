"""Privileged preview/apply boundary for reviewed source data."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth.dependencies import require_permission
from app.invoice import native_authority, read_authority
from app.core.database import get_db
from app.core.response import ok
from app.commerce_migration import service, inventory_service, finance_service, order_service, fulfillment_service, production_service
from app.commerce_migration.inventory_schemas import InventoryOpeningManifest
from app.commerce_migration.schemas import ImportManifest
from app.commerce_migration.finance_schemas import FinanceOpeningManifest
from app.commerce_migration.order_schemas import OrderOpeningManifest
from app.commerce_migration.fulfillment_schemas import FulfillmentOpeningManifest
from app.commerce_migration.production_schemas import ProductionOpeningManifest
from app.commerce_migration.activation_schemas import ActivationManifest, ActivationSelection
from app.commerce_migration import activation_service
from app.commerce_migration.material_schemas import MaterialOpeningManifest
from app.commerce_migration import material_service
from app.commerce_migration.material_pending_schemas import MaterialResolutionManifest
from app.commerce_migration import material_pending_service
from app.commerce_migration.settlement_schemas import SettlementManifest
from app.commerce_migration import settlement_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('/settlement/preview')
def settlement_preview(body: SettlementManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(settlement_service.preview(db, body))


@router.post('/settlement')
def settlement_apply(body: SettlementManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: settlement_service.apply(db, body, user))


@router.post('/preview')
def preview(body: ImportManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(service.preview(db, body))


@router.post('/batches')
def apply(body: ImportManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: service.apply_manifest(db, body, user))


@router.post('/inventory/preview')
def inventory_preview(body: InventoryOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(inventory_service.preview(db, body))


@router.post('/inventory/batches')
def inventory_apply(body: InventoryOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: inventory_service.apply_manifest(db, body, user))


@router.post('/finance/preview')
def finance_preview(body: FinanceOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(finance_service.preview(db, body))


@router.post('/finance/batches')
def finance_apply(body: FinanceOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: finance_service.apply_manifest(db, body, user))


@router.post('/orders/preview')
def order_preview(body: OrderOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(order_service.preview(db, body))


@router.post('/orders/batches')
def order_apply(body: OrderOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: order_service.apply_manifest(db, body, user))


@router.post('/fulfillment/preview')
def fulfillment_preview(body: FulfillmentOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(fulfillment_service.preview(db, body))


@router.post('/fulfillment/batches')
def fulfillment_apply(body: FulfillmentOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: fulfillment_service.apply_manifest(db, body, user))


@router.post('/production/preview')
def production_preview(body: ProductionOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(production_service.preview(db, body))


@router.post('/production/batches')
def production_apply(body: ProductionOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: production_service.apply_manifest(db, body, user))


@router.post('/activation/preview')
def activation_preview(body: ActivationManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(activation_service.preview(db, body))


@router.post('/activation/prepare')
def activation_prepare(body: ActivationSelection, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    try:
        return ok(activation_service.prepare(db, body))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/activation')
def activation_apply(body: ActivationManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: activation_service.activate(db, body, user))


@router.post('/materials/preview')
def material_preview(body: MaterialOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(material_service.preview(db, body))


@router.post('/materials/batches')
def material_apply(body: MaterialOpeningManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: material_service.apply_manifest(db, body, user))


@router.post('/materials/pending/preview')
def pending_material_preview(body: MaterialResolutionManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(material_pending_service.preview(db, body))


@router.post('/materials/pending/batches')
def pending_material_apply(body: MaterialResolutionManifest, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = native_authority.require_write(db, user, "commerce_migration:admin")
    return _write(db, lambda: material_pending_service.apply_manifest(db, body, user))


def _write(db, command):
    try:
        result = command()
        db.commit()
        return ok(result)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        logger.warning('Commerce import rejected: %s', type(exc).__name__)
        print(f'Commerce import rejected: {type(exc).__name__}', flush=True)
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else '来源身份或目标关联冲突，请重新预览') from exc
    except Exception:
        db.rollback()
        logger.exception('Commerce import failed; transaction rolled back')
        print('Commerce import failed; transaction rolled back', flush=True)
        raise


@router.get('/batches/{batch_key}')
def batch(batch_key: str, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(service.describe_batch(db, batch_key))


@router.get('/records')
def records(source: str | None = Query(None, max_length=32), tenant: str | None = Query(None, max_length=64),
            object_type: str | None = Query(None, max_length=32), after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
            db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(service.list_records(db, source=source, tenant=tenant, object_type=object_type, after_id=after_id, limit=limit))


@router.get('/records/page')
def records_page(source: str | None = Query(None, max_length=32), tenant: str | None = Query(None, max_length=64),
                 object_type: str | None = Query(None, max_length=32), role: str | None = Query(None, max_length=16),
                 page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(service.record_page(db, source=source, tenant=tenant, object_type=object_type, role=role, page=page, page_size=page_size))


@router.get('/records/{record_id}')
def record_detail(record_id: int, db: Session = Depends(get_db), user=Depends(require_permission('commerce_migration:admin'))):
    user = read_authority.current_user(db, user, "commerce_migration:admin")
    return ok(service.describe_record(db, record_id))
