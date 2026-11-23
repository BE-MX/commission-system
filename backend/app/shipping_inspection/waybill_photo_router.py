"""Private waybill images: every read authorizes its inspection, never a public URL."""
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok
from app.core.storage import transfers
from app.shipping_inspection import file_service
from app.shipping_inspection import waybill_photo_service as service
from app.shipping_inspection.waybill_photo_models import ShippingWaybillPhoto

router = APIRouter()
_READ = ('shipping_inspection:read', 'shipping_inspection:write', 'shipping_inspection:admin')


@router.post('/shipping-inspection/records/{inspection_id}/waybill-photo')
async def capture_photo(inspection_id: int, rectified: UploadFile = File(...), original: UploadFile = File(...),
                        barcode: str = Form(''), db: Session = Depends(get_db),
                        user: dict = Depends(require_any_permission('shipping_inspection:write', 'shipping_inspection:admin')),
                        _tracking: dict = Depends(require_permission('tracking:write'))):
    from app.shipping_inspection.router import _require_inspection_scope
    inspection = _require_inspection_scope(db, user, inspection_id)
    if inspection.status != 'submitted':
        raise HTTPException(409, '验货单已变化，请刷新')
    try:
        return ok(await service.capture(db, inspection_id, int(user['sub']), rectified, original, barcode))
    except file_service.FileValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/shipping-inspection/records/{inspection_id}/waybill-photos')
def list_photos(inspection_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_READ))):
    from app.shipping_inspection.router import _require_inspection_scope
    _require_inspection_scope(db, user, inspection_id)
    return ok(service.list_photos(db, inspection_id))


@router.get('/shipping-inspection/records/{inspection_id}/waybill-photos/{photo_id}')
def read_photo(inspection_id: int, photo_id: int, variant: Literal['rectified', 'original'] = 'rectified',
               db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*_READ))):
    from app.shipping_inspection.router import _require_inspection_scope
    _require_inspection_scope(db, user, inspection_id)
    photo = db.query(ShippingWaybillPhoto).filter_by(id=photo_id, inspection_id=inspection_id).first()
    if photo is None or photo.shipment_tracking_id is None:
        raise HTTPException(404, '照片不存在')
    key = photo.rectified_path if variant == 'rectified' else photo.original_path
    return transfers.response(service.DOMAIN, key, transfers.snapshot(db, service.DOMAIN, key))


@router.get('/tracking/shipments/{shipment_id}/waybill-photos')
def shipment_photos(shipment_id: int, db: Session = Depends(get_db),
                    user: dict = Depends(require_any_permission(*_READ)),
                    _tracking: dict = Depends(require_any_permission('tracking:read', 'tracking:write'))):
    from app.shipping_inspection.router import _require_inspection_scope
    from app.tracking.models import ShipmentTracking
    from app.tracking.shipment_service import apply_data_scope
    shipment = apply_data_scope(db.query(ShipmentTracking).filter(ShipmentTracking.id == shipment_id, ShipmentTracking.deleted_at.is_(None)), db, user).first()
    if shipment is None:
        raise HTTPException(404, '运单不存在')
    rows = db.query(ShippingWaybillPhoto).filter_by(shipment_tracking_id=shipment_id).order_by(ShippingWaybillPhoto.id.desc()).all()
    allowed = set()
    for inspection_id in {p.inspection_id for p in rows}:
        try:
            _require_inspection_scope(db, user, inspection_id)
            allowed.add(inspection_id)
        except HTTPException as exc:
            if exc.status_code not in (403, 404, 422):
                raise
    return ok(service.photos_dict(db, [p for p in rows if p.inspection_id in allowed]))
