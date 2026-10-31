"""Strict local money commands; no floating point input arithmetic."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, allow_inf_nan=False)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=64)


class PaymentCreate(Command):
    local_customer_id: int = Field(gt=0)
    bank_account_id: int = Field(gt=0)
    bank_reference: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    gross_amount: PositiveMoney
    actual_bank_fee: Money = Field(default=Decimal("0"), ge=0)
    collection_date: date
    payment_type: Literal["bank_transfer", "cash", "card", "online"] = "bank_transfer"
    remark: str = Field(default="", max_length=500)
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def net_cash(self):
        if self.actual_bank_fee >= self.gross_amount:
            raise ValueError("银行费用必须小于付款总额")
        return self


class FinanceAction(Command):
    expected_version: int = Field(ge=1)
    business_date: date
    reason: str = Field(min_length=1, max_length=500)
    amount: PositiveMoney | None = Field(default=None, description="退款金额；核销冲回时省略表示全部剩余有效金额")
    bank_reference: str | None = Field(default=None, min_length=1, max_length=128)


class AllocationCreate(Command):
    purpose: Literal["ordinary", "presale_deposit"] = "ordinary"
    settlement_id: int | None = Field(default=None, gt=0)
    expected_version: int = Field(ge=1)
    invoice_id: int = Field(gt=0)
    receivable_id: int = Field(gt=0)
    amount: PositiveMoney
    business_date: date


class AdjustmentCreate(Command):
    expected_version: int = Field(ge=1)
    invoice_id: int = Field(gt=0)
    amount: Money
    business_date: date
    reason: str = Field(min_length=1, max_length=500)


class ReceivableTerms(Command):
    expected_version: int = Field(ge=1)
    invoice_id: int = Field(gt=0)
    due_date: date
    business_date: date
    reason: str = Field(min_length=1, max_length=500)


class CurrencyWrite(Command):
    code: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=64)
    rate_to_cny: Decimal = Field(gt=0, max_digits=18, decimal_places=8, allow_inf_nan=False)
    active: bool = True


class BankAccountWrite(Command):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    active: bool = True
