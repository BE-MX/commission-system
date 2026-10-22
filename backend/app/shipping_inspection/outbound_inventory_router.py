"""Read-only inventory details under the existing outbound visibility boundary."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.shipping_inspection import outbound_inventory_service as inventory, outbound_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post('/outbound-records/{record_id}/replenishment-sync', summary='补货后立即核库存并生成原出库单')
def replenishment_sync(record_id: str, response: Response, db: Session = Depends(get_db),
                       user=Depends(require_permission('shipping_inspection:write')),
                       _sync=Depends(require_permission('invoice:sync'))):
    from app.shipping_inspection.replenishment_service import synchronize
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return ok(synchronize(db, record_id, user))
    except (ValueError, RuntimeError) as error:
        db.rollback()
        logger.warning('Outbound replenishment unavailable (%s)', type(error).__name__)
        print('[outbound-replenishment] original task requires review', flush=True)
        raise HTTPException(409, '补货同步暂不可执行，请刷新核对原任务') from None


@router.get('/outbound-records/{record_id}/inventory', summary='出库单对应库存与缺口详情（只读镜像）')
def outbound_inventory(record_id: str, response: Response, db: Session = Depends(get_db),
                       user: dict = Depends(require_any_permission(
                           'shipping_inspection:read', 'shipping_inspection:write', 'shipping_inspection:admin'))):
    from app.shipping_inspection.router import _outbound_scope
    response.headers['Cache-Control'] = 'private, no-store'
    try:
        return ok(inventory.inventory_details(db, record_id, okki_user_id=_outbound_scope(db, user)))
    except (outbound_service.OutboundTableError, SQLAlchemyError) as exc:
        logger.warning('Outbound inventory mirror schema unavailable: %s', type(exc).__name__)
        print('[outbound-inventory] mirror schema unavailable', flush=True)
        raise HTTPException(503, '库存镜像暂不可用，请稍后重试') from exc
