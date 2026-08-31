"""Customer-id radar action queries and evidence-bound recommendation refresh."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today, to_beijing_naive
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerOpportunity,
)
from app.customer.logical_customer_service import logical_owner_expression, logical_root_predicate
from app.customer.workflow_service import (
    CustomerWorkflowConflict,
    CustomerWorkflowNotFound,
    complete_action as complete_workflow_action,
    create_action,
)


THREAD_GROUPS: dict[str, dict[str, Any]] = {
    "new_inquiry": {
        "label": "新询盘响应", "priority_label": "优先", "color": "blue", "sort": 10,
        "desc": "需要快速判断和首回",
    },
    "sample": {
        "label": "样单反馈", "priority_label": "优先", "color": "green", "sort": 20,
        "desc": "仅在真实样单证据存在时生成",
    },
    "key_account": {
        "label": "大客户维护",
        "priority_label": "保持",
        "color": "purple",
        "sort": 30,
        "desc": "仅由订单价值或人工确认触发",
    },
    "reorder": {
        "label": "复购窗口",
        "priority_label": "重点",
        "color": "teal",
        "sort": 40,
        "desc": "仅由真实采购周期触发",
    },
    "reactivation": {
        "label": "老客唤醒",
        "priority_label": "重点",
        "color": "red",
        "sort": 50,
        "desc": "由明确的沉睡客户证据触发",
    },
    "public_pool": {
        "label": "公海验证", "priority_label": "顺手", "color": "gray", "sort": 60,
        "desc": "资格审核通过后的首轮人工复核",
    },
}

ACTION_DISMISSAL_REASON_CODES = {
    "user_dismissed",
    "duplicate",
    "no_longer_relevant",
    "wrong_customer",
    "completed_elsewhere",
    "policy_suppressed",
    "other",
}


def _live_customer_ids(db: Session, user_id: int):
    return db.query(CustomerAssignment.customer_id).filter(
        CustomerAssignment.user_id == user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )


def _attach_logical_customer(action: CustomerAction, customer_id: int) -> CustomerAction:
    action.logical_customer_id = int(customer_id)
    return action


def _opportunity_recommendation(opportunity: CustomerOpportunity) -> dict | None:
    if opportunity.status not in {"pending", "contacted", "replied", "quoted"}:
        return None
    if opportunity.opportunity_type == "public_pool":
        return {
            "thread_group": "public_pool",
            "reason": "客户已通过资格审核，需要确认首轮开发策略。",
            "next_action": "复核档案证据并准备首次人工联系。",
            "action_type": "review",
            "channel": "internal",
        }
    if opportunity.opportunity_type == "ali_inquiry":
        return {
            "thread_group": "new_inquiry",
            "reason": "客户有待处理的真实阿里询盘。",
            "next_action": "复核询盘内容并进行人工回复。",
            "action_type": "message",
            "channel": "alibaba",
        }
    if opportunity.opportunity_type == "customer_reactivation":
        return {
            "thread_group": "reactivation",
            "reason": "客户存在经证据确认的唤醒机会。",
            "next_action": "复核历史互动后决定是否人工联系。",
            "action_type": "review",
            "channel": "internal",
        }
    return None


def generate_daily_actions(
    db: Session,
    owner_user_id: int,
    action_date: date | None = None,
) -> list[CustomerAction]:
    target_date = action_date or beijing_today()
    assignments = db.query(CustomerAssignment).filter(
        CustomerAssignment.user_id == owner_user_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).all()
    customer_ids = [assignment.customer_id for assignment in assignments]
    if not customer_ids:
        return []
    accounts = {
        account.id: account
        for account in db.query(CustomerAccount).filter(
            CustomerAccount.id.in_(customer_ids),
            CustomerAccount.record_status == "active",
            CustomerAccount.current_profile_version_id.isnot(None),
        ).all()
    }
    opportunity_owner = logical_owner_expression(CustomerOpportunity, "opportunity")
    opportunities = db.query(CustomerOpportunity, opportunity_owner.label(
        "logical_customer_id",
    )).filter(
        opportunity_owner.in_(accounts),
        CustomerOpportunity.owner_user_id == owner_user_id,
        CustomerOpportunity.status.in_(("pending", "contacted", "replied", "quoted")),
    ).order_by(CustomerOpportunity.created_at.desc()).all()
    seen_customers: set[int] = set()
    for opportunity, logical_customer_id in opportunities:
        logical_customer_id = int(logical_customer_id)
        if logical_customer_id in seen_customers:
            continue
        recommendation = _opportunity_recommendation(opportunity)
        if recommendation is None:
            continue
        account = accounts[logical_customer_id]
        action = create_action(
            db,
            customer_id=account.id,
            owner_user_id=owner_user_id,
            opportunity_id=opportunity.id,
            profile_version_id=account.current_profile_version_id,
            action_type=recommendation["action_type"],
            thread_group=recommendation["thread_group"],
            channel=recommendation["channel"],
            priority="high" if opportunity.priority_level == "A" else "normal",
            reason=recommendation["reason"],
            next_action=recommendation["next_action"],
            suggested_message=opportunity.opening_message_en,
            due_at=opportunity.due_at,
            policy_version="customer_radar_v1",
            source_type="rule",
            source_event_ids=(),
            evidence_fact_ids=tuple(opportunity.evidence_fact_ids or ()),
            action_date=target_date,
        )
        seen_customers.add(logical_customer_id)
    db.commit()
    action_owner = logical_owner_expression(CustomerAction, "action")
    rows = db.query(CustomerAction, action_owner.label("logical_customer_id")).filter(
        CustomerAction.owner_user_id == owner_user_id,
        action_owner.in_(_live_customer_ids(db, owner_user_id)),
        CustomerAction.action_date == target_date,
    ).order_by(
        CustomerAction.due_at.is_(None).asc(),
        CustomerAction.due_at.asc(),
        CustomerAction.id,
    ).all()
    return [_attach_logical_customer(row, owner) for row, owner in rows]


def get_daily_focus(
    db: Session,
    owner_user_id: int,
    action_date: date | None = None,
    thread_group: str | None = None,
) -> dict:
    target_date = action_date or beijing_today()
    action_owner = logical_owner_expression(CustomerAction, "action")
    query = db.query(CustomerAction).filter(
        CustomerAction.owner_user_id == owner_user_id,
        action_owner.in_(_live_customer_ids(db, owner_user_id)),
        CustomerAction.action_date == target_date,
    )
    if query.count() == 0:
        generate_daily_actions(db, owner_user_id, target_date)
    query = db.query(CustomerAction).filter(
        CustomerAction.owner_user_id == owner_user_id,
        action_owner.in_(_live_customer_ids(db, owner_user_id)),
        CustomerAction.action_date == target_date,
    )
    if thread_group:
        query = query.filter(CustomerAction.thread_group == thread_group)
    rows = query.with_entities(CustomerAction, action_owner.label(
        "logical_customer_id",
    )).order_by(
        CustomerAction.due_at.is_(None).asc(),
        CustomerAction.due_at.asc(),
        CustomerAction.created_at,
    ).all()
    grouped: dict[str, list[CustomerAction]] = {}
    rows = [_attach_logical_customer(row, owner) for row, owner in rows]
    for row in rows:
        grouped.setdefault(row.thread_group, []).append(row)
    threads = []
    for group in sorted(THREAD_GROUPS, key=lambda key: THREAD_GROUPS[key]["sort"]):
        group_rows = grouped.get(group, [])
        if not group_rows:
            continue
        info = THREAD_GROUPS[group]
        threads.append({
            "group": group,
            "label": info["label"],
            "priority_label": info["priority_label"],
            "color": info["color"],
            "desc": info["desc"],
            "count": len(group_rows),
            "actions": [_serialize_action(row) for row in group_rows],
        })
    return {
        "action_date": str(target_date),
        "threads": threads,
        "summary": {
            "total": len(rows),
            **{
                status: sum(row.status == status for row in rows)
                for status in ("pending", "done", "dismissed", "snoozed")
            },
        },
    }


def get_thread_counts(
    db: Session,
    owner_user_id: int,
    action_date: date | None = None,
) -> dict:
    target_date = action_date or beijing_today()
    action_owner = logical_owner_expression(CustomerAction, "action")
    if db.query(CustomerAction.id).filter(
        CustomerAction.owner_user_id == owner_user_id,
        action_owner.in_(_live_customer_ids(db, owner_user_id)),
        CustomerAction.action_date == target_date,
    ).first() is None:
        generate_daily_actions(db, owner_user_id, target_date)
    rows = db.query(CustomerAction.thread_group, func.count(CustomerAction.id)).filter(
        CustomerAction.owner_user_id == owner_user_id,
        action_owner.in_(_live_customer_ids(db, owner_user_id)),
        CustomerAction.action_date == target_date,
    ).group_by(CustomerAction.thread_group).all()
    counts = {group: 0 for group in THREAD_GROUPS}
    counts.update({group: count for group, count in rows})
    return counts


def complete_action(
    db: Session,
    action_id: int,
    user_id: int,
    feedback: str | None = None,
    note: str | None = None,
    *,
    outcome_code: str = "other",
    channel: str | None = None,
    occurred_at: datetime | None = None,
    summary: str | None = None,
    next_step: str | None = None,
    can_manage: bool = False,
) -> CustomerAction:
    action = db.get(CustomerAction, action_id)
    if action is None:
        raise CustomerWorkflowNotFound("ACTION_NOT_FOUND")
    logical_customer_id = db.query(
        logical_owner_expression(CustomerAction, "action"),
    ).filter(CustomerAction.id == action_id).scalar()
    row = complete_workflow_action(
        db,
        action_id=action_id,
        completed_by=user_id,
        occurred_at=occurred_at or beijing_now(),
        channel=channel or action.channel or "internal",
        outcome_code=outcome_code,
        summary=(summary or note or "行动已由业务员完成").strip(),
        next_step=(next_step if next_step is not None else action.next_action),
        can_manage=can_manage,
    )
    if feedback:
        row.feedback_json = {
            **dict(row.feedback_json or {}),
            "user_feedback": feedback.strip(),
        }
    db.commit()
    db.refresh(row)
    return _attach_logical_customer(row, logical_customer_id)


def _action_and_account_for_update(
    db: Session,
    action_id: int,
) -> tuple[CustomerAction, CustomerAccount]:
    candidate = db.get(CustomerAction, action_id)
    if candidate is None:
        raise CustomerWorkflowNotFound("ACTION_NOT_FOUND")
    owner_id = db.query(logical_owner_expression(CustomerAction, "action")).filter(
        CustomerAction.id == action_id,
    ).scalar()
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == owner_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise CustomerWorkflowNotFound("CUSTOMER_NOT_FOUND")
    action = db.query(CustomerAction).filter(
        CustomerAction.id == action_id,
        logical_root_predicate(CustomerAction, "action", account.id),
    ).with_for_update().one_or_none()
    if action is None:
        raise CustomerWorkflowNotFound("ACTION_NOT_FOUND")
    return _attach_logical_customer(action, account.id), account


def _mark_action_changed(account: CustomerAccount, *, changed_at: datetime) -> None:
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = changed_at


def _require_action_actor_scope(
    db: Session,
    action: CustomerAction,
    user_id: int,
    *,
    can_manage: bool = False,
) -> None:
    if can_manage:
        return
    assignment = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == action.logical_customer_id,
        CustomerAssignment.user_id == user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first()
    if assignment is None:
        raise CustomerWorkflowConflict("ACTION_ACTOR_FORBIDDEN")
    if action.opportunity_id is not None:
        opportunity = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.id == action.opportunity_id,
            logical_root_predicate(
                CustomerOpportunity, "opportunity", action.logical_customer_id,
            ),
        ).one_or_none()
        if opportunity is None or opportunity.owner_user_id != user_id:
            raise CustomerWorkflowConflict("ACTION_ACTOR_FORBIDDEN")


def dismiss_action(
    db: Session,
    action_id: int,
    user_id: int,
    *,
    reason_code: str = "user_dismissed",
    note: str | None = None,
    can_manage: bool = False,
) -> CustomerAction:
    if reason_code not in ACTION_DISMISSAL_REASON_CODES:
        raise CustomerWorkflowConflict("ACTION_DISMISSAL_INVALID")
    normalized_note = note.strip() if note is not None else None
    if normalized_note is not None and len(normalized_note) > 1000:
        raise CustomerWorkflowConflict("ACTION_DISMISSAL_INVALID")
    action, account = _action_and_account_for_update(db, action_id)
    if not can_manage and action.owner_user_id != user_id:
        raise CustomerWorkflowConflict("ACTION_OWNER_REQUIRED")
    _require_action_actor_scope(db, action, user_id, can_manage=can_manage)
    if action.status != "pending":
        raise CustomerWorkflowConflict("ACTION_NOT_PENDING")
    action.status = "dismissed"
    action.dismissal_reason = reason_code
    action.feedback_json = {
        **dict(action.feedback_json or {}),
        "user_note": normalized_note,
    }
    now = beijing_now()
    action.updated_at = now
    _mark_action_changed(account, changed_at=now)
    db.commit()
    db.refresh(action)
    return action


def snooze_action(
    db: Session,
    action_id: int,
    user_id: int,
    until: datetime,
    *,
    can_manage: bool = False,
) -> CustomerAction:
    action, account = _action_and_account_for_update(db, action_id)
    if not can_manage and action.owner_user_id != user_id:
        raise CustomerWorkflowConflict("ACTION_OWNER_REQUIRED")
    _require_action_actor_scope(db, action, user_id, can_manage=can_manage)
    if action.status != "pending":
        raise CustomerWorkflowConflict("ACTION_NOT_PENDING")
    normalized_until = to_beijing_naive(until)
    if normalized_until <= beijing_now():
        raise CustomerWorkflowConflict("SNOOZE_TIME_INVALID")
    action.status = "snoozed"
    action.snoozed_until = normalized_until
    now = beijing_now()
    action.updated_at = now
    _mark_action_changed(account, changed_at=now)
    db.commit()
    db.refresh(action)
    return action


def submit_feedback(
    db: Session,
    action_id: int,
    feedback: str,
    note: str | None,
    user_id: int,
    *,
    can_manage: bool = False,
) -> CustomerAction:
    action, account = _action_and_account_for_update(db, action_id)
    if not can_manage and action.owner_user_id != user_id:
        raise CustomerWorkflowConflict("ACTION_OWNER_REQUIRED")
    _require_action_actor_scope(db, action, user_id, can_manage=can_manage)
    action.feedback_json = {
        **dict(action.feedback_json or {}),
        "user_feedback": feedback,
        "user_note": note,
        "submitted_by": user_id,
        "submitted_at": beijing_now().isoformat(),
    }
    now = beijing_now()
    action.updated_at = now
    _mark_action_changed(account, changed_at=now)
    db.commit()
    db.refresh(action)
    return action


def _serialize_action(action: CustomerAction) -> dict:
    return {
        "id": action.id,
        "customer_id": getattr(action, "logical_customer_id", action.customer_id),
        "opportunity_id": action.opportunity_id,
        "owner_user_id": action.owner_user_id,
        "thread_group": action.thread_group,
        "priority": action.priority,
        "reason": action.reason,
        "next_action": action.next_action,
        "suggested_message": action.suggested_message,
        "status": action.status,
        "action_status": action.status,
        "action_date": str(action.action_date),
        "feedback_json": action.feedback_json or {},
        "evidence_fact_ids": action.evidence_fact_ids or [],
        "profile_version_id": action.profile_version_id,
        "snoozed_until": (
            action.snoozed_until.isoformat() if action.snoozed_until else None
        ),
    }


__all__ = [
    "THREAD_GROUPS",
    "complete_action",
    "dismiss_action",
    "generate_daily_actions",
    "get_daily_focus",
    "get_thread_counts",
    "snooze_action",
    "submit_feedback",
]
