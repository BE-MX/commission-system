"""Execute approved original-currency compensation against a shipped source."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.finance.schemas import PositiveMoney


class MoneyExecute(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    settlement_item_id: int = Field(gt=0)
    application_id: int = Field(gt=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    action: Literal["cash_refund", "discount", "order_credit", "freight_subsidy"]
    amount: PositiveMoney
    currency: str = Field(min_length=3, max_length=16)
    disbursement: Literal["bank_refund", "customer_credit"]
    bank_reference: str | None = Field(default=None, min_length=1, max_length=128)
    business_date: date
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def route(self):
        if self.action == "cash_refund" and self.disbursement != "bank_refund":
            raise ValueError("现金退款必须记录实际银行退款")
        if self.action in {"discount", "order_credit"} and self.disbursement != "customer_credit":
            raise ValueError("折扣和订单抵扣应保留为客户预收")
        if (self.disbursement == "bank_refund") != bool(self.bank_reference):
            raise ValueError("实际退款必须填写银行流水；预收抵扣不能填写退款流水")
        return self
