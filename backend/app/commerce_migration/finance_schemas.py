"""Reviewed original faces and prior reversals, never guessed net receipts."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HistoricalRefund(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bank_reference: str = Field(min_length=1, max_length=128)
    business_date: date


class HistoricalReversal(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    payment_id: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bank_charge: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    rate_to_usd: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    rate_to_cny: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    business_date: date

    @model_validator(mode='after')
    def components(self):
        if self.bank_charge > self.amount:
            raise ValueError('历史逐笔冲回费用不能超过金额')
        return self


class HistoricalAllocation(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=128)
    existing_receipt_id: int | None = Field(default=None, gt=0)
    invoice_id: int = Field(gt=0)
    order_binding_record_id: int = Field(gt=0)
    receivable_id: int = Field(gt=0)
    original_receipt_id: str = Field(min_length=1, max_length=64)
    source_customer_id: str = Field(min_length=1, max_length=64)
    purpose: Literal['ordinary', 'presale_deposit', 'presale_balance', 'freight']
    collection_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bank_charge: Decimal = Field(default=Decimal('0'), ge=0, max_digits=14, decimal_places=2)
    reversed_amount: Decimal = Field(default=Decimal('0'), ge=0, max_digits=14, decimal_places=2)
    reversed_bank_charge: Decimal = Field(default=Decimal('0'), ge=0, max_digits=14, decimal_places=2)
    remaining_commission_usd: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    prior_reversals: list[HistoricalReversal] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def amounts(self):
        if (self.bank_charge > self.amount or self.reversed_amount > self.amount
                or self.reversed_bank_charge > min(self.bank_charge, self.reversed_amount)
                or self.reversed_amount - self.reversed_bank_charge > self.amount - self.bank_charge):
            raise ValueError('历史核销与冲回本金、费用组成不守恒')
        if len({r.payment_id for r in self.prior_reversals}) != len(self.prior_reversals):
            raise ValueError('历史提成调整身份重复')
        if (sum((r.amount for r in self.prior_reversals), Decimal(0)) != self.reversed_amount
                or sum((r.bank_charge for r in self.prior_reversals), Decimal(0)) != self.reversed_bank_charge):
            raise ValueError('历史冲回累计须等于逐笔原币凭证')
        if self.purpose == 'freight' and self.remaining_commission_usd:
            raise ValueError('独立运费不得计入商品提成')
        return self


class HistoricalPayment(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    external_id: str = Field(min_length=1, max_length=128)
    existing_batch_id: int | None = Field(default=None, gt=0)
    batch_no: str = Field(min_length=1, max_length=64)
    local_customer_id: int = Field(gt=0)
    source_customer_id: str = Field(min_length=1, max_length=64)
    customer_external_identity_id: int = Field(gt=0)
    bank_account_id: int = Field(gt=0)
    bank_reference: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=1, max_length=16, pattern=r'^[A-Z][A-Z0-9]{0,15}$')
    gross_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    actual_bank_fee: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    allocated_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    refunded_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    bank_charge_total: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    available_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    rate_to_cny: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    rate_to_usd: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    collection_date: date
    confirmed_date: date
    confirmed_by: int = Field(gt=0)
    confirmed_at: datetime
    payment_type: str = Field(min_length=1, max_length=64)
    remark: str = Field(default='', max_length=500)
    refunds: list[HistoricalRefund] = Field(default_factory=list, max_length=500)
    allocations: list[HistoricalAllocation] = Field(default_factory=list, max_length=500)

    @model_validator(mode='after')
    def conservation(self):
        if self.actual_bank_fee > self.gross_amount or self.confirmed_date < self.collection_date:
            raise ValueError('历史实际银行费或确认日期不正确')
        if self.confirmed_at.tzinfo is not None or self.confirmed_at.date() != self.confirmed_date:
            raise ValueError('确认时间须是明确的北京时间并对应确认业务日')
        allocated = sum((r.amount - r.reversed_amount for r in self.allocations), Decimal(0))
        if any(a.source_customer_id != self.source_customer_id for a in self.allocations):
            raise ValueError('付款与全部核销须属于同一已核验原客户')
        refunded = sum((r.amount for r in self.refunds), Decimal(0))
        fee = sum((r.bank_charge - r.reversed_bank_charge for r in self.allocations), Decimal(0))
        if (allocated != self.allocated_amount or refunded != self.refunded_amount or fee != self.bank_charge_total
                or self.available_amount != self.gross_amount - allocated - refunded):
            raise ValueError('清单核销、费用、退款与未分配金额须等于源付款完整期末责任')
        if allocated + refunded > self.gross_amount:
            raise ValueError('历史有效核销与退款超过原付款')
        keys = [self.bank_reference, *(r.bank_reference for r in self.refunds)]
        if len(set(keys)) != len(keys):
            raise ValueError('同账户收款、退款银行流水不得重复')
        for rows in (self.allocations, self.refunds):
            if len({r.external_id for r in rows}) != len(rows):
                raise ValueError('历史来源身份重复')
        return self


class FinanceOpeningManifest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    payments: list[HistoricalPayment] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def identities(self):
        bank_keys = [(p.bank_account_id, ref) for p in self.payments
            for ref in [p.bank_reference, *(r.bank_reference for r in p.refunds)]]
        allocation_ids = [identity for p in self.payments for a in p.allocations
            for identity in [a.original_receipt_id, *(r.payment_id for r in a.prior_reversals)]]
        existing_batches = [p.existing_batch_id for p in self.payments if p.existing_batch_id is not None]
        existing_receipts = [a.existing_receipt_id for p in self.payments for a in p.allocations if a.existing_receipt_id is not None]
        if (len(set(bank_keys)) != len(bank_keys) or len(set(allocation_ids)) != len(allocation_ids)
                or len({p.external_id for p in self.payments}) != len(self.payments)
                or len({p.batch_no.lower() for p in self.payments}) != len(self.payments)
                or len(set(existing_batches)) != len(existing_batches) or len(set(existing_receipts)) != len(existing_receipts)):
            raise ValueError('同一来源、银行流水或原核销只能承接一次')
        for payment in self.payments:
            if (payment.confirmed_date > self.cutover_date
                    or any(not payment.confirmed_date <= r.business_date <= self.cutover_date for r in payment.refunds)
                    or any(not payment.confirmed_date <= r.collection_date <= self.cutover_date for r in payment.allocations)):
                raise ValueError('历史核销、退款日期须在确认日与切换日之间')
            if any(not allocation.collection_date <= r.business_date <= self.cutover_date for allocation in payment.allocations for r in allocation.prior_reversals):
                raise ValueError('历史逐笔冲回日期须在原核销与切换日之间')
        if len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode('utf-8')) > 4194304:
            raise ValueError('整份清单不得超过4MiB')
        return self
