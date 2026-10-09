"""Server-priced, immutable customer quotes. Caller owns commit/rollback.

Source reads are local mirror/database reads only. A future remote inventory
adapter must prefetch outside the authorization transaction, never do network
I/O from load_observations while the authority barrier is held.
"""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal import auth_service as auth, catalog_service, mapping_service, pricing, sku_source
from app.portal.domain import content_hash, line_amount, total_amount
from app.portal.errors import PortalError, reject
from app.portal.inventory import validate_observation
from app.portal.models import AuditEvent, Quote
from app.portal.schemas import SitePolicy


def require_writes():
    auth.require_enabled()
    if not get_settings().PORTAL_WRITES_ENABLED:
        reject("SERVICE_UNAVAILABLE", "Order requests are not available yet.", 503)


def authority_snapshot(principal):
    return {"account": principal.account.auth_version, "membership": principal.membership.version,
            "access": principal.access.auth_version, "catalog": principal.access.catalog_version,
            "mapping": principal.access.mapping_version, "policy": principal.site.policy_version,
            "binding": principal.access.binding_fingerprint}


def evidence(row):
    return {"quote_id": row.public_id, "access_id": str(row.access_id),
            "account_id": str(row.account_id), "membership_id": str(row.membership_id),
            "expires_at": row.expires_at.isoformat(), "authority": row.authority_versions_json,
            "currency": row.currency, "product_amount": format(row.product_amount, ".2f"),
            "fees_status": row.fees_status, "total_amount": None if row.total_amount is None else format(row.total_amount, ".2f"),
            "items": row.lines_json, "delivery": row.delivery_json,
            "payment_terms": row.payment_terms_snapshot, "customer_po": row.customer_po,
            "remark": row.remark, "input_hash": row.input_hash}


def view(row):
    if content_hash(evidence(row)) != row.result_hash:
        reject("QUOTE_UNAVAILABLE", "This quote needs review. Please request a new quote.", 409)
    public_fields = ("line_key", "item_id", "display_snapshot", "quantity", "unit_price",
                     "discount_amount", "line_amount", "inventory_observed_at")
    return {"quote_id": row.public_id, "expires_at": row.expires_at.isoformat(),
            "status": "expired" if row.status == "valid" and row.expires_at <= beijing_now() else row.status,
            "content_hash": row.result_hash, "currency": row.currency,
            "items": [{**{key: deepcopy(line[key]) for key in public_fields},
                       "min_order_qty": line["inventory_snapshot"]["min_qty"],
                       "step_qty": line["inventory_snapshot"]["step_qty"]} for line in row.lines_json],
            "product_amount": format(row.product_amount, ".2f"),
            "fees": {"status": row.fees_status, "shipping_amount": None,
                     "packaging_amount": None, "surcharge_amount": None},
            "total_amount": None, "payment_terms_snapshot": deepcopy(row.payment_terms_snapshot),
            "delivery": deepcopy(row.delivery_json), "customer_po": row.customer_po,
            "remark": row.remark,
            "inventory_observed_at": min(line["inventory_observed_at"] for line in row.lines_json)}


def build_lines(db, access, site, requested_items):
    """Caller has already authenticated and authorized this company operation."""
    requested = {str(line.item_id): line.quantity for line in requested_items}
    rows = [item for item in catalog_service.authorized_items(db, SimpleNamespace(access=access, site=site)) if item.public_id in requested]
    if len(rows) != len(requested):
        available = {item.public_id for item in rows}
        # Echo only submitted public IDs. Absent, withdrawn and unauthorized are indistinguishable.
        raise PortalError("RESOURCE_NOT_FOUND", "Remove the unavailable products marked in your selection and review again.", 404,
            issues=[{"item_id": item_id, "code": "ITEM_UNAVAILABLE"}
                    for item_id in requested if item_id not in available])
    identities = {(item.source_namespace, item.product_id, item.sku_id) for item in rows}
    if len(identities) != len(rows):
        reject("INVALID_INPUT", "A standard SKU may occur only once.", 422)
    aliases = {line["item_id"]: line for line in mapping_service.current_projection(db, access)}
    observations = catalog_service.load_observations(db, rows)
    lines = []
    for item in rows:
        standard = sku_source.revalidate(db, item)
        price = pricing.resolve(db, access, item, site.currency)
        quantity = requested[item.public_id]
        observation = observations.get(item.public_id)
        validate_observation(observation, now=beijing_now(),
            max_age_seconds=get_settings().PORTAL_INVENTORY_MAX_AGE_SECONDS,
            quantity=quantity, inventory_unit=item.inventory_unit,
            conversion_factor=item.conversion_factor, safety_buffer=item.safety_buffer,
            minimum=item.min_qty, step=item.step_qty)
        amount = line_amount(quantity, price.amount)
        lines.append({"line_key": str(uuid4()), "item_id": item.public_id,
            "display_snapshot": deepcopy(aliases[item.public_id]), "quantity": quantity,
            "unit_price": format(price.amount, ".4f"), "discount_amount": "0.00",
            "line_amount": format(amount, ".2f"), "inventory_observed_at": observation.observed_at.isoformat(),
            "standard_snapshot": standard, "catalog_item_version": item.row_version,
            "price_fingerprint": price.fingerprint, "inventory_snapshot": {
                "quantity": format(observation.quantity, "f"), "unit": observation.unit,
                "source": observation.source, "conversion_factor": format(item.conversion_factor, "f"),
                "safety_buffer": format(item.safety_buffer, "f"), "min_qty": item.min_qty,
                "step_qty": item.step_qty}})
    # Recheck all observations at the persistence boundary: later rows may take time.
    now = beijing_now()
    for item in rows:
        validate_observation(observations.get(item.public_id), now=now,
            max_age_seconds=get_settings().PORTAL_INVENTORY_MAX_AGE_SECONDS,
            quantity=requested[item.public_id], inventory_unit=item.inventory_unit,
            conversion_factor=item.conversion_factor, safety_buffer=item.safety_buffer,
            minimum=item.min_qty, step=item.step_qty)
    return lines


def create(db, token, csrf, body):
    require_writes()
    principal, _ = auth.authenticate(db, token, csrf=csrf, write=True)
    principal.require("quote")
    if principal.site.currency != "USD":
        reject("PRICE_UNAVAILABLE", "The settlement currency needs review.", 503)
    try:
        policy = SitePolicy.model_validate(principal.site.policy_json)
    except ValidationError:
        reject("POLICY_UNAVAILABLE", "Ordering terms need review.", 503)
    term = next((value for value in policy.payment_terms if value.code == policy.default_payment_term_code), None)
    if term is None:
        reject("POLICY_UNAVAILABLE", "Ordering terms need review.", 503)
    lines = build_lines(db, principal.access, principal.site, body.items)
    now = beijing_now()
    products, _ = total_amount([line["line_amount"] for line in lines])
    row = Quote(public_id=str(uuid4()), access_id=principal.access.id,
        account_id=principal.account.id, membership_id=principal.membership.id, status="valid",
        # MySQL's existing DATETIME columns have second precision. Hash the same
        # representation that survives storage, not Python-only microseconds.
        expires_at=(now + timedelta(minutes=policy.quote_valid_minutes)).replace(microsecond=0),
        authority_versions_json=authority_snapshot(principal), input_hash=content_hash(body.model_dump(mode="json")),
        currency=principal.site.currency, product_amount=products, fees_status="pending", total_amount=None,
        lines_json=lines, delivery_json=body.delivery.model_dump(mode="json"),
        payment_terms_snapshot=term.model_dump(mode="json"), customer_po=body.customer_po, remark=body.remark)
    row.result_hash = content_hash(evidence(row))
    db.add(row)
    db.add(AuditEvent(actor_type="customer", actor_id=principal.account.id, access_id=principal.access.id,
        object_type="quote", object_public_id=row.public_id, action="quote.created", trace_id=str(uuid4()),
        safe_diff_json={"line_count": len(lines)}, reason=""))
    db.flush()
    return view(row)


def detail(db, token, public_id):
    principal, _ = auth.authenticate(db, token)
    principal.require("quote_detail")
    row = db.scalar(select(Quote).where(Quote.public_id == str(public_id),
        Quote.access_id == principal.access.id, Quote.account_id == principal.account.id,
        Quote.membership_id == principal.membership.id))
    if row is None:
        reject("RESOURCE_NOT_FOUND", "This quote is not available.", 404)
    return view(row)


def revalidate_for_submission(db, principal, row):
    """Recheck a new submission only; successful replay must bypass source reads."""
    from app.portal.domain import require_fresh
    view(row)  # Verify persisted evidence before trusting any of its fields.
    if row.status != "valid":
        reject("QUOTE_UNAVAILABLE", "This quote is no longer available for submission.", 409)
    require_fresh(row.expires_at, beijing_now(), "QUOTE_EXPIRED")
    if row.authority_versions_json != authority_snapshot(principal) or row.currency != principal.site.currency:
        reject("QUOTE_CHANGED", "Your ordering configuration changed. Request a new quote.", 409)
    requested = {line["item_id"]: line for line in row.lines_json}
    items = [item for item in catalog_service.authorized_items(db, principal) if item.public_id in requested]
    if len(items) != len(requested):
        reject("QUOTE_CHANGED", "One or more products are no longer available.", 409)
    aliases = {line["item_id"]: line for line in mapping_service.current_projection(db, principal.access)}
    observations = catalog_service.load_observations(db, items)
    for item in items:
        line = requested[item.public_id]
        if (sku_source.revalidate(db, item) != line["standard_snapshot"]
                or item.row_version != line["catalog_item_version"]
                or aliases[item.public_id] != line["display_snapshot"]):
            reject("QUOTE_CHANGED", "Product details changed. Request a new quote.", 409)
        price = pricing.resolve(db, principal.access, item, row.currency)
        if price.fingerprint != line["price_fingerprint"] or format(price.amount, ".4f") != line["unit_price"]:
            reject("PRICE_CHANGED", "Prices changed. Review a new quote before submitting.", 409)
    now = beijing_now()
    require_fresh(row.expires_at, now, "QUOTE_EXPIRED")
    for item in items:
        validate_observation(observations.get(item.public_id), now=now,
            max_age_seconds=get_settings().PORTAL_INVENTORY_MAX_AGE_SECONDS,
            quantity=requested[item.public_id]["quantity"], inventory_unit=item.inventory_unit,
            conversion_factor=item.conversion_factor, safety_buffer=item.safety_buffer,
            minimum=item.min_qty, step=item.step_qty)
    return {item.public_id: item for item in items}
