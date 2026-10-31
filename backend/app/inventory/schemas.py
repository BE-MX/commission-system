"""Strict commands: quantities are pieces; counts carry an observed version."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MovementLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: int = Field(gt=0)
    sku_id: int = Field(gt=0)
    quality: Literal["sellable", "quarantine", "damaged"] = "sellable"
    quantity: int = Field(strict=True, ge=-2147483647, le=2147483647)
    destination_warehouse_id: int | None = Field(None, gt=0)
    expected_version: int | None = Field(None, ge=0)


class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_./-]+$")
    kind: Literal["opening", "receipt", "adjustment", "count", "transfer"]
    reason: str = Field(min_length=1, max_length=500)
    source_type: str | None = Field(None, max_length=32)
    source_id: str | None = Field(None, max_length=64)
    lines: list[MovementLine] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_lines(self):
        if not self.reason.strip():
            raise ValueError("必须填写业务原因")
        seen = set()
        for line in self.lines:
            key = (line.warehouse_id, line.sku_id, line.quality)
            if key in seen:
                raise ValueError("同一库存维度不能重复填写")
            seen.add(key)
            if self.kind == "count":
                if line.quantity < 0 or line.expected_version is None:
                    raise ValueError("盘点需非负实盘数与库存版本")
            elif self.kind == "adjustment":
                if not line.quantity:
                    raise ValueError("调整数量不能为零")
            elif line.quantity <= 0:
                raise ValueError("数量必须为正整数")
            if self.kind == "transfer":
                if not line.destination_warehouse_id or line.destination_warehouse_id == line.warehouse_id:
                    raise ValueError("调拨必须选择不同的目标仓库")
            elif line.destination_warehouse_id is not None:
                raise ValueError("仅调拨允许目标仓库")
        return self


class ReversalCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_./-]+$")
    reason: str = Field(min_length=1, max_length=500)


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
