"""产品风向标请求模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class MappingSaveItem(BaseModel):
    id: int = Field(..., gt=0)
    status: Literal["suggested", "confirmed", "ignored"]
    model: str | None = Field(None, max_length=200)
    unit_grams: float | None = None


class MappingSaveRequest(BaseModel):
    items: list[MappingSaveItem] = Field(..., min_length=1, max_length=200)


class InsightRequest(BaseModel):
    refresh: bool = False
    dimension: Literal["color_size", "category", "item"]
    key: str = Field(..., min_length=1, max_length=512)
    window: int = 90
    user_id: str | None = Field(None, max_length=64)
    team: str | None = Field(None, max_length=100)
