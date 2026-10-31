"""Exact legacy inputs -> real local commands, never formal output imports."""
import hashlib
from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.commerce_shadow.dispatcher import UnsupportedCommand, snapshot
from app.commerce_shadow.models import ShadowExecution


class LegacyLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_item_id: int = Field(gt=0)
    external_product_id: str | None
    external_sku_id: str | None = ""
    quantity: int = Field(strict=True, gt=0)
    price_per_piece: Decimal | None = None
    total_price: Decimal
    discount_amount: Decimal = Decimal("0")
    commercial_kind: str | None = None
    item_type: str = "stock"
    source_line_state: str | None = None


class LegacyContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_namespace: str
    tenant: str
    customer_external_id: str
    source_invoice_id: int | None = None
    invoice_no: str
    invoice_date: date
    currency: str
    order_type: str
    sales_user_id: int = Field(gt=0)
    product_amount: Decimal | None = None
    total_amount: Decimal | None = None
    shipping_fee: Decimal
    surcharge_amount: Decimal
    internal_accessory: Decimal | None = Decimal("0")
    surcharge_name: str | None = None
    local_deposit_amount: Decimal | None = Decimal("0")
    local_deposit_charge: Decimal | None = Decimal("0")
    discount_amount: Decimal | None = None
    warehouse_id: int | None = None
    is_new_deal: bool | None = None
    is_first_return: bool | None = None
    is_private_order: bool = False
    okki_new_deal: int | None = None
    okki_free_shipping: int | None = None
    okki_first_return: int | None = None
    commercial_source: str = "unknown"
    payment_term: str | None = None
    items: list[LegacyLine] = Field(min_length=1)
    previous_source_item_ids: list[int] | None = None
    previous_contract_ref: dict | None = None


def _key(dataset, identity, suffix):
    return "shadow:" + hashlib.sha256((dataset + "\0" + identity + "\0" + suffix).encode()).hexdigest()[:56]


def customer(db, source, tenant, external_id):
    from app.customer.models import CustomerExternalIdentity
    from app.customer.transaction_identity import current_customer
    if not source or not tenant:
        raise UnsupportedCommand("missing_legacy_tenant_namespace")
    rows = db.scalars(select(CustomerExternalIdentity).where(
        CustomerExternalIdentity.source_system == source, CustomerExternalIdentity.source_account_key == tenant,
        CustomerExternalIdentity.identifier_type == "company_id", CustomerExternalIdentity.normalized_value == str(external_id),
        CustomerExternalIdentity.identity_strength == "strong", CustomerExternalIdentity.cardinality == "one_to_one",
        CustomerExternalIdentity.verification_status == "verified", CustomerExternalIdentity.status == "active",
        CustomerExternalIdentity.customer_id.isnot(None))).all()
    if len(rows) != 1:
        raise UnsupportedCommand("legacy_customer_mapping_missing_or_ambiguous")
    from app.customer.models import CustomerObjectOwnership
    owners = db.scalars(select(CustomerObjectOwnership.current_customer_id).where(
        CustomerObjectOwnership.object_type == "external_identity", CustomerObjectOwnership.object_id == rows[0].id)).all()
    if len(owners) > 1:
        raise UnsupportedCommand("legacy_customer_mapping_ownership_ambiguous")
    return current_customer(db, owners[0] if owners else rows[0].customer_id)


def sku(db, source, tenant, product_id, sku_id):
    from app.catalog.models import CatalogExternalIdentity, CatalogSku, CatalogProduct
    rows = db.scalars(select(CatalogExternalIdentity).where(CatalogExternalIdentity.source == source,
        CatalogExternalIdentity.tenant == tenant, CatalogExternalIdentity.external_product_id == str(product_id),
        CatalogExternalIdentity.external_sku_id == (str(sku_id) if sku_id is not None else ""))).all()
    if len(rows) != 1:
        raise UnsupportedCommand("legacy_sku_mapping_missing_or_ambiguous")
    result = db.get(CatalogSku, rows[0].sku_id)
    product = db.get(CatalogProduct, result.product_id) if result else None
    if result is None or product is None or not result.active or not product.active or result.unit != "piece":
        raise UnsupportedCommand("legacy_sku_mapping_inactive_or_wrong_unit")
    return result.id


def line_price(line):
    price = line.price_per_piece
    if price is None:
        price = (line.total_price - line.discount_amount) / line.quantity
        if price != price.quantize(Decimal("0.0001")):
            raise UnsupportedCommand("legacy_unit_price_not_exactly_representable")
    return price


def expected_order(command_input):
    """Read-only source evidence normalization; never called by execute_order."""
    contract = LegacyContract.model_validate(command_input["contract"])
    if contract.product_amount is None or contract.total_amount is None:
        raise UnsupportedCommand("legacy_formal_contract_totals_not_captured")
    return {"metrics": {"commerce_status": "confirmed", "currency": contract.currency,
        "product_amount": format(contract.product_amount, "f"), "total_amount": format(contract.total_amount, "f"),
        "lines": [{"quantity": row.quantity, "unit_price": format(line_price(row), "f"),
            "discount_amount": format(row.discount_amount, "f"), "amount": format(row.total_price, "f")} for row in contract.items]},
        "identities": {"id": contract.source_invoice_id,
            **{f"item_{index}": row.source_item_id for index, row in enumerate(contract.items)}}}


def invoice_target(db, dataset_id, source_invoice_id, checkpoint):
    for row in db.scalars(select(ShadowExecution).where(ShadowExecution.dataset_id == dataset_id,
            ShadowExecution.aggregate_key == f"invoice:{source_invoice_id}").order_by(ShadowExecution.causal_version.desc())):
        if row.outcome == "accepted" and row.actual.get("domain_type") == "contract":
            return row.actual["identities"]["id"], row.actual["identities"]
    identity_map = checkpoint.get("identity_map", {})
    target = identity_map.get(f"invoice:{source_invoice_id}")
    if target:
        return target, {key.split(":", 1)[1]: value for key, value in identity_map.items() if key.startswith("invoice_item:")}
    return None, {}


def execute_order(db, *, dataset_id, command, actor_id, checkpoint):
    from app.invoice import commerce_service as commerce
    from app.invoice.commerce_schemas import LocalInvoiceDraft, LocalInvoiceAction, LocalInvoiceAmend
    from app.invoice.models import Invoice, InvoiceCommerceEvent
    raw = command["body"]
    contract = LegacyContract.model_validate(raw["contract"])
    actor = command["actor"]
    if str(actor.get("sub")) != str(actor_id) or not actor.get("roles"):
        raise UnsupportedCommand("legacy_authorization_snapshot_missing")
    from app.commerce_shadow.dispatcher import require_permissions
    require_permissions(actor, "invoice:write")
    buyer = customer(db, contract.source_namespace, contract.tenant, contract.customer_external_id)
    if len({row.source_item_id for row in contract.items}) != len(contract.items):
        raise UnsupportedCommand("legacy_duplicate_stable_line_identity")
    payload = raw.get("original_payload", {})
    if len(payload.get("product_list", contract.items)) != len(contract.items):
        raise UnsupportedCommand("legacy_aggregate_line_mapping_incomplete")
    items = []
    for row in contract.items:
        if row.item_type != "stock" or not row.external_product_id:
            raise UnsupportedCommand("legacy_nonstandard_aggregate_requires_explicit_line_map")
        if row.commercial_kind not in {"bulk", "sample"}:
            raise UnsupportedCommand("legacy_commercial_kind_not_classified")
        items.append({"local_sku_id": sku(db, contract.source_namespace, contract.tenant,
            row.external_product_id, row.external_sku_id), "quantity": row.quantity,
            "price_per_piece": line_price(row), "discount_amount": row.discount_amount, "commercial_kind": row.commercial_kind})
    # Formal totals are deliberately NOT assigned to LocalInvoiceDraft/Invoice.
    values = {key: getattr(contract, key) for key in ("invoice_no", "invoice_date", "currency", "order_type", "sales_user_id",
        "shipping_fee", "surcharge_amount", "surcharge_name", "internal_accessory", "local_deposit_amount", "local_deposit_charge",
        "is_new_deal", "is_first_return", "is_private_order", "commercial_source", "payment_term")}
    if contract.order_type == "presale" and (not contract.local_deposit_amount or contract.local_deposit_charge is None):
        raise UnsupportedCommand("legacy_presale_deposit_agreement_missing")
    for field in ("internal_accessory", "local_deposit_amount", "local_deposit_charge"):
        values[field] = values[field] or Decimal("0")
    if values["is_new_deal"] is None and contract.okki_new_deal is not None:
        values["is_new_deal"] = bool(contract.okki_new_deal)
    if values["is_first_return"] is None and contract.okki_first_return is not None:
        values["is_first_return"] = bool(contract.okki_first_return)
    original_key = raw["request_key"]
    values.update(request_key=_key(dataset_id, original_key, "create"), expected_version=0,
                  local_customer_id=buyer, items=items, expected_authority_epoch=1)
    warehouse_id = contract.warehouse_id
    if contract.order_type == "stock" and not warehouse_id:
        mapping = checkpoint.get("legacy_order_warehouses", {}).get(str(contract.source_invoice_id))
        if not mapping or not mapping.get("review_reference"):
            raise UnsupportedCommand("legacy_stock_warehouse_checkpoint_missing")
        warehouse_id = mapping.get("warehouse_id")
    existing, identities = invoice_target(db, dataset_id, contract.source_invoice_id, checkpoint) if contract.source_invoice_id else (None, {})
    prior_create = db.scalar(select(InvoiceCommerceEvent).where(
        InvoiceCommerceEvent.request_key == _key(dataset_id, original_key, "create")))
    if prior_create is not None and not payload.get("order_id"):
        # A rejected source attempt may have independently succeeded here. Its
        # later retry is the same command, not an amendment/new confirmation.
        invoice = commerce.create_draft(db, LocalInvoiceDraft.model_validate(values), actor)
    elif existing is not None:
        invoice = db.get(Invoice, existing)
        before_ids = contract.previous_source_item_ids
        if before_ids is None:
            before_ids = checkpoint.get("legacy_contract_items", {}).get(str(contract.source_invoice_id))
        for index, row in enumerate(contract.items):
            identity = identities.get(f"source_item:{row.source_item_id}") or identities.get(str(row.source_item_id))
            if identity is None:
                if before_ids is not None and row.source_line_state == "new" and row.source_item_id not in before_ids:
                    continue
                raise UnsupportedCommand("legacy_amendment_line_checkpoint_missing")
            values["items"][index]["id"] = identity
        values.update(request_key=_key(dataset_id, original_key, "amend"), expected_version=invoice.commerce_version,
            business_date=contract.invoice_date, warehouse_id=warehouse_id, reason="Isolated legacy contract revision")
        invoice = commerce.amend(db, existing, LocalInvoiceAmend.model_validate(values), actor)
    else:
        if payload.get("order_id"):
            raise UnsupportedCommand("legacy_existing_order_checkpoint_missing")
        invoice = commerce.create_draft(db, LocalInvoiceDraft.model_validate(values), actor)
        invoice = commerce.confirm(db, invoice.id, LocalInvoiceAction(request_key=_key(dataset_id, original_key, "confirm"),
            expected_version=invoice.commerce_version, expected_authority_epoch=1,
            warehouse_id=warehouse_id, reason="Independent legacy contract verification"), actor)
    result = snapshot(db, "contract.confirm", invoice, checkpoint=checkpoint, check_invariants=True)
    result["identities"].update({f"source_item:{source.source_item_id}": target.id
        for source, target in zip(contract.items, sorted(invoice.items, key=lambda row: row.sort_order))})
    result["adapter"] = "legacy.order.push"
    return result


def expected_receipt(raw):
    from app.commerce_shadow.legacy_money import expected
    return expected(raw)


def execute_receipt(db, **values):
    from app.commerce_shadow.legacy_money import execute
    return execute(db, **values)


def expected_outbound(raw):
    from app.commerce_shadow.legacy_shipment import expected
    return expected(raw)


def execute_outbound(db, **values):
    from app.commerce_shadow.legacy_shipment import execute
    return execute(db, **values)
