"""Money inputs are Decimal; the ordinary receipt API remains positive-only."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Decimal


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_key: str = Field(min_length=1, max_length=160)
    quantity: int = Field(gt=0, le=1000000, strict=True)
    reduction_amount: Money = Field(ge=0, max_digits=14, decimal_places=2)


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    order_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    return_type: Literal["return_refund", "refund_only"]
    reason_code: Literal["quality", "specification", "wrong_goods", "negotiated", "other"]
    reason: str = Field(min_length=2, max_length=2000)
    lines: list[Line] = Field(min_length=1, max_length=200)
    refund_amount: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode="after")
    def distinct_lines(self):
        if len({line.source_key for line in self.lines}) != len(self.lines):
            raise ValueError("同一出库明细不可重复选择")
        return self


class Create(Draft):
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class Update(Draft):
    version: int = Field(gt=0)


class Activate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(gt=0)
    quote_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class Reverse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(gt=0)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    reason: str = Field(min_length=2, max_length=2000)


class Cash(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(gt=0)
    status: Literal["paid", "recovered"]
    evidence: str = Field(min_length=10, max_length=2000)


class Receiving(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, strict=True)
    accepted_quantity: int = Field(ge=0, strict=True)
    rejected_quantity: int = Field(ge=0, strict=True)
    pending_quantity: int = Field(ge=0, strict=True)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def reconcile_quantities(self):
        if self.accepted_quantity + self.rejected_quantity + self.pending_quantity != self.quantity:
            raise ValueError("合格、不合格和待检数量之和必须等于实收数量")
        return self


class Stock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    reference: str = Field(min_length=1, max_length=128)


class Inspection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: int = Field(gt=0)
    accepted_quantity: int = Field(ge=0, strict=True)
    rejected_quantity: int = Field(ge=0, strict=True)
    pending_quantity: int = Field(ge=0, strict=True)
    note: str = Field(min_length=2, max_length=1000)
