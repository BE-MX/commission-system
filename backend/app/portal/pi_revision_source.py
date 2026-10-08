"""Capture a live PI as immutable customer evidence, without repricing or rewriting it.

Caller owns the authority barrier, invoice/items locks, authorization and transaction.
All source reads are local; unknown terms, identities or inventory fail closed.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.invoice import service as invoices
from app.portal import catalog_service, invoice_evidence, mapping_service, proposal_service, revision_evidence, sku_source, pi_presentation
from app.portal.domain import content_hash, line_amount, total_amount
from app.portal.errors import reject
from app.portal.inventory import validate_observation
from app.portal.models import RequestLine, Revision
from app.portal.schemas import SitePolicy


def amount(value, *, nullable=False):
    if value is None and nullable:
        return Decimal("0")
    if value is None or not Decimal(value).is_finite():
        reject("INVOICE_VALIDATION_FAILED", "PI amounts need review.", 409)
    return Decimal(value)


def validated_rows(db, access, site, invoice, items):
    """Resolve actual invoice rows to currently authorized, exact standard SKUs."""
    if not 1 <= len(items) <= 100:
        reject("INVOICE_VALIDATION_FAILED", "PI must contain between 1 and 100 distinct products.", 409)
    namespace = get_settings().PORTAL_OKKI_NAMESPACE
    if not namespace or access.okki_namespace != namespace:
        reject("SKU_UNAVAILABLE", "The customer product source needs review.", 409)
    catalog = catalog_service.authorized_items(db, SimpleNamespace(access=access, site=site))
    by_sku = {}
    for item in catalog:
        key = (item.product_kind, item.product_id, item.sku_id)
        if key in by_sku:
            reject("SKU_UNAVAILABLE", "The catalog contains an ambiguous SKU.", 409)
        by_sku[key] = item
    aliases = {row["item_id"]:row for row in mapping_service.current_projection(db, access)}
    resolved, seen = [], set()
    for row in sorted(items, key=lambda row:(row.sort_order, row.id)):
        key = (row.product_kind, str(row.product_id), str(row.sku_id))
        item = by_sku.get(key)
        if row.item_type != "stock" or item is None or key in seen or item.public_id not in aliases:
            reject("SKU_UNAVAILABLE", "PI products need catalog review.", 409)
        if item.source_namespace != access.okki_namespace:
            reject("SKU_UNAVAILABLE", "The customer and product sources do not match.", 409)
        seen.add(key)
        source = sku_source.revalidate(db, item)["standard_json"]
        for field, standard in (("product_name","product_name"), ("product_display","product_display"),
                ("model","model"), ("color","color"), ("length","length"), ("net_weight_grams","weight")):
            if str(getattr(row, field) or "") != str(source.get(standard) or ""):
                reject("SKU_CHANGED", "PI specifications do not match the authorized standard SKU.", 409)
        if row.quantity is None or row.quantity <= 0 or amount(row.price_per_piece) <= 0 or amount(row.discount_amount) > 0:
            reject("INVOICE_VALIDATION_FAILED", "PI quantities or prices need review.", 409)
        if line_amount(row.quantity, row.price_per_piece, row.discount_amount) != amount(row.total_price):
            reject("INVOICE_AMOUNT_MISMATCH", "PI line amounts need review.", 409)
        resolved.append((row, item, source, aliases[item.public_id]))
    if not resolved:
        reject("INVOICE_VALIDATION_FAILED", "PI needs at least one product.", 409)
    observations = catalog_service.load_observations(db, [entry[1] for entry in resolved])
    for row, item, _, _ in resolved:
        validate_observation(observations.get(item.public_id), now=beijing_now(),
            max_age_seconds=get_settings().PORTAL_INVENTORY_MAX_AGE_SECONDS, quantity=row.quantity,
            inventory_unit=item.inventory_unit, conversion_factor=item.conversion_factor,
            safety_buffer=item.safety_buffer, minimum=item.min_qty, step=item.step_qty)
    return resolved


def build(db, access, site, order, invoice, items, *, actor_id, valid_for_hours):
    if (invoice.source_type != "portal" or invoice.source_order_id != order.public_id
            or order.invoice_id != invoice.id or invoice.customer_id != access.okki_company_id
            or order.customer_id_snapshot != access.customer_id or order.okki_company_id_snapshot != access.okki_company_id
            or invoice.status in {"cancelled", "cancel_pending"} or invoice.currency != site.currency or invoice.currency != "USD"):
        reject("PI_REVISION_PENDING", "PI identity or status needs review.", 409)
    if invoice.order_type != "stock" or invoice.invoice_date is None or not invoice.invoice_no:
        reject("INVOICE_VALIDATION_FAILED", "PI date, number or order type needs review.", 409)
    try:
        policy = SitePolicy.model_validate(site.policy_json)
    except ValidationError:
        reject("POLICY_UNAVAILABLE", "Trading policy needs review.", 503)
    terms = [term for term in policy.payment_terms if term.display_text == invoice.payment_term]
    if valid_for_hours is None:
        valid_for_hours = policy.proposal_valid_hours[0]  # Validation-only capture; never persisted.
    if len(terms) != 1 or valid_for_hours not in policy.proposal_valid_hours:
        reject("CUSTOMER_ACCEPTANCE_REQUIRED", "Complete the configured PI payment terms and validity first.", 409)
    if not invoice.contact_name or not invoice.contact_phone or not invoice.delivery_address or not invoice.customer_name:
        reject("INVOICE_VALIDATION_FAILED", "Complete the PI customer and delivery details first.", 409)
    if invoices.validate_invoice(SimpleNamespace(customer_id=invoice.customer_id, items=items)):
        reject("INVOICE_VALIDATION_FAILED", "PI validation failed.", 409)
    resolved = validated_rows(db, access, site, invoice, items)
    fees = [amount(invoice.shipping_fee), amount(invoice.internal_accessory), amount(invoice.surcharge_amount)]
    products, total = total_amount([row.total_price for row in items], *fees)
    if (any(value < 0 for value in fees) or products != amount(invoice.product_amount)
            or total != amount(invoice.total_amount) or (fees[2] and not invoice.surcharge_name)):
        reject("INVOICE_AMOUNT_MISMATCH", "PI totals or fees need review.", 409)
    previous = db.scalar(select(Revision).where(Revision.request_id == order.id).order_by(Revision.revision_no.desc()).limit(1))
    old = [] if previous is None else db.scalars(select(RequestLine).where(RequestLine.revision_id == previous.id)).all()
    if previous is not None:
        revision_evidence.verify(previous, old)
    keys = {(row.product_kind,row.product_id,row.sku_id):row.line_key for row in old}
    fingerprint = invoice_evidence.fingerprint(invoice, items)
    authority = proposal_service.company_versions(access, site)
    authority.update(invoice_document_hash=fingerprint, invoice_sales_user_id=invoice.sales_user_id)
    delivery = {"contact_name":invoice.contact_name,"phone":invoice.contact_phone,"formatted_address":invoice.delivery_address}
    if previous is not None:
        prior_address = previous.delivery_json.get("formatted_address") or "\n".join(previous.delivery_json[key]
            for key in ("address_line1","address_line2","city","region","postal_code","country_code") if previous.delivery_json.get(key))
        if prior_address == invoice.delivery_address:
            delivery = {**deepcopy(previous.delivery_json),"contact_name":invoice.contact_name,"phone":invoice.contact_phone}
    revision = Revision(public_id=str(uuid4()), request_id=order.id,
        revision_no=(db.scalar(select(func.max(Revision.revision_no)).where(Revision.request_id == order.id)) or 0)+1,
        kind="pi_amendment", currency=invoice.currency, product_amount=products,
        shipping_amount=fees[0], packaging_amount=fees[1], surcharge_amount=fees[2], surcharge_name=invoice.surcharge_name or "",
        total_amount=total, fees_status="confirmed", delivery_json=delivery,
        payment_terms_snapshot=terms[0].model_dump(mode="json"),
        expires_at=beijing_now().replace(microsecond=0)+timedelta(hours=valid_for_hours),
        authority_versions_json=authority, remark=invoice.remark or "", mapping_version=access.mapping_version,
        invoice_presentation_json=pi_presentation.capture(invoice),
        pricing_fingerprint=fingerprint, bound_invoice_document_version=invoice.portal_document_version, created_by=actor_id)
    records = []
    for row, item, standard, display in resolved:
        records.append(RequestLine(line_key=keys.get((row.product_kind,str(row.product_id),str(row.sku_id)), str(uuid4())),
            catalog_item_id=item.id, product_kind=row.product_kind, product_id=str(row.product_id), sku_id=str(row.sku_id),
            standard_json=deepcopy(standard), customer_display_json=deepcopy(display), mapping_version=access.mapping_version,
            qty=row.quantity, unit_price=amount(row.price_per_piece), discount_amount=amount(row.discount_amount),
            line_amount=amount(row.total_price), unit_weight_grams=item.conversion_factor if item.inventory_unit == "g" else None,
            price_source="ark_invoice", price_fingerprint=content_hash({"invoice":fingerprint,"item_id":row.id})))
    revision.content_hash = revision_evidence.digest(revision, records)
    return revision, records
