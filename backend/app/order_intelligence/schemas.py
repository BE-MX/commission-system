"""订单经营智能分析 API schema。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AiBriefRequest(BaseModel):
    date_from: date
    date_to: date
    focus: Literal["executive", "marketing", "people", "customer"] = "executive"
    team: str | None = Field(None, max_length=100)
    user_id: str | None = Field(None, max_length=64)
    countries: list[str] = Field(default_factory=list, max_length=100)
    models: list[str] = Field(default_factory=list, max_length=100)
    colors: list[str] = Field(default_factory=list, max_length=100)
    sources: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_window(self):
        if self.date_from > self.date_to:
            raise ValueError("开始日期不能晚于结束日期")
        if (self.date_to - self.date_from).days > 1095:
            raise ValueError("单次分析区间不能超过 3 年")
        return self
