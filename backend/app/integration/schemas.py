"""Strict request schemas for external-system administration and invoices."""

from datetime import date, datetime
from decimal import Decimal
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.core.time import to_beijing_naive


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _parse_json_decimal(value) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("金额必须使用 JSON 十进制字符串")
    normalized = value.strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", normalized) is None:
        raise ValueError("金额必须是有限十进制字符串")
    amount = Decimal(normalized)
    if not amount.is_finite():
        raise ValueError("金额必须是有限十进制字符串")
    return amount


JsonDecimal = Annotated[
    Decimal,
    BeforeValidator(_parse_json_decimal, json_schema_input_type=str),
]


class IntegrationAppCreate(StrictSchema):
    name: str = Field(min_length=2, max_length=100)
    owner_user_id: int = Field(ge=1)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def normalize_expires_at(cls, value: datetime | None) -> datetime | None:
        return to_beijing_naive(value)


class IntegrationAppRotate(StrictSchema):
    current_token_suffix: str = Field(min_length=6, max_length=6)


class CustomerContactSubmission(StrictSchema):
    name: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=256)
    phone: str | None = Field(default=None, max_length=100)


class CustomerSubmission(StrictSchema):
    ark_customer_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        pattern=r"^\d+$",
    )
    name: str | None = Field(default=None, min_length=1, max_length=256)
    contact: CustomerContactSubmission = Field(default_factory=CustomerContactSubmission)


class CatalogReference(StrictSchema):
    product_id: int = Field(gt=0, strict=True)
    sku_id: int = Field(gt=0, strict=True)


class ProductDescriptionSubmission(StrictSchema):
    product_display: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=128)
    color: str | None = Field(default=None, max_length=128)
    length: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, max_length=64)


class ProductResolutionRequest(StrictSchema):
    product_kind: Literal["hair", "accessory"]
    catalog_ref: CatalogReference | None = None
    description: ProductDescriptionSubmission = Field(
        default_factory=ProductDescriptionSubmission,
    )


class InvoiceLineSubmission(ProductResolutionRequest):
    external_line_id: str | None = Field(default=None, max_length=64)
    quantity: int = Field(gt=0, le=2_147_483_647, strict=True)
    unit_price: JsonDecimal = Field(gt=0, max_digits=12, decimal_places=4)
    discount_amount: JsonDecimal = Field(
        default=Decimal("0"), le=0, max_digits=14, decimal_places=2,
    )


class DeliverySubmission(StrictSchema):
    address: str | None = None
    express_channel: str | None = Field(default=None, max_length=64)


class SurchargeSubmission(StrictSchema):
    name: str | None = Field(default=None, max_length=128)
    amount: JsonDecimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2,
    )


class FeeSubmission(StrictSchema):
    packaging_amount: JsonDecimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2,
    )
    packaging_quantity: int = Field(
        default=0, ge=0, le=2_147_483_647, strict=True,
    )
    shipping_amount: JsonDecimal = Field(
        default=Decimal("0"), ge=0, max_digits=14, decimal_places=2,
    )
    surcharge: SurchargeSubmission = Field(default_factory=SurchargeSubmission)


class DeclaredTotals(StrictSchema):
    product_amount: JsonDecimal = Field(ge=0, max_digits=14, decimal_places=2)
    total_amount: JsonDecimal = Field(ge=0, max_digits=14, decimal_places=2)


class InvoiceSubmission(StrictSchema):
    schema_version: Literal["1.0"]
    external_order_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    order_type: Literal["stock", "production"]
    invoice_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer: CustomerSubmission
    delivery: DeliverySubmission
    fees: FeeSubmission = Field(default_factory=FeeSubmission)
    declared_totals: DeclaredTotals | None = None
    items: list[InvoiceLineSubmission] = Field(min_length=1, max_length=200)
    payment_term: str | None = Field(default=None, max_length=256)
    remark: str | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value) -> str:
        return str(value or "").strip().upper()

    @field_validator("invoice_date", mode="before")
    @classmethod
    def require_iso_json_date(cls, value) -> date:
        if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
            raise ValueError("invoice_date 必须是 YYYY-MM-DD ISO 日期")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("invoice_date 必须是有效的 ISO 日期") from exc


class IntegrationValidationIssue(StrictSchema):
    code: str
    field: str
    message: str


class CanonicalCustomerContact(StrictSchema):
    name: str | None
    email: str | None
    phone: str | None


class CanonicalCustomer(StrictSchema):
    ark_customer_id: str
    name: str
    country_name: str | None
    contact: CanonicalCustomerContact


class CanonicalCatalogReference(StrictSchema):
    product_id: int
    sku_id: int


class CanonicalProductDescription(StrictSchema):
    product_name: str
    product_display: str
    model: str
    color: str
    length: str
    unit: str


class CanonicalProduct(StrictSchema):
    product_kind: Literal["hair", "accessory"]
    catalog_ref: CanonicalCatalogReference
    description: CanonicalProductDescription


class CustomerResolveData(StrictSchema):
    customer: CanonicalCustomer


class CustomerResolveSuccessEnvelope(StrictSchema):
    code: Literal[200]
    message: Literal["ok"]
    data: CustomerResolveData


class ProductResolveData(StrictSchema):
    item: CanonicalProduct


class ProductResolveSuccessEnvelope(StrictSchema):
    code: Literal[200]
    message: Literal["ok"]
    data: ProductResolveData


class InvoiceValidationDelivery(StrictSchema):
    address: str | None
    express_channel: str | None


class InvoiceValidationSurcharge(StrictSchema):
    name: str | None
    amount: str = Field(pattern=r"^\d+\.\d{2}$")


class InvoiceValidationFees(StrictSchema):
    packaging_amount: str = Field(pattern=r"^\d+\.\d{2}$")
    packaging_quantity: int
    shipping_amount: str = Field(pattern=r"^\d+\.\d{2}$")
    surcharge: InvoiceValidationSurcharge


class InvoiceValidationLine(StrictSchema):
    external_line_id: str | None
    product_kind: Literal["hair", "accessory"]
    catalog_ref: CanonicalCatalogReference
    description: CanonicalProductDescription
    quantity: int
    unit_price: str = Field(pattern=r"^\d+\.\d{4}$")
    discount_amount: str = Field(pattern=r"^-?\d+\.\d{2}$")
    standard_price: str | None = Field(pattern=r"^\d+\.\d{4}$")
    customer_price: str | None = Field(pattern=r"^\d+\.\d{4}$")
    price_source: str
    total_price: str = Field(pattern=r"^\d+\.\d{2}$")


class InvoiceValidationTotals(StrictSchema):
    product_amount: str = Field(pattern=r"^\d+\.\d{2}$")
    total_amount: str = Field(pattern=r"^\d+\.\d{2}$")


class InvoiceValidationData(StrictSchema):
    schema_version: Literal["1.0"]
    external_order_id: str
    order_type: Literal["stock", "production"]
    invoice_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    customer: CanonicalCustomer
    delivery: InvoiceValidationDelivery
    fees: InvoiceValidationFees
    payment_term: str | None
    remark: str | None
    items: list[InvoiceValidationLine]
    totals: InvoiceValidationTotals
    warnings: list[IntegrationValidationIssue]


class InvoiceValidationSuccessEnvelope(StrictSchema):
    code: Literal[200]
    message: Literal["ok"]
    data: InvoiceValidationData


class InvoiceValidationErrorData(StrictSchema):
    issues: list[IntegrationValidationIssue]
    warnings: list[IntegrationValidationIssue]


class InvoiceValidationErrorEnvelope(StrictSchema):
    code: Literal[422]
    message: Literal["invoice validation failed"]
    data: InvoiceValidationErrorData
