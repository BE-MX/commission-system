"""Mobile queue and read-only synchronization endpoints."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission
from app.auth.service import get_live_user_authorization
from app.core.database import get_db
from app.core.response import ok
from app.shipping_inspection.schemas import InspectionShipmentPreview

router = APIRouter()
EDIT = ('shipping_inspection:write', 'shipping_inspection:admin')


@router.get('/mobile/waybill-queue')
def waybill_queue(tab: Literal['pending', 'done'] = 'pending', keyword: str | None = Query(None, max_length=100),
                  include_older: bool = False, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                  db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*EDIT))):
    from app.shipping_inspection.waybill_queue_service import queue
    roles, permissions = get_live_user_authorization(db, int(user['sub']))
    return ok(queue(db, int(user['sub']), roles, permissions, tab=tab, keyword=keyword,
                    include_older=include_older, page=page, page_size=page_size))


@router.post('/records/{inspection_id}/shipment-preview')
async def shipment_preview(inspection_id: int, body: InspectionShipmentPreview, db: Session = Depends(get_db),
                           user: dict = Depends(require_any_permission(*EDIT))):
    from app.shipping_inspection.router import _require_inspection_scope
    from app.shipping_inspection.waybill_preview_service import preview
    inspection = _require_inspection_scope(db, user, inspection_id)
    roles, permissions = get_live_user_authorization(db, int(user['sub']))
    try:
        return ok(await preview(db, inspection, body, int(user['sub']), roles, permissions))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
