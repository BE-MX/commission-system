"""半成品领域请求模型。"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ComponentInput(BaseModel):
    material_id: int
    ratio: Decimal = Field(gt=0, le=1)


class MappingUpdate(BaseModel):
    components: list[ComponentInput] = Field(min_length=1)

    @model_validator(mode="after")
    def ratios_sum_to_one(self):
        if abs(sum((item.ratio for item in self.components), Decimal("0")) - Decimal("1")) > Decimal("0.000001"):
            raise ValueError("半成品配比总和必须等于1")
        if len({item.material_id for item in self.components}) != len(self.components):
            raise ValueError("半成品不能重复")
        return self


class QuoteRequest(BaseModel):
    product_id: int
    finished_qty: int = Field(gt=0, le=999999)


class QuantityItem(BaseModel):
    material_id: int
    quantity_grams: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    remark: str | None = Field(None, max_length=500)


class OrderCreate(BaseModel):
    items: list[QuantityItem] = Field(min_length=1)
    batch_no: str | None = Field(None, max_length=64)
    is_urgent: bool = False
    expected_delivery_date: date | None = None
    remark: str | None = Field(None, max_length=500)


class ReceiptCreate(BaseModel):
    quantity_grams: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    idempotency_key: str = Field(min_length=8, max_length=128)
    remark: str | None = Field(None, max_length=500)


class OrderStatusUpdate(BaseModel):
    status: Literal["terminated"]


class InventoryAdjustment(BaseModel):
    quantity_grams: Decimal = Field(max_digits=14, decimal_places=3)
    idempotency_key: str = Field(min_length=8, max_length=128)
    remark: str = Field(min_length=2, max_length=500)


class AllocationRecovery(BaseModel):
    action: Literal["finalize", "release"]


class CartPlanInput(BaseModel):
    material_id: int
    quantity_grams: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
