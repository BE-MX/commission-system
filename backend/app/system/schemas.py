"""系统字典 — Pydantic 模式"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DictItemCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    sort: int = 0
    is_active: bool = True
    remark: Optional[str] = None


class DictItemUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=128)
    sort: Optional[int] = None
    is_active: Optional[bool] = None
    remark: Optional[str] = None


class DictItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    code: str
    label: str
    sort: int
    is_active: bool
    remark: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DictTypeStat(BaseModel):
    type: str
    item_count: int
    active_count: int
