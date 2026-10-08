"""Bounded analytical queries; client input can only narrow live authorization."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PRODUCT_FIELDS = ("product_type", "craft", "net_color", "size", "length", "density", "hair_style_series", "color")
CUSTOMER_FIELDS = ("province", "city", "customer_source", "store_type", "settle_mode", "membership_level")
ORDER_FIELDS = ("order_category", "order_type", "order_channel")
DIMENSIONS = PRODUCT_FIELDS + CUSTOMER_FIELDS + ORDER_FIELDS


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    end_date: date
    comparison_mode: Literal["previous", "year", "none"] = "previous"
    scope: Literal["mine", "all"] = "mine"
    customer_ids: list[int] = Field(default_factory=list, max_length=500)
    owner_ids: list[int] = Field(default_factory=list, max_length=100)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    dimensions: list[str] = Field(default_factory=lambda: ["craft", "length"], max_length=2)
    metric: Literal["amount", "quantity", "order_count", "customer_count"] = "amount"
    finance_related_customers: bool = False

    @model_validator(mode="after")
    def bounded_query(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days + 1 > 1096:
            raise ValueError("时间范围须为 1 至 1096 天")
        if any(x not in DIMENSIONS for x in self.dimensions) or len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("无效或重复分析维度")
        if any(x not in DIMENSIONS for x in self.filters):
            raise ValueError("无效筛选字段")
        if any(len(values) > 100 or any(len(x) > 255 for x in values) for values in self.filters.values()):
            raise ValueError("筛选值超限")
        if any(x <= 0 for x in self.customer_ids + self.owner_ids):
            raise ValueError("客户和业务员 ID 必须为正整数")
        return self
