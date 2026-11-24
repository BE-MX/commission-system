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
    """大类 AI 分析：公司口径，不带份额参数。"""

    refresh: bool = False
    grade: Literal["B1", "B3", "50"]
    window: int = 90
