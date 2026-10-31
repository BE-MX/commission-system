"""Local commands carry stable customer/SKU identity and explicit money."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.trade.schemas import DepartmentShares
from app.invoice.schemas import InvoiceItemGroupPayload


class LocalItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(None, gt=0)
    group_key: str | None = Field(None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    local_sku_id: int = Field(gt=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    price_per_piece: Decimal = Field(ge=0, max_digits=12, decimal_places=4)
    discount_amount: Decimal = Field(default=Decimal("0"), le=0, max_digits=14, decimal_places=2)
    commercial_kind: Literal["sample", "bulk"] = "bulk"


class LocalInvoiceDraft(DepartmentShares):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_./-]+$")
    expected_authority_epoch: int | None = Field(default=None, ge=1)
    expected_version: int = Field(default=0, ge=0)
    invoice_no: str | None = Field(None, min_length=1, max_length=56)
    local_customer_id: int = Field(gt=0)
    sales_user_id: int = Field(gt=0)
    merchandiser_id: int | None = Field(None, gt=0)
    order_type: Literal["stock", "production", "presale"] = "stock"
    invoice_date: date
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    contact_name: str | None = Field(None, max_length=256)
    contact_phone: str | None = Field(None, max_length=100)
    contact_email: str | None = Field(None, max_length=256)
    delivery_address: str | None = Field(None, max_length=4000)
    express_channel: str | None = Field(None, max_length=64)
    shipping_fee: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    surcharge_name: str | None = Field(None, max_length=128)
    surcharge_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    packaging_quantity: int = Field(default=0, strict=True, ge=0, le=2147483647)
    internal_accessory: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    local_deposit_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    local_deposit_charge: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    payment_term: str | None = Field(None, max_length=256)
    remark: str | None = Field(None, max_length=4000)
    commercial_source: Literal["alibaba_inquiry", "alibaba_ecosystem", "social_owned", "social_assigned", "referral", "website", "other", "unknown"] = "unknown"
    is_new_deal: bool | None = None
    is_first_return: bool | None = None
    is_private_order: bool = False
    inspection_requirement: Literal["single", "detail"] | None = None
    item_groups: list[InvoiceItemGroupPayload] | None = Field(None, max_length=100)
    expected_groups_version: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    items: list[LocalItem] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_presale(self):
        if self.order_type == "presale" and self.shipping_fee:
            raise ValueError("预售主单不含运费，请在分批发货时登记")
        if self.order_type != "presale" and (self.local_deposit_amount or self.local_deposit_charge):
            raise ValueError("仅预售订单可约定末批抵扣首款")
        if self.local_deposit_charge > self.surcharge_amount or self.local_deposit_charge > self.local_deposit_amount:
            raise ValueError("首款费用不能超过首款总额或合同附加费")
        return self


class LocalInvoiceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_./-]+$")
    expected_authority_epoch: int | None = Field(default=None, ge=1)
    expected_version: int = Field(ge=0)
    warehouse_id: int | None = Field(None, gt=0)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_reason(self):
        if not self.reason.strip():
            raise ValueError("必须填写操作原因")
        return self


class LocalInvoiceAmend(LocalInvoiceDraft):
    business_date: date
    warehouse_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=500)
