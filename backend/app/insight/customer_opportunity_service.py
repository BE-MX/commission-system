"""Customer-id opportunity queries and mutations for the legacy insight surface."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerOpportunity,
)
from app.customer.workflow_service import (
    CustomerWorkflowConflict,
    CustomerWorkflowNotFound,
    append_opportunity_event,
    transition_opportunity,
)


def _live_customer_ids(db: Session, user_id: int):
    return db.query(CustomerAssignment.customer_id).filter(
        CustomerAssignment.user_id == user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )


def get_opportunity(db: Session, opp_id: int) -> CustomerOpportunity | None:
    return db.get(CustomerOpportunity, opp_id)


def _filtered_query(
    db: Session,
    *,
    owner_user_id: int | None = None,
    status: str | None = None,
    priority_level: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    live_scope_user_id: int | None = None,
):
    query = db.query(CustomerOpportunity)
    if owner_user_id is not None:
        query = query.filter(CustomerOpportunity.owner_user_id == owner_user_id)
    if live_scope_user_id is not None:
        query = query.filter(
            CustomerOpportunity.customer_id.in_(
                _live_customer_ids(db, live_scope_user_id)
            )
        )
    if status:
        query = query.filter(CustomerOpportunity.status == status)
    if priority_level:
        query = query.filter(CustomerOpportunity.priority_level == priority_level)
    if source:
        query = query.filter(CustomerOpportunity.source == source)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.join(
            CustomerAccount,
            CustomerAccount.id == CustomerOpportunity.customer_id,
        ).filter(or_(
            CustomerAccount.display_name.ilike(pattern),
            CustomerAccount.canonical_company_name.ilike(pattern),
            CustomerOpportunity.title.ilike(pattern),
            CustomerOpportunity.summary.ilike(pattern),
        ))
    if date_from:
        query = query.filter(CustomerOpportunity.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(CustomerOpportunity.created_at <= datetime.fromisoformat(date_to))
    return query


def _order_query(query):
    return query.order_by(
        CustomerOpportunity.due_at.is_(None).asc(),
        CustomerOpportunity.due_at.asc(),
        CustomerOpportunity.created_at.desc(),
    )


def _page(query, page: int, page_size: int) -> dict:
    total = query.count()
    items = (
        _order_query(query)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_my_opportunities(
    db: Session,
    user_id: int,
    status: str | None = None,
    priority_level: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    return _page(
        _filtered_query(
            db,
            owner_user_id=user_id,
            live_scope_user_id=user_id,
            status=status,
            priority_level=priority_level,
            source=source,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
        ),
        page,
        page_size,
    )


def list_all_opportunities(
    db: Session,
    status: str | None = None,
    priority_level: str | None = None,
    owner_user_id: int | None = None,
    resolve_status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = _filtered_query(
        db,
        owner_user_id=owner_user_id,
        status=status,
        priority_level=priority_level,
        keyword=keyword,
    )
    if resolve_status in {"unassigned", "conflict", "inactive_user"}:
        query = query.filter(CustomerOpportunity.owner_user_id.is_(None))
    return _page(query, page, page_size)


def list_unassigned_opportunities(
    db: Session,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    return _page(
        db.query(CustomerOpportunity).filter(CustomerOpportunity.owner_user_id.is_(None)),
        page,
        page_size,
    )


def get_opportunity_stats(db: Session, user_id: int) -> dict:
    now = beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    base = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.owner_user_id == user_id,
        CustomerOpportunity.customer_id.in_(_live_customer_ids(db, user_id)),
    )
    status_counts = {
        status: base.filter(CustomerOpportunity.status == status).count()
        for status in ("pending", "contacted", "replied", "quoted", "won", "lost")
    }
    return {
        "total": base.count(),
        **status_counts,
        "a_count": base.filter(CustomerOpportunity.priority_level == "A").count(),
        "overdue": base.filter(
            CustomerOpportunity.status == "pending",
            CustomerOpportunity.due_at.isnot(None),
            CustomerOpportunity.due_at < now,
        ).count(),
        "today_contacted": base.filter(
            CustomerOpportunity.status.in_(("contacted", "replied", "quoted")),
            CustomerOpportunity.handled_at >= today_start,
        ).count(),
    }


def update_opportunity_status(
    db: Session,
    opp_id: int,
    new_status: str,
    note: str | None,
    user_id: int,
    *,
    evidence_event_ids: tuple[int, ...] = (),
    evidence_fact_ids: tuple[int, ...] = (),
    linked_order_id: int | None = None,
    close_reason_code: str | None = None,
    close_reason_text: str | None = None,
    can_manage: bool = False,
) -> CustomerOpportunity:
    opportunity = transition_opportunity(
        db,
        opportunity_id=opp_id,
        new_status=new_status,
        actor_user_id=user_id,
        reason=(note or "manual_stage_change").strip(),
        close_reason_code=close_reason_code,
        close_reason_text=close_reason_text,
        evidence_event_ids=evidence_event_ids,
        evidence_fact_ids=evidence_fact_ids,
        linked_order_id=linked_order_id,
        can_manage=can_manage,
    )
    if opportunity.handled_at is None:
        opportunity.handled_at = beijing_now()
    db.commit()
    db.refresh(opportunity)
    return opportunity


def assign_opportunity(
    db: Session,
    opp_id: int,
    user_id: int,
    admin_user_id: int,
) -> CustomerOpportunity:
    candidate = db.get(CustomerOpportunity, opp_id)
    if candidate is None:
        raise CustomerWorkflowNotFound("OPPORTUNITY_NOT_FOUND")
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == candidate.customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise CustomerWorkflowNotFound("CUSTOMER_NOT_FOUND")
    opportunity = (
        db.query(CustomerOpportunity)
        .filter(
            CustomerOpportunity.id == opp_id,
            CustomerOpportunity.customer_id == account.id,
        )
        .with_for_update()
        .one_or_none()
    )
    if opportunity is None:
        raise CustomerWorkflowNotFound("OPPORTUNITY_NOT_FOUND")
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
    ).one_or_none()
    if user is None:
        raise CustomerWorkflowConflict("USER_NOT_ACTIVE")
    assignee_scope = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == opportunity.customer_id,
        CustomerAssignment.user_id == user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first()
    if assignee_scope is None:
        raise CustomerWorkflowConflict("OPPORTUNITY_ASSIGNEE_SCOPE_REQUIRED")
    primary = db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id == opportunity.customer_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).one_or_none()
    if primary is not None and primary.user_id != user_id:
        raise CustomerWorkflowConflict("OPPORTUNITY_PRIMARY_OWNER_CONFLICT")
    previous_owner = opportunity.owner_user_id
    now = beijing_now()
    linked_actions = db.query(CustomerAction).filter(
        CustomerAction.customer_id == opportunity.customer_id,
        CustomerAction.opportunity_id == opportunity.id,
        CustomerAction.status.in_(("pending", "snoozed")),
    ).with_for_update().all()
    actions_changed = False
    for action in linked_actions:
        if action.owner_user_id != user_id:
            action.owner_user_id = user_id
            action.updated_at = now
            actions_changed = True
    if previous_owner != user_id:
        opportunity.owner_user_id = user_id
        opportunity.updated_at = now
        append_opportunity_event(
            db,
            opportunity=opportunity,
            event_type="assigned",
            actor_user_id=admin_user_id,
            event_payload={"from_user_id": previous_owner, "to_user_id": user_id},
        )
    if previous_owner != user_id or actions_changed:
        account.profile_input_seq = int(account.profile_input_seq) + 1
        account.updated_at = now
    db.commit()
    db.refresh(opportunity)
    return opportunity


__all__ = [
    "assign_opportunity",
    "get_opportunity",
    "get_opportunity_stats",
    "list_all_opportunities",
    "list_my_opportunities",
    "list_unassigned_opportunities",
    "update_opportunity_status",
]
