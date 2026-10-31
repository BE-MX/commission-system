"""Local manufacturing commands with strict piece/gram units."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Piece = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=64)


class ProductionLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_sku_id: int = Field(gt=0)
    quantity: Piece
    process_route_id: int | None = Field(default=None, gt=0)
    expected_delivery_date: date | None = None
    remark: str = Field(default="", max_length=500)


class ProductionCreate(Command):
    batch_no: str = Field(min_length=1, max_length=64)
    remark: str = Field(default="", max_length=500)
    items: list[ProductionLine] = Field(min_length=1, max_length=100)


class Action(Command):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class QuantityCommand(Action):
    quantity: Piece


class SupplyCreate(QuantityCommand):
    invoice_item_id: int = Field(gt=0)


class ReceiptAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supply_id: int = Field(gt=0)
    quantity: Piece


class ReceiptCreate(QuantityCommand):
    warehouse_id: int = Field(gt=0)
    quality: Literal["sellable", "quarantine", "damaged"] = "sellable"
    allocations: list[ReceiptAllocation] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def distribution(self):
        if len({x.supply_id for x in self.allocations}) != len(self.allocations):
            raise ValueError("供货关系不能重复")
        if sum(x.quantity for x in self.allocations) > self.quantity:
            raise ValueError("分配数量不能超过本次验收入库数量")
        if self.allocations and self.quality != "sellable":
            raise ValueError("待检或损坏库存不能预占给销售订单")
        return self


class MaterialCommand(Action):
    material_id: int = Field(gt=0)
    quantity_grams: Decimal = Field(gt=0, max_digits=14, decimal_places=3, allow_inf_nan=False)


class LocalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(gt=0)
    progress_id: int = Field(gt=0)
