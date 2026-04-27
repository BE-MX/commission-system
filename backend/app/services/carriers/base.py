"""物流商适配器基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TrackingEvent:
    event_time: datetime
    description: str
    location: str
    status_code: str
    raw: dict = field(default_factory=dict)


@dataclass
class TrackingResult:
    success: bool
    waybill_no: str
    current_status: str
    current_status_text: str
    current_location: str
    last_event_time: Optional[datetime]
    events: list[TrackingEvent]
    error: Optional[str] = None


STATUS_MAP_CN = {
    "pending": "待查询",
    "picked_up": "已揽收",
    "in_transit": "运输中",
    "out_for_delivery": "派送中",
    "customs": "清关中",
    "customs_hold": "海关扣留",
    "delivered": "已签收",
    "returned": "已退回",
    "exception": "异常",
}


class CarrierAdapter(ABC):
    @abstractmethod
    async def track(self, waybill_no: str) -> TrackingResult:
        ...
