"""Employee rejection of unconverted requests; retains evidence and command receipts."""
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import select
from app.core.time import beijing_now
from app.portal import order_commands, proposal_service, quote_service
from app.portal.domain import content_hash, request_transition, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CommandReceipt, OutboxEvent


def reject_request(db, actor_id, public_id, expected, body):
    actor,_,access,order = proposal_service.managed_request(db,actor_id,public_id)
    key = "reject:"+str(expected)
    digest = content_hash(body.model_dump(mode="json"))
    saved = db.scalar(select(CommandReceipt).where(CommandReceipt.action=="reject",
        CommandReceipt.object_public_id==order.public_id,CommandReceipt.command_key==key))
    if saved is not None:
        if saved.payload_hash != digest:
            reject("IDEMPOTENCY_CONFLICT","该拒绝命令已使用其他内容完成。",409)
        return {"replayed":True,"original_receipt":deepcopy(saved.result_reference_json),
            "current_state":order.status,"row_version":order.row_version}
    quote_service.require_writes()
    require_version(order.row_version,expected)
    if order_commands.has_invoice_lineage(db,order):
        reject("INVOICE_ALREADY_CREATED","已建票请求请使用发票取消流程。",409)
    state = request_transition(order.status,"reject")
    before = order.row_version
    order.status = state
    order.accepted_revision_id = None
    order.row_version += 1
    now = beijing_now()
    result = {"request_id":order.public_id,"status":state,"row_version":order.row_version,"completed_at":now.isoformat()}
    db.add(CommandReceipt(action="reject",object_public_id=order.public_id,command_key=key,payload_hash=digest,
        result_reference_json=result,first_actor_type="employee",first_actor_id=actor["id"],completed_at=now))
    db.add(AuditEvent(actor_type="employee",actor_id=actor["id"],access_id=access.id,
        object_type="order_request",object_public_id=order.public_id,action="order.rejected",
        before_version=before,after_version=order.row_version,reason=body.reason,trace_id=str(uuid4()),safe_diff_json={"status":state}))
    db.add(OutboxEvent(event_key="order.rejected:"+order.public_id,event_type="order_rejected",
        aggregate_public_id=order.public_id,payload_json={"request_id":order.public_id},next_attempt_at=now))
    db.flush()
    return {"replayed":False,"original_receipt":result,"current_state":state,"row_version":order.row_version}
