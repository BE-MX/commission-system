"""Create a dated manual follow-up inside the original action's locked transaction."""

from datetime import datetime

from app.core.time import beijing_now, to_beijing_naive
from app.customer.models import CustomerAccount


def followup_request(*, next_step, due_at, action_type, channel):
    if due_at is None:
        return None
    return {"next_step": next_step.strip(), "due_at": to_beijing_naive(due_at).isoformat(),
            "action_type": action_type, "channel": channel}


def validate_followup(request):
    from app.customer.workflow_service import CustomerWorkflowError

    if request is None:
        return
    if not request["next_step"]:
        raise CustomerWorkflowError("FOLLOWUP_DESCRIPTION_REQUIRED")
    if datetime.fromisoformat(request["due_at"]) <= beijing_now():
        raise CustomerWorkflowError("FOLLOWUP_TIME_MUST_BE_FUTURE")
    if request["action_type"] not in {"call", "email", "message", "meeting", "research", "review"}:
        raise CustomerWorkflowError("FOLLOWUP_TYPE_INVALID")
    if request["channel"] not in {"alibaba", "email", "whatsapp", "phone", "linkedin", "offline", "internal"}:
        raise CustomerWorkflowError("FOLLOWUP_CHANNEL_INVALID")


def create_followup(db, original, activity, customer_id, request):
    from app.customer.workflow_service import CustomerWorkflowConflict, create_action

    # The account lock is already held. Read its current pointer directly so a
    # previously cached ORM account cannot attach the follow-up to an old profile.
    profile_version_id = db.query(CustomerAccount.current_profile_version_id).filter(
        CustomerAccount.id == customer_id,
    ).with_for_update().scalar()
    if profile_version_id is None:
        raise CustomerWorkflowConflict("PROFILE_NOT_READY")
    deadline = datetime.fromisoformat(request["due_at"])
    return create_action(
        db, customer_id=customer_id, owner_user_id=original.owner_user_id,
        profile_version_id=profile_version_id,
        action_type=request["action_type"], channel=request["channel"],
        thread_group=original.thread_group, priority=original.priority,
        reason="业务员登记跟进结果后安排的后续行动。", next_action=request["next_step"],
        policy_version="human_followup_v1", source_type="manual",
        source_event_ids=[activity.id], evidence_fact_ids=original.evidence_fact_ids or [],
        action_date=deadline.date(), planned_at=deadline, due_at=deadline,
        opportunity_id=original.opportunity_id,
        feedback_json={"parent_action_id": original.id},
    )
