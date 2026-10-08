"""Strict wire inputs. Browser requests cannot supply authoritative prices or owners."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, StrictInt, model_validator


ShortText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)]
Reason = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
Money = Annotated[str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,11})\.[0-9]{2}$")]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
StableId = Annotated[str, StringConstraints(strict=True, pattern=r"^[1-9][0-9]{0,19}$")]
Quantity = Annotated[StrictInt, Field(ge=1, le=10000)]


class PortalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChallengeInput(PortalInput):
    email: Annotated[str, Field(min_length=3, max_length=254)]
    purpose: Literal["login", "activate"]
    invitation_token: Annotated[str, Field(min_length=32, max_length=128)] | None = None

    @model_validator(mode="after")
    def activation_requires_invite(self):
        if (self.purpose == "activate") != bool(self.invitation_token):
            raise ValueError("Activation requires an invitation token; login does not accept one")
        return self


class VerifyInput(PortalInput):
    challenge_id: UUID
    code: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9]{6}$")]


class Delivery(PortalInput):
    contact_name: ShortText
    phone: Annotated[str, Field(min_length=3, max_length=40)]
    address_line1: Annotated[str, Field(min_length=1, max_length=200)]
    address_line2: Annotated[str, Field(max_length=200)] = ""
    city: Annotated[str, Field(max_length=100)] = ""
    region: Annotated[str, Field(max_length=100)] = ""
    postal_code: Annotated[str, Field(max_length=32)] = ""
    country_code: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{2}$")]


class QuoteLine(PortalInput):
    item_id: UUID
    quantity: Quantity


class QuoteInput(PortalInput):
    items: Annotated[list[QuoteLine], Field(min_length=1, max_length=100)]
    delivery: Delivery
    customer_po: Annotated[str, Field(max_length=80)] = ""
    remark: Annotated[str, Field(max_length=1000)] = ""

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("Each item may occur only once")
        return self


class SubmitInput(PortalInput):
    quote_id: UUID
    quote_content_hash: Hash
    customer_po: Annotated[str, Field(max_length=80)] = ""
    remark: Annotated[str, Field(max_length=1000)] = ""


class AcceptInput(PortalInput):
    proposal_hash: Hash


class ReasonInput(PortalInput):
    reason: Reason


class ReorderInput(PortalInput):
    line_keys: Annotated[list[UUID], Field(min_length=1, max_length=100)] | None = None

    @model_validator(mode="after")
    def unique_lines(self):
        if self.line_keys is not None and len(set(self.line_keys)) != len(self.line_keys):
            raise ValueError("Each previous order line may occur only once")
        return self


class Fees(PortalInput):
    shipping_amount: Money
    packaging_amount: Money
    surcharge_amount: Money
    surcharge_name: Annotated[str, Field(max_length=100)] = ""

    @model_validator(mode="after")
    def named_surcharge(self):
        if self.surcharge_amount != "0.00" and not self.surcharge_name:
            raise ValueError("A nonzero surcharge needs a name")
        return self


class ProposalInput(QuoteInput):
    fees: Fees
    payment_terms: Annotated[str, Field(min_length=1, max_length=64)]
    valid_for_hours: Annotated[StrictInt, Field(ge=1, le=168)] = 24
    reason: Reason


class ApproveInput(PortalInput):
    accepted_revision_id: UUID


class PiProposalInput(PortalInput):
    invoice_document_version: Annotated[StrictInt, Field(ge=1)]
    valid_for_hours: Annotated[StrictInt, Field(ge=1, le=168)] = 24
    reason: Reason


class PublishPiInput(ApproveInput):
    invoice_document_version: Annotated[StrictInt, Field(ge=1)]


class VoidPiInput(ReasonInput):
    invoice_document_version: Annotated[StrictInt, Field(ge=1)]


class Capabilities(PortalInput):
    can_view_price: bool
    can_order: bool

    @model_validator(mode="after")
    def order_requires_price(self):
        if self.can_order and not self.can_view_price:
            raise ValueError("Ordering requires price access")
        return self


class CustomerCreate(PortalInput):
    binding_fingerprint: Hash
    canonical_customer_id: StableId
    assignment_id: StableId
    okki_identity_id: StableId
    catalog_item_ids: Annotated[list[UUID], Field(max_length=5000)]
    capabilities: Capabilities


class CustomerUpdate(PortalInput):
    status: Literal["enabled", "suspended"]
    capabilities: Capabilities
    catalog_item_ids: Annotated[list[UUID] | None, Field(max_length=5000)] = None
    reason: Reason


class CustomerCatalogUpdate(PortalInput):
    catalog_item_ids: Annotated[list[UUID], Field(max_length=5000)]
    reason: Reason


class InvitationInput(PortalInput):
    email: Annotated[str, Field(min_length=3, max_length=254)]
    contact_name: ShortText


class AccountUpdate(ReasonInput):
    status: Literal["active", "disabled", "invited"]


class TransferInput(ReasonInput):
    review_fingerprint: Hash
    assignment_id: StableId
    pending_request_ids: Annotated[list[UUID], Field(max_length=1000)]
    history_policy: Literal["remove", "explicit_grant"]
    history_days: Annotated[StrictInt, Field(ge=1, le=365)] | None = None


class RebindInput(ReasonInput):
    review_fingerprint: Hash
    identity_id: StableId


class MappingEntry(PortalInput):
    kind: Literal["sku", "model", "color"]
    source_key: Annotated[str, Field(min_length=1, max_length=128)]
    display_value: Annotated[str, Field(min_length=1, max_length=128)]
    item_id: UUID | None = None
    customer_sku: Annotated[str, Field(min_length=1, max_length=64)] | None = None


    @model_validator(mode="after")
    def validate_source_shape(self):
        if self.kind == "sku":
            if self.item_id is None or self.source_key != str(self.item_id):
                raise ValueError("SKU mappings require matching item_id and source_key")
        elif self.item_id is not None or self.customer_sku is not None:
            raise ValueError("Only a SKU mapping may specify item_id or customer_sku")
        return self


class MappingInput(PortalInput):
    base_version: Annotated[StrictInt, Field(ge=0)]
    entries: Annotated[list[MappingEntry], Field(max_length=15000)]


class EmptyInput(PortalInput):
    pass


class PaymentTerm(PortalInput):
    code: Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    display_text: Annotated[str, Field(min_length=1, max_length=256)]
    deposit_percent: Annotated[str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]?|100)\.[0-9]{2}$")]

    @model_validator(mode="after")
    def validate_term(self):
        from decimal import Decimal
        import unicodedata
        if Decimal(self.deposit_percent) > 100:
            raise ValueError("Deposit percentage cannot exceed 100")
        if any(unicodedata.category(c).startswith("C") for c in self.display_text) or "<" in self.display_text or ">" in self.display_text:
            raise ValueError("Payment terms must be plain text")
        return self


class SalesContact(PortalInput):
    user_id: StableId
    display_name: ShortText
    approved: bool = False
    email: Annotated[str, StringConstraints(strict=True, max_length=254,
        pattern=r"^[A-Za-z0-9.!#$%&'*+/=^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")] | None = None
    whatsapp: Annotated[str, StringConstraints(strict=True, pattern=r"^\+[1-9][0-9]{6,14}$")] | None = None

    @model_validator(mode="after")
    def validate_contact(self):
        import unicodedata
        if any(unicodedata.category(c).startswith("C") for c in self.display_name) or any(c in self.display_name for c in "<>"):
            raise ValueError("Contact display name must be plain text")
        if self.approved and not (self.email or self.whatsapp):
            raise ValueError("Approve at least one outward contact channel")
        return self


class SitePolicy(PortalInput):
    sales_contacts: Annotated[list[SalesContact], Field(max_length=200)] = Field(default_factory=list)
    quote_valid_minutes: Annotated[StrictInt, Field(ge=1, le=30)] = 15
    proposal_valid_hours: Annotated[list[Annotated[StrictInt, Field(ge=1, le=168)]], Field(min_length=1, max_length=8)] = Field(default_factory=lambda: [24, 48])
    payment_terms: Annotated[list[PaymentTerm], Field(max_length=20)] = Field(default_factory=list)
    default_payment_term_code: str | None = None

    @model_validator(mode="after")
    def unique_and_default(self):
        if len({contact.user_id for contact in self.sales_contacts}) != len(self.sales_contacts):
            raise ValueError("An employee may have only one approved contact profile")
        codes = [term.code for term in self.payment_terms]
        if len(set(codes)) != len(codes) or len(set(self.proposal_valid_hours)) != len(self.proposal_valid_hours):
            raise ValueError("Policy choices must be unique")
        if self.default_payment_term_code is not None and self.default_payment_term_code not in codes:
            raise ValueError("Default payment term must be one of the configured choices")
        if codes and self.default_payment_term_code is None:
            raise ValueError("Choose a default payment term")
        return self


class SiteUpdate(ReasonInput):
    name: ShortText
    status: Literal["enabled", "disabled"]
    policy: SitePolicy

    @model_validator(mode="after")
    def enabled_requires_terms(self):
        if self.status == "enabled" and not self.policy.payment_terms:
            raise ValueError("Configure approved payment terms before enabling the site")
        return self


StockDecimal = Annotated[str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,7})(\.[0-9]{1,6})?$")]


class CatalogConfiguration(ReasonInput):
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    color_name: Annotated[str, Field(min_length=1, max_length=128)]
    inventory_unit: Annotated[str, Field(min_length=1, max_length=32)]
    sale_unit: Annotated[str, Field(min_length=1, max_length=32)]
    conversion_factor: StockDecimal
    safety_buffer: StockDecimal
    min_qty: Quantity
    step_qty: Quantity

    @model_validator(mode="after")
    def validate_catalog_configuration(self):
        from decimal import Decimal
        import unicodedata
        if Decimal(self.conversion_factor) <= 0 or self.min_qty % self.step_qty:
            raise ValueError("Conversion must be positive and minimum a multiple of step")
        for value in (self.display_name, self.color_name, self.inventory_unit, self.sale_unit):
            if any(unicodedata.category(c).startswith("C") or c in "<>" for c in value):
                raise ValueError("Catalog labels must be plain text")
        return self


class CatalogImport(CatalogConfiguration):
    standard_fingerprint: Hash
    product_id: StableId
    sku_id: StableId
    product_kind: Literal["hair", "accessory"]


class CatalogUpdate(CatalogConfiguration):
    status: Literal["draft", "published", "disabled"]


class NotificationRetryInput(ReasonInput):
    fingerprint: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class CatalogImageInput(ReasonInput):
    asset_id: StableId | None
    asset_reference: Annotated[str, StringConstraints(strict=True, max_length=64,
        pattern=r"^[1-9][0-9]{0,19}:[A-Za-z0-9_-]{43}$")] | None = None

    @model_validator(mode="after")
    def require_preview_reference(self):
        if self.asset_id is not None and (self.asset_reference is None or self.asset_reference.split(':')[0] != self.asset_id):
            raise ValueError("Choose and preview the exact asset version before binding")
        if self.asset_id is None and self.asset_reference is not None:
            raise ValueError("Removing an image must not specify an asset version")
        return self
