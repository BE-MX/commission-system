"""Typed shipment and receipt payloads."""
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, model_validator
from app.core.time import beijing_today, to_beijing_naive


class ShipmentItemInput(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=2000)
    unit_ids: list[int] | None = Field(None, max_length=2000)
    ship_weight: Decimal | None = Field(None, gt=0, le=100000)
    unit_price: Decimal | None = Field(None, ge=0, le=Decimal("999999999999.99"), decimal_places=2)

    @model_validator(mode="after")
    def check_units(self):
        if self.unit_ids is not None and (
            len(self.unit_ids) != self.quantity or len(set(self.unit_ids)) != self.quantity
            or any(value <= 0 for value in self.unit_ids)
        ):
            raise ValueError("指定件数必须与发货数量一致，且不能重复")
        return self


class ShipmentCreate(BaseModel):
    customer_id: int = Field(gt=0)
    ship_time: datetime
    request_id: str = Field(min_length=8, max_length=64)
    remark: str | None = Field(None, max_length=500)
    items: list[ShipmentItemInput] = Field(min_length=1, max_length=200)

    @field_validator("ship_time")
    @classmethod
    def normalize_time(cls, value):
        return to_beijing_naive(value)

    @model_validator(mode="after")
    def unique_items(self):
        if len({row.item_id for row in self.items}) != len(self.items):
            raise ValueError("同一明细不能重复选择")
        return self


class ShipmentReceive(BaseModel):
    received_date: date

    @field_validator("received_date")
    @classmethod
    def not_future(cls, value):
        if value > beijing_today():
            raise ValueError("收货日期不能晚于今天")
        return value


class ReceiptAllocationInput(BaseModel):
    shipment_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=Decimal("999999999999.99"), decimal_places=2)


class ReceiptCreate(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    receipt_date: date
    amount: Decimal = Field(gt=0, le=Decimal("999999999999.99"), decimal_places=2)
    remark: str | None = Field(None, max_length=500)
    allocations: list[ReceiptAllocationInput] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_allocations(self):
        if len({row.shipment_id for row in self.allocations}) != len(self.allocations):
            raise ValueError("同一批次不能重复核销")
        if sum((row.amount for row in self.allocations), Decimal(0)) > self.amount:
            raise ValueError("核销合计不能超过收款金额")
        if self.receipt_date > beijing_today():
            raise ValueError("收款日期不能晚于今天")
        return self
