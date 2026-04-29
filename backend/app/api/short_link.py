"""短链接 302 重定向端点"""

from fastapi import APIRouter, Path
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from app.api.deps import get_db
from app.models.tracking import ShipmentTracking
from app.services.short_link import build_carrier_tracking_url

router = APIRouter()


@router.get("/s/{code}", summary="短链接跳转物流官网")
def redirect_short_link(
    code: str = Path(..., min_length=8, max_length=8),
    db: Session = Depends(get_db),
):
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.short_code == code)
        .first()
    )
    if not shipment:
        return {"code": 404, "message": "短链接不存在", "data": None}

    url = build_carrier_tracking_url(shipment.carrier, shipment.waybill_no)
    return RedirectResponse(url=url, status_code=302)
