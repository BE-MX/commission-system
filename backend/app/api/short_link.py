"""短链接 API: POST /api/shortlink 生成 + GET /s/{code} 跳转"""

import logging

from fastapi import APIRouter, Depends, Path
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.short_link import ArkShortLink
from app.models.tracking import ShipmentTracking
from app.services.short_link import build_carrier_tracking_url
from app.utils.shortlink import generate_short_link

router = APIRouter()
logger = logging.getLogger("commission.shortlink")
settings = get_settings()

# 短码未命中时的兜底跳转
_FALLBACK_URL = "https://leshine.work"


class ShortLinkRequest(BaseModel):
    url: str = Field(..., min_length=1, description="原始 URL")


class ShortLinkResponse(BaseModel):
    short_url: str


@router.post("/api/shortlink", summary="生成短链", response_model=ShortLinkResponse)
def create_short_link(payload: ShortLinkRequest) -> ShortLinkResponse:
    return ShortLinkResponse(short_url=generate_short_link(payload.url))


@router.get("/s/{short_code}", summary="短链跳转")
def redirect_short_link(
    short_code: str = Path(..., min_length=1, max_length=8),
    db: Session = Depends(get_db),
):
    # 1. 优先查 ark_short_links 表(新短链)
    row = (
        db.query(ArkShortLink)
        .filter(ArkShortLink.short_code == short_code)
        .first()
    )
    if row:
        row.click_count = (row.click_count or 0) + 1
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("click_count 更新失败: %s", exc)
        return RedirectResponse(url=row.original_url, status_code=302)

    # 2. 回退查 shipment_tracking 旧承运商短码,保持已发出的钉钉链接可用
    shipment = (
        db.query(ShipmentTracking)
        .filter(ShipmentTracking.short_code == short_code)
        .first()
    )
    if shipment:
        url = build_carrier_tracking_url(shipment.carrier, shipment.waybill_no)
        return RedirectResponse(url=url, status_code=302)

    # 3. 都没命中,兜底跳转
    return RedirectResponse(url=_FALLBACK_URL, status_code=302)
