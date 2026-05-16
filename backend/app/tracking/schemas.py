"""物流跟踪 / 运单录入 — Schemas (合并自 schemas/tracking.py + schemas/waybill.py)"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── 物流跟踪 ────────────────────────────────────────────


class StagingCreateRequest(BaseModel):
    """运单推送到暂存表"""
    waybill_no: str
    carrier: str
    carrier_name: Optional[str] = None
    sender_name: Optional[str] = None
    sender_company: Optional[str] = None
    receiver_name: Optional[str] = None
    receiver_company: Optional[str] = None
    receiver_country: Optional[str] = None
    receiver_city: Optional[str] = None
    dingtalk_user_id: str
    dingtalk_user_name: str
    source_image_url: Optional[str] = None
    ocr_raw_text: Optional[str] = None


class StagingCreateResponse(BaseModel):
    staging_id: int
    waybill_no: str
    carrier: str
    status: str = "queued"
    message: str = "运单已进入处理队列"


class ShipmentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    waybill_no: str
    carrier: str
    carrier_name: str
    receiver_name: Optional[str] = None
    receiver_company: Optional[str] = None
    receiver_country: Optional[str] = None
    current_status: str
    current_status_text: Optional[str] = None
    current_location: Optional[str] = None
    last_event_time: Optional[datetime] = None
    estimated_delivery_date: Optional[datetime] = None
    dingtalk_user_name: str
    is_active: bool
    short_link: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TrackingEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_time: datetime
    status_code: Optional[str] = None
    description: str
    location: Optional[str] = None


class ShipmentDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    waybill_no: str
    carrier: str
    carrier_name: str
    sender_name: Optional[str] = None
    sender_company: Optional[str] = None
    receiver_name: Optional[str] = None
    receiver_company: Optional[str] = None
    receiver_country: Optional[str] = None
    receiver_city: Optional[str] = None
    current_status: str
    current_status_text: Optional[str] = None
    current_location: Optional[str] = None
    last_event_time: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    estimated_delivery_date: Optional[datetime] = None
    dingtalk_user_id: str
    dingtalk_user_name: str
    is_active: bool
    poll_count: int
    last_polled_at: Optional[datetime] = None
    poll_error: Optional[str] = None
    short_link: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    events: list[TrackingEventItem] = []


class TrackingStatsResponse(BaseModel):
    total: int = 0
    active: int = 0
    pending: int = 0
    in_transit: int = 0
    delivered: int = 0
    exception: int = 0
    customs: int = 0
    returned: int = 0


# ── 运单录入 (manual + OCR) ─────────────────────────────


class WaybillCreate(BaseModel):
    waybill_no: str = Field(..., min_length=1, max_length=50)
    carrier: Literal["FedEx", "DHL", "UPS", "未知"] = "未知"
    recipient_name: str = Field(..., min_length=1, max_length=100)
    recipient_country: str = Field(..., min_length=1, max_length=100)
    ship_date: date
    entry_source: Literal["ocr", "manual"] = "manual"

    @field_validator("ship_date")
    @classmethod
    def ship_date_not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("发件日期不能是未来日期")
        return v


class WaybillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    waybill_no: str
    carrier: str
    recipient_name: str
    recipient_country: str
    ship_date: date
    status: str
    entry_source: str
    created_by: str
    created_at: datetime


class WaybillCheckResponse(BaseModel):
    exists: bool
    data: Optional[dict] = None


class OCRUploadResponse(BaseModel):
    waybill_no: Optional[str] = None
    carrier: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_country: Optional[str] = None
    ship_date: Optional[str] = None
    ocr_confidence: Literal["high", "partial", "failed"] = "failed"
