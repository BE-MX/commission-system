"""Customer acceptance/rejection of a bound revision; no PI or inventory reservation."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

from app.core.time import beijing_now
from app.portal import auth_service as auth, order_commands, proposal_service, quote_service, revision_evidence
from app.portal.domain import content_hash, request_transition, require_fresh, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CatalogItem, CommandReceipt, OrderRequest, OutboxEvent, RequestLine, Revision
from app.portal.schemas import QuoteLine


def revalidate(db, principal, revision, records):
    require_fresh(revision.expires_at, beijing_now())
    if revision.authority_versions_json != proposal_service.company_versions(principal.access, principal.site):
        reject("PROPOSAL_CHANGED", "Ordering terms changed. Request a new proposal.", 409)
    items = {row.id: row for row in db.scalars(select(CatalogItem).where(
        CatalogItem.id.in_([record.catalog_item_id for record in records]))).all()}
    if len(items) != len(records):
        reject("PROPOSAL_CHANGED", "The product selection needs review.", 409)
    requested = [QuoteLine(item_id=items[row.catalog_item_id].public_id, quantity=row.qty) for row in records]
    fresh = {line["item_id"]: line for line in quote_service.build_lines(db, principal.access, principal.site, requested)}
    for row in records:
        line = fresh[items[row.catalog_item_id].public_id]
        standard = line["standard_snapshot"]
        if (row.price_fingerprint != line["price_fingerprint"] or revision.currency != principal.site.currency
                or row.standard_json != standard["standard_json"] or row.product_id != standard["product_id"]
                or row.sku_id != standard["sku_id"] or row.product_kind != standard["product_kind"]
                or row.customer_display_json != line["display_snapshot"]
                or revision_evidence.fixed(row.unit_price, 4) != line["unit_price"]
                or revision_evidence.fixed(row.line_amount) != line["line_amount"]):
            reject("PROPOSAL_CHANGED", "Product details or prices changed. Request a new proposal.", 409)
    require_fresh(revision.expires_at, beijing_now())


def decide(db, token, csrf, request_id, revision_id, expected, body, *, accept):
    principal, _ = auth.authenticate(db, token, csrf=csrf, write=True)
    principal.require("accept" if accept else "reject")
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == str(request_id),
        OrderRequest.access_id == principal.access.id).with_for_update().execution_options(populate_existing=True))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    revision = db.scalar(select(Revision).where(Revision.public_id == str(revision_id), Revision.request_id == order.id)
        .with_for_update().execution_options(populate_existing=True))
    if revision is not None and revision.kind == "pi_amendment":
        from app.portal import pi_amendment_service
        return pi_amendment_service.decide(db, token, csrf, request_id, revision_id, expected, body, accept=accept)
    if revision is None or revision.kind != "proposal":
        reject("RESOURCE_NOT_FOUND", "This proposal is not available.", 404)
    action = "accept" if accept else "reject_proposal"
    key = revision.public_id + (":" + body.proposal_hash if accept else "")
    payload_hash = content_hash(body.model_dump(mode="json"))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action == action,
        CommandReceipt.object_public_id == order.public_id, CommandReceipt.command_key == key))
    if saved is not None:
        if saved.payload_hash != payload_hash:
            reject("IDEMPOTENCY_CONFLICT", "This decision was already recorded with different content.", 409)
        return {"replayed": True, "original_receipt": deepcopy(saved.result_reference_json),
                "current_state": order.status, "row_version": order.row_version}
    quote_service.require_writes()
    require_version(order.row_version, expected)
    if order_commands.has_invoice_lineage(db, order):
        reject("INVOICE_ALREADY_CREATED", "This request already has an invoice.", 409)
    if order.active_revision_id != revision.id or order.status != "awaiting_customer":
        reject("PROPOSAL_SUPERSEDED", "Review the current proposal before continuing.", 409)
    records = db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id)).all()
    revision_evidence.verify(revision, records)
    if accept:
        if body.proposal_hash != revision.content_hash:
            reject("PROPOSAL_CHANGED", "Review the current proposal before accepting.", 409)
        if revision.fees_status != "confirmed" or revision.total_amount is None:
            reject("CUSTOMER_ACCEPTANCE_REQUIRED", "The complete order terms need review.", 409)
        revalidate(db, principal, revision, records)
    before = order.row_version
    now = beijing_now().replace(microsecond=0)
    order.status = request_transition(order.status, "accept" if accept else "reject_proposal")
    order.accepted_revision_id = revision.id if accept else None
    order.row_version += 1
    if accept:
        revision.customer_accepted_by = principal.account.id
        revision.customer_accepted_at = now
    result = {"request_id": order.public_id, "revision_id": revision.public_id,
              "content_hash": revision.content_hash, "status": order.status,
              "row_version": order.row_version, "completed_at": now.isoformat()}
    db.add(CommandReceipt(action=action, object_public_id=order.public_id, command_key=key,
        payload_hash=payload_hash, result_reference_json=result, first_actor_type="customer",
        first_actor_id=principal.account.id, completed_at=now))
    event = "order.accepted" if accept else "order.proposal_rejected"
    db.add(AuditEvent(actor_type="customer", actor_id=principal.account.id, access_id=principal.access.id,
        object_type="order_request", object_public_id=order.public_id, action=event,
        before_version=before, after_version=order.row_version, reason="" if accept else body.reason,
        trace_id=str(uuid4()), safe_diff_json={"revision_id": revision.public_id}))
    db.add(OutboxEvent(event_key=event+":"+revision.public_id, event_type=event.replace(".", "_"),
        aggregate_public_id=order.public_id, payload_json={"request_id": order.public_id,
        "revision_id": revision.public_id}, next_attempt_at=now))
    db.flush()
    return {"replayed": False, "original_receipt": result, "current_state": order.status, "row_version": order.row_version}
