"""Whole contract and closing responsibilities; no remaining-quantity pseudo-order."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
import json
from pydantic import BaseModel, ConfigDict, Field, model_validator

ZERO = Decimal('0')


class HistoricalReservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    warehouse_id: int = Field(gt=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)


class HistoricalOrderItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_item_id: str = Field(min_length=1, max_length=64)
    legacy_unique_id: str | None = Field(max_length=64)
    existing_invoice_item_id: int | None = Field(default=None, gt=0)
    existing_customer_order_item_id: int | None = Field(default=None, gt=0)
    catalog_record_id: int = Field(gt=0)
    local_sku_id: int = Field(gt=0)
    product_kind: Literal['hair', 'accessory']
    item_type: Literal['stock', 'custom']
    custom_product_id: int | None = Field(default=None, gt=0)
    legacy_product_id: int | None = Field(default=None, gt=0)
    legacy_sku_id: int | None = Field(default=None, gt=0)
    product_name: str = Field(min_length=1, max_length=512)
    product_display: str = Field(min_length=1, max_length=256)
    product_family: str = Field(min_length=1, max_length=256)
    net_weight_grams: str | None = Field(max_length=64)
    model: str | None = Field(max_length=200)
    color: str = Field(min_length=1, max_length=128)
    length: str | None = Field(max_length=128)
    curl: str | None = Field(max_length=64)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    price_per_piece: Decimal | None = Field(ge=0, max_digits=12, decimal_places=4)
    standard_price: Decimal | None = Field(ge=0, max_digits=12, decimal_places=4)
    customer_price: Decimal | None = Field(ge=0, max_digits=12, decimal_places=4)
    discount_amount: Decimal = Field(le=0, max_digits=14, decimal_places=2)
    total_price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    price_source: str = Field(min_length=1, max_length=32)
    commercial_kind: Literal['sample', 'bulk', 'unknown']
    shipped_quantity: int = Field(strict=True, ge=0, le=2147483647)
    production_pending_quantity: int = Field(strict=True, ge=0, le=2147483647)
    reservations: list[HistoricalReservation] = Field(max_length=50)

    @model_validator(mode='after')
    def quantities_and_faces(self):
        reserved = sum(row.quantity for row in self.reservations)
        if self.shipped_quantity + self.production_pending_quantity + reserved > self.quantity:
            raise ValueError('完整订单行的已发、在产与预占不能超过原合同件数')
        if len({row.warehouse_id for row in self.reservations}) != len(self.reservations):
            raise ValueError('同一销售行仓库责任不能重复')
        if self.price_per_piece is not None and (self.price_per_piece * self.quantity + self.discount_amount).quantize(
                Decimal('.01'), rounding=ROUND_HALF_UP) != self.total_price:
            raise ValueError('原成交单价、数量、折扣与原行金额不一致')
        if self.item_type == 'stock' and self.custom_product_id is not None:
            raise ValueError('标准行不能带非标主数据身份')
        return self


class HistoricalCustomerItemAlias(BaseModel):
    model_config = ConfigDict(extra='forbid')
    existing_customer_order_item_id: int = Field(gt=0)
    source_record_id: int = Field(gt=0)
    item_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    external_item_id: str = Field(min_length=1, max_length=128)
    original_snapshot_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_item_ids: list[str] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def members(self):
        if len(set(self.source_item_ids)) != len(self.source_item_ids):
            raise ValueError('原聚合别名成员不能重复')
        return self


class HistoricalOrderAdjustment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    external_id: str = Field(min_length=1, max_length=128)
    kind: Literal['contract_change', 'credit']
    amount: Decimal = Field(max_digits=14, decimal_places=2)
    released_bank_charge: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    business_date: date
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def components(self):
        if not self.amount or not self.reason.strip():
            raise ValueError('原应收调整必须非零并有原始依据')
        if self.kind == 'credit' and self.amount >= 0:
            raise ValueError('原贷项只能减少应收；正合同变更须明确为合同变更')
        if (self.kind == 'contract_change' and self.released_bank_charge
                or self.released_bank_charge and (self.amount >= 0 or self.released_bank_charge > -self.amount)):
            raise ValueError('合同变更不能重复释放费用；贷项费用须由原负金额覆盖')
        return self


class HistoricalOrderReceivable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    external_id: str = Field(min_length=1, max_length=128)
    existing_receivable_id: int | None = Field(default=None, gt=0)
    kind: Literal['goods', 'freight']
    source_settlement_id: str | None = Field(max_length=64)
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    handling_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    due_date: date | None
    paid_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    adjustments: list[HistoricalOrderAdjustment] = Field(max_length=500)

    @model_validator(mode='after')
    def components(self):
        face = self.amount + sum((row.amount for row in self.adjustments), ZERO)
        fee = self.handling_amount - sum((row.released_bank_charge for row in self.adjustments), ZERO)
        if face < self.paid_amount or not ZERO <= fee <= face:
            raise ValueError('原应收本金、费用、贷项和已收余额不守恒')
        if self.kind == 'freight' and self.handling_amount:
            raise ValueError('独立运费不能重复计客户商品附加费')
        if len({row.external_id for row in self.adjustments}) != len(self.adjustments):
            raise ValueError('原应收调整身份重复')
        return self


class HistoricalDepartment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    department_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=128)
    rate: Decimal = Field(gt=0, le=100, max_digits=7, decimal_places=4)


class HistoricalOrder(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_order_id: str = Field(min_length=1, max_length=64)
    source_customer_id: str = Field(min_length=1, max_length=64)
    source_order_no: str | None = Field(max_length=128)
    legacy_invoice_order_no: str | None = Field(max_length=64)
    source_order_name: str | None = Field(max_length=255)
    source_order_status: str = Field(min_length=1, max_length=64)
    existing_invoice_id: int | None = Field(default=None, gt=0)
    existing_customer_order_id: int | None = Field(default=None, gt=0)
    local_customer_id: int = Field(gt=0)
    customer_external_identity_id: int = Field(gt=0)
    invoice_no: str = Field(min_length=1, max_length=64)
    order_type: Literal['stock', 'production', 'presale']
    commerce_status: Literal['confirmed', 'partially_shipped', 'shipped', 'closed', 'cancelled']
    invoice_date: date
    account_date: date
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    rate_to_usd: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    customer_name: str = Field(min_length=1, max_length=256)
    customer_grade: str | None = Field(max_length=1)
    contact_name: str | None = Field(max_length=256)
    contact_phone: str | None = Field(max_length=100)
    contact_email: str | None = Field(max_length=256)
    delivery_address: str | None = Field(max_length=4000)
    sales_user_id: int | None = Field(gt=0)
    sales_user_name: str | None = Field(max_length=100)
    owner_external_user_id: str | None = Field(max_length=64)
    merchandiser_id: int | None = Field(gt=0)
    merchandiser_name: str | None = Field(max_length=100)
    express_channel: str | None = Field(max_length=64)
    shipping_fee: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    surcharge_name: str | None = Field(max_length=128)
    surcharge_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    packaging_quantity: int = Field(strict=True, ge=0, le=2147483647)
    internal_accessory: Decimal | None = Field(ge=0, max_digits=14, decimal_places=2)
    internal_discount: Decimal | None = Field(le=0, max_digits=14, decimal_places=2)
    internal_payment_method: str | None = Field(max_length=64)
    internal_shipping_type: str | None = Field(max_length=64)
    product_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    total_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    source_received_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    source_balance_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    local_deposit_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    local_deposit_charge: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    commercial_source: str | None = Field(max_length=32)
    is_new_deal: bool | None
    is_first_return: bool | None
    is_private_order: bool
    is_valid_business_order: bool
    business_amount_original: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    business_amount_usd: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    country: str | None = Field(max_length=8)
    departments: list[HistoricalDepartment] = Field(max_length=20)
    payment_term: str | None = Field(max_length=256)
    remark: str | None = Field(max_length=4000)
    items: list[HistoricalOrderItem] = Field(min_length=1, max_length=200)
    customer_item_aliases: list[HistoricalCustomerItemAlias] = Field(default_factory=list, max_length=200)
    receivables: list[HistoricalOrderReceivable] = Field(min_length=1, max_length=500)
    historical_shipment_ids: list[str] = Field(max_length=500)
    production_ids: list[str] = Field(max_length=500)
    material_allocation_ids: list[int] = Field(max_length=500)

    @model_validator(mode='after')
    def complete_contract(self):
        if sum((row.total_price for row in self.items), ZERO) != self.product_amount:
            raise ValueError('原产品总额须等于全部原合同明细，不得仅导入未发部分')
        if self.total_amount != self.product_amount + (self.internal_accessory or ZERO) + self.shipping_fee + self.surcharge_amount:
            raise ValueError('完整合同产品、包装、运费及附加费总额不守恒')
        if self.order_type != 'presale' and (self.local_deposit_amount or self.local_deposit_charge):
            raise ValueError('非预售订单不能制造首款责任')
        if self.order_type == 'presale' and (self.shipping_fee or not ZERO < self.local_deposit_amount - self.local_deposit_charge <= self.product_amount):
            raise ValueError('预售完整主合同须独立运费，原首款本金由商品金额覆盖')
        if self.local_deposit_charge > min(self.local_deposit_amount, self.surcharge_amount):
            raise ValueError('原首款费用不能超过首款或合同附加费')
        if len({row.source_item_id for row in self.items}) != len(self.items):
            raise ValueError('原订单明细身份重复')
        if self.customer_item_aliases:
            if not self.existing_invoice_id or not self.existing_customer_order_id:
                raise ValueError('聚合别名只能修复明确复用的原发票及经营订单')
            members = {item.source_item_id: item for item in self.items}
            assigned = set()
            aliases = set()
            for alias in self.customer_item_aliases:
                if alias.existing_customer_order_item_id in aliases:
                    raise ValueError('原聚合经营行只能关联一次')
                aliases.add(alias.existing_customer_order_item_id)
                for identity in alias.source_item_ids:
                    item = members.get(identity)
                    if (identity in assigned or item is None or item.item_type != 'custom'
                            or item.legacy_unique_id != alias.external_item_id
                            or item.existing_customer_order_item_id or not item.existing_invoice_item_id):
                        raise ValueError('聚合成员须为完整原非标发票行，明确共享原别名且不能重复归组')
                    assigned.add(identity)
            if aliases.intersection(item.existing_customer_order_item_id for item in self.items):
                raise ValueError('聚合经营行不能同时绑定真实明细')
        for rows, key in ((self.items, 'existing_invoice_item_id'), (self.items, 'existing_customer_order_item_id'),
                          (self.receivables, 'existing_receivable_id')):
            values = [getattr(row, key) for row in rows if getattr(row, key) is not None]
            if len(set(values)) != len(values):
                raise ValueError('既有主账明细或应收只能绑定一次')
        if len({row.external_id for row in self.receivables}) != len(self.receivables):
            raise ValueError('原应收身份重复')
        goods = [row for row in self.receivables if row.kind == 'goods']
        contract = [row for row in self.receivables if row.source_settlement_id is None]
        if len(goods) != 1 or goods[0].source_settlement_id is not None:
            raise ValueError('完整主合同必须且仅有一条商品应收')
        if (sum((row.amount + sum((a.amount for a in row.adjustments if a.kind == 'contract_change'), ZERO)
                 for row in contract), ZERO) != self.total_amount):
            raise ValueError('原应收面额与已计入合同的变更须等于完整合同')
        goods_contract = goods[0].amount + sum((a.amount for a in goods[0].adjustments if a.kind == 'contract_change'), ZERO)
        freight_contract = sum((row.amount + sum((a.amount for a in row.adjustments if a.kind == 'contract_change'), ZERO)
            for row in contract if row.kind == 'freight'), ZERO)
        if (goods_contract != self.total_amount - self.shipping_fee or freight_contract != self.shipping_fee
                or goods[0].handling_amount != self.surcharge_amount):
            raise ValueError('主合同商品、独立运费和原客户费用须分别对应完整合同')
        face = sum((row.amount + sum((a.amount for a in row.adjustments), ZERO) for row in self.receivables), ZERO)
        if (sum((row.paid_amount for row in self.receivables), ZERO) != self.source_received_amount
                or self.source_received_amount + self.source_balance_amount != face):
            raise ValueError('整单期末已收、剩余与全部原应收/贷项责任不一致')
        expected_business = max(ZERO, self.total_amount - self.surcharge_amount
            + sum((a.amount + a.released_bank_charge for row in contract for a in row.adjustments if a.kind == 'credit'), ZERO))
        if (expected_business != self.business_amount_original
                or (self.business_amount_original * self.rate_to_usd).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) != self.business_amount_usd):
            raise ValueError('原经营金额与完整合同、非重复贷项及冻结汇率不一致')
        if self.departments and (len({row.department_id for row in self.departments}) != len(self.departments)
                or sum((row.rate for row in self.departments), ZERO) != 100):
            raise ValueError('原部门分摊必须唯一并合计100%')
        for values in (self.historical_shipment_ids, self.production_ids, self.material_allocation_ids):
            if len(set(values)) != len(values):
                raise ValueError('原履约、生产或物料责任身份重复')
        if any(row.source_settlement_id not in self.historical_shipment_ids for row in self.receivables if row.source_settlement_id is not None):
            raise ValueError('批次运费必须关联完整原发货批次清单')
        if any(row.shipped_quantity for row in self.items) and not self.historical_shipment_ids:
            raise ValueError('原已发件数必须有完整历史发货批次')
        if any(row.production_pending_quantity for row in self.items) and not self.production_ids:
            raise ValueError('原在产供货必须有完整生产责任')
        shipped = sum(row.shipped_quantity for row in self.items)
        quantity = sum(row.quantity for row in self.items)
        if (self.commerce_status == 'confirmed' and shipped
                or self.commerce_status == 'partially_shipped' and not 0 < shipped < quantity
                or self.commerce_status in {'shipped', 'closed'} and shipped != quantity):
            raise ValueError('原订单状态与全部已发数量不一致')
        if self.commerce_status in {'shipped', 'closed', 'cancelled'} and any(
                row.reservations or row.production_pending_quantity for row in self.items):
            raise ValueError('已结束订单不能保留待供货或预占责任')
        return self


class OrderOpeningManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_key: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9._:-]+$')
    source: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9._-]+$')
    tenant: str = Field(min_length=1, max_length=64)
    cutover_date: date
    evidence_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    review_reference: str = Field(min_length=1, max_length=500)
    orders: list[HistoricalOrder] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def identities_and_dates(self):
        if not self.review_reference.strip() or len({row.source_order_id for row in self.orders}) != len(self.orders):
            raise ValueError('整单清单须有核验依据，来源订单身份不能重复')
        for key in ('existing_invoice_id', 'existing_customer_order_id'):
            values = [getattr(row, key) for row in self.orders if getattr(row, key) is not None]
            if len(set(values)) != len(values):
                raise ValueError('既有整单或经营投影只能绑定一次')
        for order in self.orders:
            if order.invoice_date > self.cutover_date or order.account_date > self.cutover_date:
                raise ValueError('原订单及经营业务日不能晚于切换日')
            if any(not order.invoice_date <= a.business_date <= self.cutover_date for row in order.receivables for a in row.adjustments):
                raise ValueError('原应收调整日须在原订单与切换日之间')
        if len(json.dumps(self.model_dump(mode='json'), ensure_ascii=False).encode('utf-8')) > 4194304:
            raise ValueError('整份清单不得超过4MiB')
        return self
