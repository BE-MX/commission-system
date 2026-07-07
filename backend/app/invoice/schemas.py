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


class InvoiceItemPayload(BaseModel):
    product_id: int
    sku_id: Optional[int] = None
    product_name: str = Field(..., max_length=512)
    product_display: str = Field(..., max_length=256)
    net_weight_grams: str = Field(..., max_length=64)
    curl: Optional[str] = Field(None, max_length=64)
    model: str = Field(..., max_length=128)
    color: str = Field(..., max_length=128)
    length: str = Field(..., max_length=128)
    quantity: int = Field(..., gt=0)
    price_per_piece: Optional[Decimal] = Field(None, gt=0)
    price_source: str = Field(default="manual", max_length=32)


class InvoiceCreate(BaseModel):
    customer_id: str = Field(..., max_length=64)
    customer_name: str = Field(..., max_length=256)
    invoice_date: date
    currency: str = Field(default="USD", max_length=16)
    remark: Optional[str] = None
    items: list[InvoiceItemPayload] = Field(default_factory=list)

    @field_validator("customer_id", mode="before")
    @classmethod
    def _coerce_customer_id(cls, value):
        return "" if value is None else str(value)


class InvoiceUpdate(BaseModel):
    customer_id: str = Field(..., max_length=64)
    customer_name: str = Field(..., max_length=256)
    invoice_date: date
    currency: str = Field(default="USD", max_length=16)
    remark: Optional[str] = None
    items: list[InvoiceItemPayload] = Field(default_factory=list)

    @field_validator("customer_id", mode="before")
    @classmethod
    def _coerce_customer_id(cls, value):
        return "" if value is None else str(value)


class InvoiceItemResponse(InvoiceItemPayload):
    id: int
    total_price: Decimal
    sort_order: int

    model_config = {"from_attributes": True}


class InvoiceListItem(BaseModel):
    id: int
    invoice_no: str
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
