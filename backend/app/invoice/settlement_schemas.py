"""Strict wire contracts: decimal strings, bounded batches and idempotency keys."""
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.receipt.schemas import ReceiptFields


class ShipmentLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_item_id: int = Field(gt=0, strict=True)
    quantity: int = Field(gt=0, strict=True)


class ShipmentQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ShipmentLine] = Field(min_length=1, max_length=200)
    freight_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({x.invoice_item_id for x in self.items}) != len(self.items):
            raise ValueError("产品明细不可重复")
        return self


class ShipmentCreate(ShipmentQuote):
    quote_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    payment: ReceiptFields | None = None


class SettlementAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)
    reason: str = Field(min_length=2, max_length=500)


class BatchAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: int = Field(gt=0)
    settlement_id: int | None = Field(default=None, gt=0)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    balance_version: str = Field(pattern=r"^[a-f0-9]{64}$")


class BatchCreate(ReceiptFields):
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    allocations: list[BatchAllocation] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def allocation_total(self):
        if len({x.invoice_id for x in self.allocations}) != len(self.allocations):
            raise ValueError("订单不可重复")
        if sum((x.amount for x in self.allocations), Decimal("0")) != self.amount:
            raise ValueError("订单分配合计必须等于本次回款总额")
        if self.bank_charge:
            raise ValueError("批次手续费由订单费用分摊，请勿重复填写")
        return self
