"""Customer order commands with persistent replay receipts and shared lock order."""
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select

from app.core.time import beijing_now
from app.portal import auth_service as auth, quote_service
from app.portal.domain import content_hash, request_transition, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, Conversion, OrderRequest, OutboxEvent


def has_invoice_lineage(db, order):
    return order.invoice_id is not None or db.scalar(select(Conversion.id).where(Conversion.request_id == order.id)) is not None


def cancel(db, token, csrf, public_id, expected, body):
    principal, _ = auth.authenticate(db, token, csrf=csrf, write=True)
    principal.require("cancel")
    order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == str(public_id),
        OrderRequest.access_id == principal.access.id).with_for_update()
        .execution_options(populate_existing=True))
    if order is None:
        reject("RESOURCE_NOT_FOUND", "This order request is not available.", 404)
    payload_hash = content_hash(body.model_dump(mode="json"))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action == "cancel",
        CommandReceipt.object_public_id == order.public_id, CommandReceipt.command_key == "cancel"))
    if saved is not None:
        if saved.payload_hash != payload_hash:
            reject("IDEMPOTENCY_CONFLICT", "This request was cancelled with different content.", 409)
        return {"replayed": True, "original_receipt": deepcopy(saved.result_reference_json),
                "current_state": order.status, "row_version": order.row_version}
    quote_service.require_writes()
    require_version(order.row_version, expected)
    if has_invoice_lineage(db, order):
        reject("INVOICE_ALREADY_CREATED", "This request already has an invoice. Contact your representative.", 409)
    state = request_transition(order.status, "cancel")
    before = order.row_version
    order.status = state
    order.accepted_revision_id = None
    order.row_version += 1
    now = beijing_now().replace(microsecond=0)
    result = {"request_id": order.public_id, "status": state, "row_version": order.row_version,
              "completed_at": now.isoformat()}
    db.add(CommandReceipt(action="cancel", object_public_id=order.public_id, command_key="cancel",
        payload_hash=payload_hash, result_reference_json=result, first_actor_type="customer",
        first_actor_id=principal.account.id, completed_at=now))
    db.add(AuditEvent(actor_type="customer", actor_id=principal.account.id, access_id=principal.access.id,
        object_type="order_request", object_public_id=order.public_id, action="order.cancelled",
        before_version=before, after_version=order.row_version, reason=body.reason,
        trace_id=str(uuid4()), safe_diff_json={"status": state}))
    db.add(OutboxEvent(event_key="order.cancelled:"+order.public_id, event_type="order_cancelled",
        aggregate_public_id=order.public_id, payload_json={"request_id": order.public_id}, next_attempt_at=now))
    db.flush()
    return {"replayed": False, "original_receipt": result, "current_state": state, "row_version": order.row_version}
