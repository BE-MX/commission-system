"""运单录入相关 Schema"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
