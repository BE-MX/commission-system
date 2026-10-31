"""Historical shipped batches and consumed funds, including original cents."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator

ZERO = Decimal('0')


class HistoricalShipmentItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_item_id: str = Field(min_length=1, max_length=64)
    outbound_item_id: str = Field(min_length=1, max_length=64)
    existing_settlement_item_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    line_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class HistoricalApplication(BaseModel):
    model_config = ConfigDict(extra='forbid')
    existing_application_id: int | None = Field(default=None, gt=0)
    original_receipt_id: str = Field(min_length=1, max_length=64)
    component: Literal['goods', 'freight', 'deposit']
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bank_charge: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    released_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    released_bank_charge: Decimal = Field(ge=0, max_digits=14, decimal_places=2)

    @model_validator(mode='after')
    def amounts(self):
        if (self.bank_charge > self.amount or self.released_amount > self.amount
                or self.released_bank_charge > min(self.bank_charge, self.released_amount)
                or self.released_amount - self.released_bank_charge > self.amount - self.bank_charge):
            raise ValueError('原发货资金占用及已释放本金、费用不守恒')
        return self


class HistoricalShipment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_settlement_id: str = Field(min_length=1, max_length=64)
    existing_settlement_id: int | None = Field(default=None, gt=0)
    existing_outbound_id: int | None = Field(default=None, gt=0)
    sequence: int = Field(strict=True, gt=0, le=2147483647)
    settlement_no: str = Field(min_length=1, max_length=96)
    outbound_no: str = Field(min_length=1, max_length=64)
    outbound_record_id: str = Field(min_length=1, max_length=64)
    outbound_invoice_id: str | None = Field(max_length=64)
    shipped_at: datetime
    business_date: date
    warehouse_id: int = Field(gt=0)
    is_final: bool
    goods_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    packaging_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    handling_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    freight_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    deposit_applied: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    deposit_charge_applied: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    goods_payment_due: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    goods_payment_charge: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    new_payment_due: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    inspection_id: int | None = Field(gt=0)
    items: list[HistoricalShipmentItem] = Field(min_length=1, max_length=200)
    applications: list[HistoricalApplication] = Field(max_length=500)

    @model_validator(mode='after')
    def frozen_quote(self):
        if self.shipped_at.tzinfo is not None or self.shipped_at.date() != self.business_date:
            raise ValueError('原发货时间须明确为北京时间且与原业务日一致')
        if any(identity.startswith(('local-', 'task:')) for identity in (self.outbound_record_id, self.outbound_invoice_id) if identity):
            raise ValueError('原出库身份与本地命名空间冲突，须核验原始身份')
        if sum((item.line_amount for item in self.items), ZERO) != self.goods_amount:
            raise ValueError('原批次商品金额须等于全部原发货明细金额')
        if (self.deposit_charge_applied > self.deposit_applied
                or self.goods_payment_due + self.deposit_applied != self.goods_amount + self.packaging_amount + self.handling_amount
                or self.goods_payment_charge + self.deposit_charge_applied != self.handling_amount
                or self.goods_payment_charge > self.goods_payment_due
                or self.goods_payment_due + self.freight_amount != self.new_payment_due):
            raise ValueError('原批次商品、首款、费用与运费组成不守恒')
        required = {'goods': (self.goods_payment_due, self.goods_payment_charge),
            'freight': (self.freight_amount, ZERO), 'deposit': (self.deposit_applied, self.deposit_charge_applied)}
        for component, (amount, fee) in required.items():
            apps = [app for app in self.applications if app.component == component]
            if (sum((app.amount for app in apps), ZERO), sum((app.bank_charge for app in apps), ZERO)) != (amount, fee):
                raise ValueError('原发货须完整记录已消费核销本金及费用，不能重用已发货资金')
        if (len({item.source_item_id for item in self.items}) != len(self.items)
                or len({item.outbound_item_id for item in self.items}) != len(self.items)
                or len({(app.original_receipt_id, app.component) for app in self.applications}) != len(self.applications)):
            raise ValueError('原发货明细或资金应用身份重复')
        return self


class FulfillmentOpening(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_binding_record_id: int = Field(gt=0)
    shipments: list[HistoricalShipment] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def identities(self):
        for key in ('source_settlement_id', 'sequence', 'settlement_no', 'outbound_record_id', 'outbound_no'):
            values = [getattr(row, key) for row in self.shipments]
            if len(set(values)) != len(values):
                raise ValueError('原发货批次、序号及出库身份须唯一')
        for key in ('existing_settlement_id', 'existing_outbound_id', 'inspection_id'):
            values = [getattr(row, key) for row in self.shipments if getattr(row, key) is not None]
            if len(set(values)) != len(values):
                raise ValueError('既有发货、出库或检验身份只能复用一次')
        return self


class FulfillmentOpeningManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    orders: list[FulfillmentOpening] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def identities_and_dates(self):
        if not self.review_reference.strip() or len({row.order_binding_record_id for row in self.orders}) != len(self.orders):
            raise ValueError('须有核验依据，同一整单不能重复出现')
        for key in ('outbound_record_id', 'outbound_no', 'settlement_no'):
            values = [getattr(ship, key) for row in self.orders for ship in row.shipments]
            if len(set(values)) != len(values):
                raise ValueError('跨订单出库及批次身份重复')
        aliases = set()
        for row in self.orders:
            for ship in row.shipments:
                current = {identity for identity in (ship.outbound_record_id, ship.outbound_invoice_id) if identity}
                if current & aliases:
                    raise ValueError('跨批次原出库镜像与API身份交叉重复')
                aliases.update(current)
        if any(ship.business_date > self.cutover_date for row in self.orders for ship in row.shipments):
            raise ValueError('历史发货不能晚于切换日')
        if len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode('utf-8')) > 4194304:
            raise ValueError('整份历史履约清单不得超过4MiB')
        return self
