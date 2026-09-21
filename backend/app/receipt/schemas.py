"""Public receipt input contracts; money never passes through binary floats."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReceiptFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    collection_date: date
    payment_type: str = Field(min_length=1, max_length=64)
    bank_charge: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    remark: str = Field(default="", max_length=500)
    attachment_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator("bank_charge", mode="before")
    @classmethod
    def empty_charge_is_zero(cls, value):
        return Decimal("0") if value is None or value == "" else value

    @model_validator(mode="after")
    def check_charge(self):
        if self.bank_charge > self.amount:
            raise ValueError("银行手续费不能超过回款金额")
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("回款凭证不可重复")
        return self


class ReceiptCreate(ReceiptFields):
    invoice_id: int = Field(gt=0)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    balance_version: str = Field(min_length=64, max_length=64)


class ReceiptUpdate(ReceiptFields):
    version: int = Field(gt=0)


class ReceiptDraft(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    collection_date: date | None = None
    payment_type: str | None = Field(default=None, max_length=64)
    remark: str = Field(default="", max_length=500)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)


class Resolution(BaseModel):
    resolution: str = Field(pattern="^(bind_receipt|confirm_not_created)$")
    xiaoman_receipt_id: str | None = Field(default=None, pattern=r"^\d+$", max_length=64)
    reason: str = Field(min_length=2, max_length=500)


class Reason(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class RemoteChange(BaseModel):
    version: int = Field(gt=0)
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=10, max_length=500)
    confirmed: bool
