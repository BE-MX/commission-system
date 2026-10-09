"""Atomic customer submission and account-scoped recovery, without invoice creation."""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.time import beijing_now
from app.portal import auth_service as auth, quote_service, revision_evidence
from app.portal.domain import content_hash
from app.portal.errors import reject
from app.portal.models import AuditEvent, OrderRequest, OutboxEvent, Quote, RequestLine, Revision


def find_by_key(db, principal, key):
    return db.scalar(select(OrderRequest).where(OrderRequest.access_id == principal.access.id,
        OrderRequest.account_id == principal.account.id, OrderRequest.idempotency_key == str(key))
        .execution_options(populate_existing=True))


def receipt(db, row, principal, *, replayed):
    result = {"request_id": row.public_id, "request_no": row.public_no, "status": row.status,
              "row_version": row.row_version, "replayed": replayed,
              "submitted_at": row.submitted_at.isoformat()}
    if principal.access.can_view_price:
        original = db.scalar(select(Revision).where(Revision.request_id == row.id, Revision.revision_no == 1))
        if original is None:
            reject("ORDER_UNAVAILABLE", "This order request needs review.", 409)
        lines = db.scalars(select(RequestLine).where(RequestLine.revision_id == original.id)).all()
        revision_evidence.verify(original, lines)
        result.update(currency=original.currency, product_amount=format(original.product_amount, ".2f"),
                      total_amount=None if original.total_amount is None else format(original.total_amount, ".2f"))
    return result


def replay(db, principal, key, payload_hash):
    existing = find_by_key(db, principal, key)
    if existing is None:
        return None
    if existing.client_payload_hash != payload_hash:
        reject("IDEMPOTENCY_CONFLICT", "This submission key was already used for different content.", 409)
    return receipt(db, existing, principal, replayed=True)


def submit(db, token, csrf, key, body):
    auth.require_enabled()
    principal, _ = auth.authenticate(db, token, csrf=csrf, write=True)
    payload_hash = content_hash(body.model_dump(mode="json"))
    # A committed result remains recoverable after can_order or write switch changes.
    # Current login and amount visibility are still enforced before any disclosure.
    previous = replay(db, principal, key, payload_hash)
    if previous is not None:
        return previous
    quote_service.require_writes()
    principal.require("submit")
    quote = db.scalar(select(Quote).where(Quote.public_id == str(body.quote_id),
        Quote.account_id == principal.account.id, Quote.access_id == principal.access.id,
        Quote.membership_id == principal.membership.id).with_for_update()
        .execution_options(populate_existing=True))
    if quote is None:
        reject("RESOURCE_NOT_FOUND", "This quote is not available.", 404)
    if quote.result_hash != body.quote_content_hash or quote.customer_po != body.customer_po or quote.remark != body.remark:
        reject("QUOTE_CHANGED", "Order details changed. Request a new quote before submitting.", 409)
    items = quote_service.revalidate_for_submission(db, principal, quote)
    now = beijing_now().replace(microsecond=0)
    public_id = str(uuid4())
    order = OrderRequest(public_id=public_id, access_id=principal.access.id, account_id=principal.account.id,
        customer_id_snapshot=principal.access.customer_id, okki_company_id_snapshot=principal.access.okki_company_id,
        sales_user_id_snapshot=principal.access.sales_user_id, servicing_user_id=principal.access.sales_user_id,
        public_no="POR-" + now.strftime("%Y%m%d") + "-" + public_id.replace("-", "").upper(),
        idempotency_key=str(key), client_payload_hash=payload_hash, quote_id=quote.id,
        status="submitted", customer_po=quote.customer_po, submitted_at=now)
    db.add(order)
    db.flush()
    revision = Revision(public_id=str(uuid4()), request_id=order.id, revision_no=1, kind="submitted", currency=quote.currency,
        product_amount=quote.product_amount, fees_status="pending", total_amount=None,
        shipping_amount=None, packaging_amount=None, surcharge_amount=None, surcharge_name="",
        delivery_json=deepcopy(quote.delivery_json), payment_terms_snapshot=deepcopy(quote.payment_terms_snapshot),
        expires_at=quote.expires_at, authority_versions_json=deepcopy(quote.authority_versions_json),
        remark=quote.remark, mapping_version=principal.access.mapping_version,
        pricing_fingerprint=content_hash({line["item_id"]: line["price_fingerprint"] for line in quote.lines_json}),
        bound_invoice_document_version=None, created_by=None)
    request_lines = []
    for line in quote.lines_json:
        item = items[line["item_id"]]
        standard = line["standard_snapshot"]
        inventory = line["inventory_snapshot"]
        request_lines.append(RequestLine(line_key=line["line_key"], catalog_item_id=item.id,
            product_kind=standard["product_kind"], product_id=standard["product_id"], sku_id=standard["sku_id"],
            standard_json=deepcopy(standard["standard_json"]), customer_display_json=deepcopy(line["display_snapshot"]),
            mapping_version=principal.access.mapping_version, qty=line["quantity"],
            unit_price=Decimal(line["unit_price"]), discount_amount=Decimal(line["discount_amount"]),
            line_amount=Decimal(line["line_amount"]),
            unit_weight_grams=Decimal(inventory["conversion_factor"]) if inventory["unit"] == "g" else None,
            price_source="ark_customer_rule", price_fingerprint=line["price_fingerprint"]))
    revision.content_hash = revision_evidence.digest(revision, request_lines)
    db.add(revision)
    db.flush()
    for line in request_lines:
        line.revision_id = revision.id
        db.add(line)
    order.active_revision_id = revision.id
    quote.status = "consumed"
    db.add(AuditEvent(actor_type="customer", actor_id=principal.account.id, access_id=principal.access.id,
        object_type="order_request", object_public_id=public_id, action="order.submitted", trace_id=str(uuid4()),
        safe_diff_json={"line_count": len(quote.lines_json)}, reason=""))
    # Event is a reference only. Delivery resolves current authority/recipient later.
    db.add(OutboxEvent(event_key="order.submitted:"+public_id, event_type="order_submitted",
        aggregate_public_id=public_id, payload_json={"request_id": public_id}, next_attempt_at=now))
    db.flush()
    return receipt(db, order, principal, replayed=False)


def by_key(db, token, key):
    principal, _ = auth.authenticate(db, token)
    principal.require("order_status")
    order = find_by_key(db, principal, key)
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    return receipt(db, order, principal, replayed=True)


def recover_unique_race(db, token, csrf, key, body):
    """Only return an actually committed winner after the caller rolled back."""
    principal, _ = auth.authenticate(db, token, csrf=csrf, write=True)
    return replay(db, principal, key, content_hash(body.model_dump(mode="json")))
