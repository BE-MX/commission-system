"""色板库（公库 / 私库）请求体。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class LibrarySwatchCreate(BaseModel):
    library_scope: Literal["public", "private"]
    customer_id: Optional[int] = Field(None, description="私库必填")
    color_code: str = Field(..., min_length=1, max_length=30)
    size_value: float = Field(..., gt=0, le=9999)
    size_unit: Literal["inch", "cm"] = "inch"
    display_name: Optional[str] = Field(None, max_length=100)
    base_swatch_id: Optional[int] = None
    base_palette_id: Optional[int] = None
    tolerance_de: float = Field(1.5, gt=0, le=99)


class LibrarySwatchUpdate(BaseModel):
    color_code: Optional[str] = Field(None, min_length=1, max_length=30)
    size_value: Optional[float] = Field(None, gt=0, le=9999)
    size_unit: Optional[Literal["inch", "cm"]] = None
    display_name: Optional[str] = Field(None, max_length=100)
    base_swatch_id: Optional[int] = None
    base_palette_id: Optional[int] = None
    tolerance_de: Optional[float] = Field(None, gt=0, le=99)


class MeasurementIn(BaseModel):
    client_request_id: str = Field(..., min_length=1, max_length=64)
    source: Literal["device", "simulation", "manual"] = "device"
    receipt_status: Optional[Literal["matched", "late", "manual"]] = None
    record_type: Literal["standard", "batch"] = "standard"
    position_tag: Optional[str] = Field(None, max_length=64)
    lab: List[float] = Field(..., min_length=3, max_length=3)
    luv: Optional[List[float]] = Field(None, min_length=3, max_length=3)
    lch: Optional[List[float]] = Field(None, min_length=3, max_length=3)
    yxy: Optional[List[float]] = Field(None, min_length=3, max_length=3)
    cmyk: Optional[List[int]] = Field(None, min_length=4, max_length=4)
    rgb: Optional[List[int]] = Field(None, min_length=3, max_length=3)
    raw_hex: Optional[str] = Field(None, max_length=4096, pattern=r"^[0-9A-Fa-f]*$")
    device_name: Optional[str] = Field(None, max_length=64)
    device_sn: Optional[str] = Field(None, max_length=32)
    device_fw: Optional[str] = Field(None, max_length=16)
    session_id: Optional[str] = Field(None, max_length=64)
    requested_at: Optional[datetime] = None
    received_at: Optional[datetime] = None


class MeasurementBatch(BaseModel):
    items: List[MeasurementIn] = Field(..., min_length=1, max_length=20)


class InclusionUpdate(BaseModel):
    is_included: bool
    reason: Optional[str] = Field(None, max_length=255)


class PromotionReview(BaseModel):
    approve: bool
