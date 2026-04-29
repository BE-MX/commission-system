"""物流跟踪相关 Schema"""

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
