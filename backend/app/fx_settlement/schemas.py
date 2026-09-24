"""Input contracts: amounts are principal, rates are CNY per one USD."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import to_beijing_naive

Money = Annotated[Decimal, Field(ge=0, le=1_000_000_000, decimal_places=2)]


class SettlementInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    usd_balance: Annotated[Decimal, Field(gt=0, le=1_000_000_000, decimal_places=2)]
    reserved_usd: Money = Decimal("0")
    immediate_cny_need: Money = Decimal("0")
    settle_by: date
    max_loss_cny: Money
    stress_drop_pct: Annotated[Decimal, Field(ge=0.1, le=30)] = Decimal("2")
    bank_rate: Annotated[Decimal | None, Field(ge=1, le=20)] = None
    bank_quote_at: datetime | None = None
    fee_bps: Annotated[Decimal, Field(ge=0, le=1000)] = Decimal("0")
    usd_interest_pct: Annotated[Decimal, Field(ge=0, le=20)] = Decimal("0")
    cny_interest_pct: Annotated[Decimal, Field(ge=0, le=20)] = Decimal("0")

    @model_validator(mode="after")
    def validate_inputs(self):
        if self.reserved_usd > self.usd_balance:
            raise ValueError("预留美元不能超过已到账美元")
        if (self.bank_rate is None) != (self.bank_quote_at is None):
            raise ValueError("银行报价与报价时间须同时填写")
        if self.bank_quote_at is not None:
            self.bank_quote_at = to_beijing_naive(self.bank_quote_at)
        return self


class AiDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=40)
    reason_ids: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(min_length=1, max_length=5)
    watchpoint_ids: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(min_length=1, max_length=5)
