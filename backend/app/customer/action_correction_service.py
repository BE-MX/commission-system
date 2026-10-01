"""Append corrections and safe compensation without deleting execution facts."""

from app.customer import pcw_errors
from app.customer.models import CustomerAction
from app.customer.pcw_workitem_service import _require_version, _lock_action_for_actor, create_pcw_action
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.work_item_service import item_access, record_event
from app.customer.work_item_evidence_service import validate_evidence
from app.core.time import beijing_now


def correct_action(db, user, action_id, payload, idempotency_key):
    candidate = db.get(CustomerAction, action_id)
    if candidate is None or candidate.work_item_id is None:
        raise pcw_errors.not_found("事项行动不存在", error_code="ACTION_NOT_FOUND")
    item, access = item_access(db, user, candidate.work_item_id, write=True, lock=True)
    action, _ = _lock_action_for_actor(db, action_id=action_id, actor_user_id=access.actor_user_id, can_manage=access.can_manage)
    def execute():
        _require_version(action.row_version, payload["expected_action_version"], "ACTION_VERSION_CONFLICT", "current_action_version")
        _require_version(item.row_version, payload["expected_work_item_version"], "WORK_ITEM_VERSION_CONFLICT", "current_item_version")
        refs = validate_evidence(db, access, payload["evidence_refs"]) if payload.get("evidence_refs") else []
        operation = payload.get("operation", "correct")
        followup_id = None
        original_status = action.status
        if operation == "undo":
            dependents = db.query(CustomerAction.id).filter(CustomerAction.parent_action_id == action.id,
                CustomerAction.status.in_(("done", "pending", "snoozed"))).first()
            if (action.feedback_json or {}).get("completion", {}).get("evidence_message_ids") or dependents or item.state in {"resolved", "cancelled", "paused"} or action.status not in {"dismissed", "snoozed"}:
                raise pcw_errors.conflict("已有执行事实或依赖，保留登记并追加纠正", error_code="CORRECTION_ONLY")
            followup = create_pcw_action(db, work_item=item, action_type="review", thread_group=action.thread_group,
                priority=action.priority, reason=payload["reason"], next_action=payload["correction"],
                channel="internal", business_due_at=beijing_now(), owner_user_id=action.owner_user_id,
                parent_action=action)
            followup_id = followup.id
            if action.status == "snoozed":
                action.status = "cancelled"
                action.dismissal_reason = "undo_replaced"
                action.row_version += 1
                action.updated_at = beijing_now()
        event = record_event(db, item, actor=access.actor_user_id, operation="action_"+operation,
            previous=item.state, reason=payload["reason"], evidence=refs,
            payload={"action_id": action.id, "original_status": original_status, "original_summary": (action.feedback_json or {}).get("completion", {}).get("summary"),
                "correction": payload["correction"], "followup_action_id": followup_id})
        return {"event_id": event.id, "action_id": action.id, "row_version": action.row_version,
            "work_item_version": item.row_version, "followup_action_id": followup_id, "history_preserved": True}
    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id, operation_scope=f"action_correction:{action_id}",
        idempotency_key=idempotency_key, request_payload=payload, execute=execute)
    return result
