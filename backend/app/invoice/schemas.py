"""Pydantic schemas for order invoice management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CustomerSearchItem(BaseModel):
    company_id: str
    company_name: str
    country_name: Optional[str] = None


class ProductFilterQuery(BaseModel):
    model: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    unit: Optional[str] = None


class ProductFilterOptions(BaseModel):
    models: list[str] = []
    colors: list[str] = []
    sizes: list[str] = []
    units: list[str] = []


class ProductMatchItem(BaseModel):
    product_id: int
    sku_id: Optional[int] = None
    sku_count: int = 0
    product_name: str
    product_display: str
    model: str
    color: str
    size: str
    unit: str
    price_per_piece: Optional[Decimal] = None
    price_source: str = "missing"


class ProductMatchResponse(BaseModel):
    is_unique: bool
    item: Optional[ProductMatchItem] = None
    matches: list[ProductMatchItem] = []


class InvoiceImportRow(BaseModel):
    source_row: int = Field(..., ge=1)
    product: str = Field(..., max_length=256)
    length: str = Field(..., max_length=128)
    color: str = Field(..., max_length=128)
    weight: str = Field(..., max_length=64)
    quantity: int | str
    unit_price: Decimal | str


class InvoiceImportPreviewRequest(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=64)
    order_type: str = Field(..., pattern="^(stock|production)$")
    currency: str = Field(..., pattern="^[A-Z]{3}$")
    rows: list[InvoiceImportRow] = Field(..., min_length=1, max_length=200)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value):
        return str(value or "").strip().upper()


class InvoiceItemPayload(BaseModel):
    # 编辑时回传既有行 id，用于跨保存传承 xiaoman_unique_id（OKKI 编辑推单按行更新）
    id: Optional[int] = None
    product_kind: str = Field(default="hair", pattern="^(hair|accessory)$")
    item_type: str = Field(default="stock", pattern="^(stock|custom)$")
    product_id: Optional[int] = None
    sku_id: Optional[int] = None
    product_name: str = Field(default="", max_length=512)
    product_display: str = Field(..., max_length=256)
    net_weight_grams: Optional[str] = Field(None, max_length=64)
    curl: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=128)
    color: str = Field(..., max_length=128)
    length: Optional[str] = Field(None, max_length=128)
    quantity: int = Field(..., gt=0)
    price_per_piece: Optional[Decimal] = Field(
        None, gt=0, max_digits=12, decimal_places=4,
    )
    discount_amount: Decimal = Field(default=Decimal("0"), le=0)
    price_source: str = Field(default="manual", max_length=32)

    @field_validator("discount_amount", mode="before")
    @classmethod
    def _normalize_line_discount(cls, value):
        if value is None or value == "":
            return Decimal("0")
        return -abs(Decimal(str(value)))


class AccessoryPricePayload(BaseModel):
    id: Optional[int] = None
    product_id: int
    sku_id: int
    accessory_name: str = Field(..., min_length=1, max_length=256)
    accessory_model: str = Field(..., min_length=1, max_length=128)
    accessory_color: str = Field(..., min_length=1, max_length=128)
    price: Decimal = Field(..., ge=0, max_digits=12, decimal_places=4)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")


class _InvoiceHeaderPayload(BaseModel):
    # 发票号开放编辑：None/空串 = 新建时按规则生成、编辑时保持原号
    invoice_no: Optional[str] = Field(None, max_length=64)
    customer_id: str = Field(..., max_length=64)
    customer_name: str = Field(..., max_length=256)
    order_type: str = Field(default="stock", pattern="^(stock|production)$")
    contact_name: Optional[str] = Field(None, max_length=256)
    contact_phone: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[str] = Field(None, max_length=256)
    delivery_address: Optional[str] = None
    sales_user_name: Optional[str] = Field(None, max_length=100)
    sales_phone: Optional[str] = Field(None, max_length=100)
    sales_email: Optional[str] = Field(None, max_length=256)
    invoice_date: date
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    express_channel: Optional[str] = Field(None, max_length=64)
    shipping_fee: Decimal = Field(default=Decimal("0"), ge=0)
    surcharge_name: Optional[str] = Field(None, max_length=128)
    surcharge_amount: Decimal = Field(default=Decimal("0"), ge=0)
    payment_term: Optional[str] = Field(None, max_length=256)
    internal_payment_method: Optional[str] = Field(None, max_length=64)
    internal_discount: Optional[Decimal] = Field(None, le=0)
    packaging_quantity: int = Field(default=0, ge=0)
    internal_accessory: Optional[Decimal] = Field(None, ge=0)
    internal_received: Optional[Decimal] = Field(None, ge=0)
    internal_balance: Optional[Decimal] = Field(None, ge=0)
    internal_shipping_type: Optional[str] = Field(None, max_length=64)
    # OKKI 必填业务标记（1是/0否；None=服务端按兜底规则自动判定）
    okki_new_deal: Optional[int] = Field(None, ge=0, le=1)
    okki_free_shipping: Optional[int] = Field(None, ge=0, le=1)
    okki_first_return: Optional[int] = Field(None, ge=0, le=1)
    remark: Optional[str] = None
    items: list[InvoiceItemPayload] = Field(default_factory=list)

    @field_validator("customer_id", mode="before")
    @classmethod
    def _coerce_customer_id(cls, value):
        return "" if value is None else str(value)

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value):
        return str(value or "").strip().upper()

    @field_validator("internal_discount", mode="before")
    @classmethod
    def _normalize_order_discount(cls, value):
        if value is None or value == "":
            return None
        return -abs(Decimal(str(value)))


class InvoiceCreate(_InvoiceHeaderPayload):
    pass


class InvoiceUpdate(_InvoiceHeaderPayload):
    pass


class InvoiceItemResponse(InvoiceItemPayload):
    id: int
    total_price: Decimal
    sort_order: int
    standard_price: Optional[Decimal] = None
    customer_price: Optional[Decimal] = None
    custom_product_id: Optional[int] = None

    model_config = {"from_attributes": True}


class InvoiceListItem(BaseModel):
    id: int
    invoice_no: str
    order_type: str
    customer_id: str
    customer_name: str
    invoice_date: date
    currency: str
    status: str
    sync_status: str
    total_amount: Decimal
    item_count: int
    created_at: datetime


class InvoiceDetail(InvoiceListItem):
    remark: Optional[str] = None
    xiaoman_order_id: Optional[str] = None
    xiaoman_order_no: Optional[str] = None
    sync_error: Optional[str] = None
    synced_at: Optional[datetime] = None
    updated_at: datetime
    items: list[InvoiceItemResponse]


class ValidationIssue(BaseModel):
    field: str
    message: str


class InvoiceValidationResponse(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = []
