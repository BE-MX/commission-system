"""Customer-owned assignment, opportunity and radar workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time
import hashlib
import json
import secrets
from typing import Iterable, Mapping, Sequence

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.core.time import beijing_now, to_beijing_naive
from app.customer.fact_service import append_customer_event
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerChangeProposal,
    CustomerContact,
    CustomerContactRelationship,
    CustomerConversation,
    CustomerEvent,
    CustomerFact,
    CustomerListProjection,
    CustomerMessage,
    CustomerOpportunity,
    CustomerOpportunityEvent,
    CustomerOrder,
    CustomerProfileVersion,
    CustomerQualificationReview,
    CustomerResearchTask,
    CustomerSourceRecord,
    CustomerTargetMatch,
    SearchJob,
    SearchResult,
)


OPEN_OPPORTUNITY_STATUSES = ("pending", "contacted", "replied", "quoted")
PROPOSAL_OPEN_STATUSES = ("draft", "pending", "approved")
OPPORTUNITY_EVENT_TYPES = {
    "created",
    "assigned",
    "stage_changed",
    "contact_changed",
    "amount_changed",
    "next_step_changed",
    "closed",
    "reopened",
}
OPPORTUNITY_TRANSITIONS = {
    "pending": {"contacted", "dismissed"},
    "contacted": {"replied", "lost", "dismissed"},
    "replied": {"quoted", "lost", "dismissed"},
    "quoted": {"won", "lost", "dismissed"},
    "won": set(),
    "lost": {"pending"},
    "dismissed": {"pending"},
}
ACTION_OUTCOME_CODES = {
    "contacted",
    "replied",
    "no_response",
    "meeting_booked",
    "wrong_contact",
    "other",
}
ACTION_CHANNELS = {
    "alibaba",
    "email",
    "whatsapp",
    "phone",
    "linkedin",
    "offline",
    "internal",
}
OPPORTUNITY_CLOSE_REASON_CODES = {
    "won": {"order_confirmed", "manual_confirmed"},
    "lost": {
        "no_response",
        "price",
        "product_mismatch",
        "timing",
        "competitor",
        "budget",
        "risk_rejected",
        "other",
    },
    "dismissed": {
        "duplicate",
        "not_qualified",
        "wrong_customer",
        "no_opportunity",
        "dnc",
        "other",
    },
}


class CustomerWorkflowError(ValueError):
    """Stable customer workflow error."""


class CustomerWorkflowConflict(CustomerWorkflowError):
    """The requested transition conflicts with current customer state."""


class CustomerWorkflowNotFound(CustomerWorkflowError):
    """The requested workflow object does not exist."""


@dataclass(frozen=True, slots=True)
class QualificationWorkflowResult:
    opportunity: CustomerOpportunity
    action: CustomerAction


def _json_value(value):
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _canonical_json(value) -> str:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise CustomerWorkflowError("PAYLOAD_INVALID") from exc


def _fingerprint(*parts) -> str:
    encoded = "\x1f".join(
        _canonical_json(part)
        if isinstance(part, (Mapping, list, tuple, set))
        else str(part)
        for part in parts
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _active_user(db: Session, user_id: int) -> ArkUser:
    row = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
    ).one_or_none()
    if row is None:
        raise CustomerWorkflowConflict("USER_NOT_ACTIVE")
    return row


def _active_user_for_update_statement(user_id: int):
    return select(ArkUser.id).where(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
    ).with_for_update()


def _active_user_for_update(db: Session, user_id: int) -> ArkUser:
    locked_id = db.execute(
        _active_user_for_update_statement(user_id)
    ).scalar_one_or_none()
    if locked_id is None:
        raise CustomerWorkflowConflict("USER_NOT_ACTIVE")
    return db.get(ArkUser, locked_id)


def _account_for_update_statement(customer_id: int):
    return select(CustomerAccount).where(
        CustomerAccount.id == customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update()


def _account_for_update(db: Session, customer_id: int) -> CustomerAccount:
    row = db.execute(_account_for_update_statement(customer_id)).scalar_one_or_none()
    if row is None:
        raise CustomerWorkflowNotFound("CUSTOMER_NOT_FOUND")
    return row


def _fact_ids(
    db: Session,
    *,
    customer_id: int,
    values: Iterable[int],
) -> list[int]:
    fact_ids = sorted(set(values))
    if any(type(value) is not int or value <= 0 for value in fact_ids):
        raise CustomerWorkflowError("EVIDENCE_FACT_INVALID")
    if not fact_ids:
        return []
    rows = db.query(CustomerFact.id).filter(
        CustomerFact.customer_id == customer_id,
        CustomerFact.id.in_(fact_ids),
    ).all()
    if {row.id for row in rows} != set(fact_ids):
        raise CustomerWorkflowConflict("EVIDENCE_FACT_CUSTOMER_MISMATCH")
    return fact_ids


def _current_primary(db: Session, customer_id: int) -> CustomerAssignment | None:
    return db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id == customer_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).with_for_update().one_or_none()


def _require_owner_scope(
    db: Session,
    *,
    customer_id: int,
    owner_user_id: int,
    error_code: str,
) -> None:
    assignment = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == customer_id,
        CustomerAssignment.user_id == owner_user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first()
    if assignment is None:
        raise CustomerWorkflowConflict(error_code)


def _validate_source_reference(
    db: Session,
    *,
    customer_id: int,
    source_ref_type: str | None,
    source_ref_id: int | None,
) -> None:
    if source_ref_type is None and source_ref_id is None:
        return
    if source_ref_type is None or type(source_ref_id) is not int or source_ref_id <= 0:
        raise CustomerWorkflowError("SOURCE_REFERENCE_INVALID")
    model = {
        "source_record": CustomerSourceRecord,
        "message": CustomerMessage,
        "conversation": CustomerConversation,
        "research_task": CustomerResearchTask,
        "customer_event": CustomerEvent,
    }.get(source_ref_type)
    if model is None:
        raise CustomerWorkflowError("SOURCE_REFERENCE_INVALID")
    row = db.get(model, source_ref_id)
    if row is None:
        raise CustomerWorkflowNotFound("SOURCE_REFERENCE_NOT_FOUND")
    if source_ref_type == "message":
        conversation = db.get(CustomerConversation, row.conversation_id)
        referenced_customer_id = conversation.customer_id if conversation else None
    else:
        referenced_customer_id = row.customer_id
    if referenced_customer_id != customer_id:
        raise CustomerWorkflowConflict("SOURCE_REFERENCE_CUSTOMER_MISMATCH")


def append_opportunity_event(
    db: Session,
    *,
    opportunity: CustomerOpportunity,
    event_type: str,
    actor_user_id: int | None,
    event_payload: Mapping,
    evidence_fact_ids: Sequence[int] = (),
    from_status: str | None = None,
    to_status: str | None = None,
    occurred_at: datetime | None = None,
) -> CustomerOpportunityEvent:
    if event_type not in OPPORTUNITY_EVENT_TYPES:
        raise CustomerWorkflowError("OPPORTUNITY_EVENT_TYPE_INVALID")
    occurred = to_beijing_naive(occurred_at or beijing_now())
    evidence = _fact_ids(
        db,
        customer_id=opportunity.customer_id,
        values=evidence_fact_ids,
    )
    payload = {
        "schema_version": "opportunity_event_v1",
        **_json_value(event_payload),
    }
    fingerprint = _fingerprint(
        "opportunity_event_v1",
        opportunity.id,
        opportunity.customer_id,
        event_type,
        from_status or "",
        to_status or "",
        payload,
        evidence,
        actor_user_id or "",
        occurred.isoformat(),
    )
    existing = db.query(CustomerOpportunityEvent).filter(
        CustomerOpportunityEvent.event_fingerprint == fingerprint
    ).one_or_none()
    if existing is not None:
        return existing
    row = CustomerOpportunityEvent(
        opportunity_id=opportunity.id,
        customer_id=opportunity.customer_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        event_payload=payload,
        evidence_fact_ids=evidence,
        actor_user_id=actor_user_id,
        occurred_at=occurred,
        event_fingerprint=fingerprint,
        created_at=beijing_now(),
    )
    db.add(row)
    db.flush()
    return row


def upsert_opportunity(
    db: Session,
    *,
    customer_id: int,
    source_system: str,
    source_account_key: str,
    source_key: str,
    opportunity_type: str,
    source: str,
    title: str,
    actor_user_id: int | None = None,
    owner_user_id: int | None = None,
    source_ref_type: str | None = None,
    source_ref_id: int | None = None,
    primary_contact_id: int | None = None,
    expected_amount=None,
    currency: str | None = None,
    expected_close_date: date | None = None,
    stage_probability: int | None = None,
    forecast_category: str | None = "pipeline",
    priority_level: str = "C",
    confidence_score=0,
    urgency: str = "normal",
    summary: str | None = None,
    product_requirement_json: Mapping | None = None,
    quote_ref: str | None = None,
    competitor_json: Sequence | None = None,
    recommended_strategy: str | None = None,
    opening_message_en: str | None = None,
    follow_up_message_en: str | None = None,
    evidence_fact_ids: Sequence[int] = (),
    due_at: datetime | None = None,
    latest_message_at: datetime | None = None,
    created_by: int | None = None,
) -> CustomerOpportunity:
    account = _account_for_update(db, customer_id)
    if not all(
        isinstance(value, str) and value.strip()
        for value in (
            source_system,
            source_account_key,
            source_key,
            opportunity_type,
            source,
            title,
        )
    ):
        raise CustomerWorkflowError("OPPORTUNITY_INPUT_INVALID")
    existing = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.source_system == source_system,
        CustomerOpportunity.source_account_key == source_account_key,
        CustomerOpportunity.source_key == source_key,
    ).one_or_none()
    if existing is not None:
        if existing.customer_id != customer_id:
            raise CustomerWorkflowConflict("OPPORTUNITY_SOURCE_CONFLICT")
        return existing
    _validate_source_reference(
        db,
        customer_id=customer_id,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
    )
    if owner_user_id is not None:
        _active_user(db, owner_user_id)
        _require_owner_scope(
            db,
            customer_id=customer_id,
            owner_user_id=owner_user_id,
            error_code="OPPORTUNITY_OWNER_SCOPE_REQUIRED",
        )
    if created_by is not None:
        _active_user(db, created_by)
    if actor_user_id is not None:
        _active_user(db, actor_user_id)
    if primary_contact_id is not None:
        contact = db.get(CustomerContact, primary_contact_id)
        relation = db.query(CustomerContactRelationship.id).filter(
            CustomerContactRelationship.customer_id == customer_id,
            CustomerContactRelationship.contact_id == primary_contact_id,
            CustomerContactRelationship.effective_to.is_(None),
        ).first()
        if contact is None or relation is None:
            raise CustomerWorkflowConflict("CONTACT_CUSTOMER_MISMATCH")
    evidence = _fact_ids(
        db,
        customer_id=customer_id,
        values=evidence_fact_ids,
    )
    now = beijing_now()
    row = CustomerOpportunity(
        customer_id=customer_id,
        opportunity_type=opportunity_type,
        source=source,
        source_system=source_system,
        source_account_key=source_account_key,
        source_key=source_key,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        owner_user_id=owner_user_id,
        primary_contact_id=primary_contact_id,
        expected_amount=expected_amount,
        currency=currency,
        expected_close_date=expected_close_date,
        stage_probability=stage_probability,
        forecast_category=forecast_category,
        priority_level=priority_level,
        confidence_score=confidence_score,
        urgency=urgency,
        title=title,
        summary=summary,
        product_requirement_json={
            "schema_version": "opportunity_requirement_v1",
            **_json_value(product_requirement_json or {}),
        },
        quote_ref=quote_ref,
        competitor_json=list(_json_value(competitor_json or [])),
        recommended_strategy=recommended_strategy,
        opening_message_en=opening_message_en,
        follow_up_message_en=follow_up_message_en,
        evidence_fact_ids=evidence,
        status="pending",
        stage_entered_at=now,
        due_at=to_beijing_naive(due_at) if due_at is not None else None,
        latest_message_at=(
            to_beijing_naive(latest_message_at)
            if latest_message_at is not None
            else None
        ),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        existing = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.source_system == source_system,
            CustomerOpportunity.source_account_key == source_account_key,
            CustomerOpportunity.source_key == source_key,
        ).one_or_none()
        if existing is not None:
            if existing.customer_id != customer_id:
                raise CustomerWorkflowConflict("OPPORTUNITY_SOURCE_CONFLICT") from exc
            return existing
        raise CustomerWorkflowConflict("RETRY_NEW_TRANSACTION") from exc
    append_opportunity_event(
        db,
        opportunity=row,
        event_type="created",
        actor_user_id=actor_user_id,
        event_payload={
            "source_system": source_system,
            "source_account_key": source_account_key,
            "source_key": source_key,
        },
        evidence_fact_ids=evidence,
        occurred_at=now,
    )
    append_customer_event(
        db,
        customer_id=customer_id,
        event_type="opportunity.created",
        event_source="opportunity",
        event_title="创建销售机会",
        event_summary=title,
        event_payload={
            "source_system": source_system,
            "source_account_key": source_account_key,
            "source_key": source_key,
            "status": "pending",
        },
        payload_schema_version="customer_event_v1",
        occurred_at=now,
        source_ref_type="opportunity",
        source_ref_id=str(row.id),
        evidence_fact_ids=evidence,
        actor_user_id=actor_user_id,
    )
    account.updated_at = now
    db.flush()
    return row


def create_action(
    db: Session,
    *,
    customer_id: int,
    owner_user_id: int | None,
    profile_version_id: int,
    action_type: str,
    thread_group: str,
    priority: str,
    reason: str,
    next_action: str,
    policy_version: str,
    source_type: str,
    source_event_ids: Sequence[int],
    evidence_fact_ids: Sequence[int],
    action_date: date,
    opportunity_id: int | None = None,
    contact_id: int | None = None,
    channel: str | None = None,
    suggested_message: str | None = None,
    planned_at: datetime | None = None,
    due_at: datetime | None = None,
    agent_run_id: int | None = None,
    feedback_json: Mapping | None = None,
) -> CustomerAction:
    account = _account_for_update(db, customer_id)
    if owner_user_id is None:
        if thread_group != "public_pool":
            raise CustomerWorkflowConflict("ACTION_OWNER_REQUIRED")
    else:
        _active_user(db, owner_user_id)
        _require_owner_scope(
            db,
            customer_id=customer_id,
            owner_user_id=owner_user_id,
            error_code="ACTION_OWNER_SCOPE_REQUIRED",
        )
    profile = db.query(CustomerProfileVersion).filter(
        CustomerProfileVersion.id == profile_version_id,
        CustomerProfileVersion.customer_id == customer_id,
    ).one_or_none()
    if profile is None:
        raise CustomerWorkflowConflict("PROFILE_CUSTOMER_MISMATCH")
    if opportunity_id is not None:
        opportunity = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.id == opportunity_id,
            CustomerOpportunity.customer_id == customer_id,
        ).one_or_none()
        if opportunity is None:
            raise CustomerWorkflowConflict("OPPORTUNITY_CUSTOMER_MISMATCH")
        if (
            owner_user_id is not None
            and opportunity.owner_user_id != owner_user_id
        ):
            raise CustomerWorkflowConflict("ACTION_OPPORTUNITY_OWNER_MISMATCH")
    if contact_id is not None:
        relation = db.query(CustomerContactRelationship.id).filter(
            CustomerContactRelationship.customer_id == customer_id,
            CustomerContactRelationship.contact_id == contact_id,
            CustomerContactRelationship.effective_to.is_(None),
            CustomerContactRelationship.verification_status.in_(("identified", "verified")),
        ).one_or_none()
        if relation is None:
            raise CustomerWorkflowConflict("CONTACT_CUSTOMER_MISMATCH")
    evidence = _fact_ids(
        db,
        customer_id=customer_id,
        values=evidence_fact_ids,
    )
    event_ids = sorted(set(source_event_ids))
    if event_ids:
        rows = db.query(CustomerEvent.id).filter(
            CustomerEvent.customer_id == customer_id,
            CustomerEvent.id.in_(event_ids),
        ).all()
        if {row.id for row in rows} != set(event_ids):
            raise CustomerWorkflowConflict("SOURCE_EVENT_CUSTOMER_MISMATCH")
    action_fingerprint = _fingerprint(
        "customer_action_v1",
        customer_id,
        opportunity_id or "",
        contact_id or "",
        action_type,
        thread_group,
        channel or "",
        action_date.isoformat(),
        policy_version,
        event_ids,
        evidence,
    )
    existing = db.query(CustomerAction).filter(
        CustomerAction.action_fingerprint == action_fingerprint
    ).one_or_none()
    if existing is not None:
        if existing.status in {"pending", "snoozed"}:
            projection = {
                "profile_version_id": profile_version_id,
                "priority": priority,
                "reason": reason,
                "next_action": next_action,
                "suggested_message": suggested_message,
                "planned_at": to_beijing_naive(planned_at) if planned_at else None,
                "due_at": to_beijing_naive(due_at) if due_at else None,
                "source_type": source_type,
                "agent_run_id": agent_run_id,
            }
            changed = any(
                getattr(existing, field) != value
                for field, value in projection.items()
            )
            if changed:
                for field, value in projection.items():
                    setattr(existing, field, value)
                now = beijing_now()
                existing.generated_at = now
                existing.updated_at = now
                account.profile_input_seq = int(account.profile_input_seq) + 1
                account.updated_at = now
                db.flush()
        return existing
    now = beijing_now()
    row = CustomerAction(
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        opportunity_id=opportunity_id,
        contact_id=contact_id,
        action_type=action_type,
        thread_group=thread_group,
        channel=channel,
        priority=priority,
        reason=reason,
        next_action=next_action,
        suggested_message=suggested_message,
        planned_at=to_beijing_naive(planned_at) if planned_at else None,
        due_at=to_beijing_naive(due_at) if due_at else None,
        action_date=action_date,
        status="pending",
        snoozed_until=None,
        completed_at=None,
        completed_by=None,
        outcome_code=None,
        dismissal_reason=None,
        feedback_json={
            "schema_version": "action_feedback_v1",
            **_json_value(feedback_json or {}),
        },
        source_event_ids=event_ids,
        evidence_fact_ids=evidence,
        profile_version_id=profile_version_id,
        source_type=source_type,
        agent_run_id=agent_run_id,
        policy_version=policy_version,
        action_fingerprint=action_fingerprint,
        evidence_status="valid",
        generated_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        existing = db.query(CustomerAction).filter(
            CustomerAction.action_fingerprint == action_fingerprint
        ).one_or_none()
        if existing is not None:
            return existing
        raise CustomerWorkflowConflict("RETRY_NEW_TRANSACTION") from exc
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = now
    db.flush()
    return row


def _qualification_source_key(
    db: Session,
    review: CustomerQualificationReview,
) -> tuple[str, str, str, str | None, int | None]:
    if review.review_source == "search_result":
        if not str(review.source_ref_id or "").isdigit():
            raise CustomerWorkflowConflict("QUALIFICATION_SOURCE_INVALID")
        result = db.get(SearchResult, int(review.source_ref_id))
        job = db.get(SearchJob, result.job_id) if result else None
        if (
            result is None
            or job is None
            or result.customer_id != review.customer_id
            or result.result_status != "qualified"
        ):
            raise CustomerWorkflowConflict("QUALIFICATION_SOURCE_INVALID")
        return (
            "search",
            "global",
            f"job:{job.id}:result:{result.id}",
            None,
            None,
        )
    if review.review_source == "public_pool_research":
        if not str(review.source_ref_id or "").isdigit():
            raise CustomerWorkflowConflict("QUALIFICATION_SOURCE_INVALID")
        task = db.get(CustomerResearchTask, int(review.source_ref_id))
        if (
            task is None
            or task.customer_id != review.customer_id
            or task.task_status != "completed"
            or task.gate_status != "passed"
            or task.result_review_status != "accepted"
        ):
            raise CustomerWorkflowConflict("QUALIFICATION_SOURCE_INVALID")
        return (
            "public_pool",
            "global",
            f"research:{task.task_fingerprint}",
            "research_task",
            task.id,
        )
    raise CustomerWorkflowConflict("QUALIFICATION_SOURCE_NOT_ACTIONABLE")


def orchestrate_qualification_review(
    db: Session,
    review_id: int,
) -> QualificationWorkflowResult | None:
    candidate = db.get(CustomerQualificationReview, review_id)
    if candidate is None:
        raise CustomerWorkflowNotFound("QUALIFICATION_REVIEW_NOT_FOUND")
    account = _account_for_update(db, candidate.customer_id)
    review = db.query(CustomerQualificationReview).filter(
        CustomerQualificationReview.id == review_id,
        CustomerQualificationReview.customer_id == account.id,
    ).with_for_update().one_or_none()
    if review is None:
        raise CustomerWorkflowNotFound("QUALIFICATION_REVIEW_NOT_FOUND")
    if review.decision != "approved":
        return None
    if not review.is_current or review.reason_code != "qualified":
        raise CustomerWorkflowConflict("QUALIFICATION_NOT_CURRENT")
    if review.review_source not in {"search_result", "public_pool_research"}:
        return None
    if account.current_profile_version_id is None:
        raise CustomerWorkflowConflict("PROFILE_NOT_READY")
    source_system, source_account_key, source_key, source_ref_type, source_ref_id = (
        _qualification_source_key(db, review)
    )
    snapshot = dict(review.review_snapshot or {})
    evidence = _fact_ids(
        db,
        customer_id=account.id,
        values=snapshot.get("evidence_fact_ids") or (),
    )
    primary = _current_primary(db, account.id)
    opportunity = upsert_opportunity(
        db,
        customer_id=account.id,
        source_system=source_system,
        source_account_key=source_account_key,
        source_key=source_key,
        opportunity_type="public_pool",
        source="public_pool",
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        owner_user_id=primary.user_id if primary else None,
        title=f"开发 {account.display_name}",
        summary="资格审核通过，等待业务员领取或跟进。",
        priority_level=str(snapshot.get("priority_level") or "C"),
        confidence_score=snapshot.get("confidence_score") or 0,
        urgency="high" if snapshot.get("priority_level") == "A" else "normal",
        evidence_fact_ids=evidence,
        actor_user_id=review.reviewed_by,
    )
    qualification_event = append_customer_event(
        db,
        customer_id=account.id,
        event_type="qualification.reviewed",
        event_source="qualification",
        event_title="客户资格审核通过",
        event_summary=review.reason_text,
        event_payload={"decision": "approved"},
        payload_schema_version="customer_event_v1",
        occurred_at=review.reviewed_at,
        source_ref_type="qualification_review",
        source_ref_id=str(review.id),
        evidence_fact_ids=evidence,
        actor_user_id=review.reviewed_by,
    )
    if account.relationship_stage == "discovered":
        append_customer_event(
            db,
            customer_id=account.id,
            event_type="relationship.stage_changed",
            event_source="qualification",
            event_title="客户进入合格阶段",
            event_summary="当前作用范围资格审核通过",
            event_payload={"reason_code": "qualification_approved"},
            payload_schema_version="customer_event_v1",
            occurred_at=review.reviewed_at,
            source_ref_type="qualification_review",
            source_ref_id=str(review.id),
            evidence_fact_ids=evidence,
            actor_user_id=review.reviewed_by,
            target_relationship_stage="qualified",
            transition_trigger="qualification_approved",
        )
    action = create_action(
        db,
        customer_id=account.id,
        owner_user_id=primary.user_id if primary else None,
        opportunity_id=opportunity.id,
        profile_version_id=account.current_profile_version_id,
        action_type="review",
        thread_group="public_pool",
        channel="internal",
        priority="high" if opportunity.priority_level == "A" else "normal",
        reason="客户已通过资格审核，需要确认首轮开发策略。",
        next_action="复核档案证据并准备首次人工联系。",
        policy_version=review.policy_version,
        source_type="rule",
        source_event_ids=[qualification_event.id],
        evidence_fact_ids=evidence,
        action_date=review.reviewed_at.date(),
        feedback_json={
            "queue_assignment": {
                "mode": "primary_owner" if primary else "public_pool_unassigned",
                "does_not_confer_customer_ownership": primary is None,
                "qualification_review_id": review.id,
            }
        },
    )
    return QualificationWorkflowResult(opportunity=opportunity, action=action)


def assign_customer(
    db: Session,
    *,
    customer_id: int,
    user_id: int,
    assignment_role: str,
    assignment_source: str,
    operated_by: int,
    change_reason: str | None = None,
    _expected_previous_owner_user_id: int | None = None,
) -> CustomerAssignment:
    account = _account_for_update(db, customer_id)
    _active_user(db, user_id)
    _active_user(db, operated_by)
    if assignment_role not in {"primary", "collaborator"}:
        raise CustomerWorkflowError("ASSIGNMENT_ROLE_INVALID")
    existing = db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id == customer_id,
        CustomerAssignment.user_id == user_id,
        CustomerAssignment.assignment_role == assignment_role,
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).one_or_none()
    if existing is not None:
        return existing
    if assignment_role == "primary":
        if _current_primary(db, customer_id) is not None:
            raise CustomerWorkflowConflict("PRIMARY_OWNER_CONFLICT")
        owner_conflict = CustomerOpportunity.owner_user_id != user_id
        if _expected_previous_owner_user_id is not None:
            owner_conflict = CustomerOpportunity.owner_user_id.notin_((
                user_id,
                _expected_previous_owner_user_id,
            ))
        conflicting_opportunity = db.query(CustomerOpportunity.id).filter(
            CustomerOpportunity.customer_id == customer_id,
            CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
            CustomerOpportunity.owner_user_id.isnot(None),
            owner_conflict,
        ).first()
        if conflicting_opportunity is not None:
            raise CustomerWorkflowConflict("OPPORTUNITY_OWNER_CONFLICT")
    now = beijing_now()
    row = CustomerAssignment(
        customer_id=customer_id,
        user_id=user_id,
        assignment_role=assignment_role,
        assignment_status="active",
        assignment_source=assignment_source,
        effective_from=now,
        effective_to=None,
        change_reason=change_reason,
        operated_by=operated_by,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        winner_query = db.query(CustomerAssignment).filter(
            CustomerAssignment.customer_id == customer_id,
            CustomerAssignment.assignment_role == assignment_role,
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        )
        if assignment_role == "collaborator":
            winner_query = winner_query.filter(CustomerAssignment.user_id == user_id)
        winner = winner_query.one_or_none()
        if winner is not None and winner.user_id == user_id:
            return winner
        if winner is not None:
            raise CustomerWorkflowConflict("PRIMARY_OWNER_CONFLICT") from exc
        raise CustomerWorkflowConflict("RETRY_NEW_TRANSACTION") from exc
    append_customer_event(
        db,
        customer_id=customer_id,
        event_type="assignment.changed",
        event_source="assignment",
        event_title="客户归属已更新",
        event_summary=change_reason,
        event_payload={"assignment_status": "active"},
        payload_schema_version="customer_event_v1",
        occurred_at=now,
        source_ref_type="assignment",
        source_ref_id=str(row.id),
        actor_user_id=operated_by,
    )
    if assignment_role == "primary":
        opportunities = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.customer_id == customer_id,
            CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
            CustomerOpportunity.owner_user_id.is_(None),
        ).with_for_update().all()
        for opportunity in opportunities:
            opportunity.owner_user_id = user_id
            opportunity.updated_at = now
            append_opportunity_event(
                db,
                opportunity=opportunity,
                event_type="assigned",
                actor_user_id=operated_by,
                event_payload={
                    "old_owner_user_id": None,
                    "new_owner_user_id": user_id,
                    "assignment_id": row.id,
                },
                occurred_at=now,
            )
        actions = db.query(CustomerAction).filter(
            CustomerAction.customer_id == customer_id,
            CustomerAction.owner_user_id.is_(None),
            CustomerAction.status == "pending",
        ).with_for_update().all()
        for action in actions:
            feedback = dict(action.feedback_json or {})
            feedback["queue_assignment"] = {
                "mode": "primary_owner",
                "does_not_confer_customer_ownership": False,
                "assignment_id": row.id,
            }
            action.owner_user_id = user_id
            action.feedback_json = feedback
            action.updated_at = now
    account.updated_at = now
    db.flush()
    return row


def transfer_primary_owner(
    db: Session,
    *,
    customer_id: int,
    new_user_id: int,
    operated_by: int,
    change_reason: str,
) -> CustomerAssignment:
    account = _account_for_update(db, customer_id)
    _active_user(db, new_user_id)
    _active_user(db, operated_by)
    current = _current_primary(db, customer_id)
    if current is None:
        return assign_customer(
            db,
            customer_id=customer_id,
            user_id=new_user_id,
            assignment_role="primary",
            assignment_source="transfer",
            operated_by=operated_by,
            change_reason=change_reason,
        )
    if current.user_id == new_user_id:
        return current
    now = beijing_now()
    old_user_id = current.user_id
    current.assignment_status = "ended"
    current.effective_to = now
    current.change_reason = change_reason
    current.operated_by = operated_by
    current.updated_at = now
    db.flush()
    append_customer_event(
        db,
        customer_id=customer_id,
        event_type="assignment.changed",
        event_source="assignment",
        event_title="原主负责人归属结束",
        event_summary=change_reason,
        event_payload={"assignment_status": "ended"},
        payload_schema_version="customer_event_v1",
        occurred_at=now,
        source_ref_type="assignment",
        source_ref_id=str(current.id),
        actor_user_id=operated_by,
    )
    replacement = assign_customer(
        db,
        customer_id=customer_id,
        user_id=new_user_id,
        assignment_role="primary",
        assignment_source="transfer",
        operated_by=operated_by,
        change_reason=change_reason,
        _expected_previous_owner_user_id=old_user_id,
    )
    opportunities = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.customer_id == customer_id,
        CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
        or_(
            CustomerOpportunity.owner_user_id == old_user_id,
            CustomerOpportunity.owner_user_id.is_(None),
        ),
    ).all()
    for opportunity in opportunities:
        previous = opportunity.owner_user_id
        opportunity.owner_user_id = new_user_id
        opportunity.updated_at = now
        append_opportunity_event(
            db,
            opportunity=opportunity,
            event_type="assigned",
            actor_user_id=operated_by,
            event_payload={"old_owner_user_id": previous, "new_owner_user_id": new_user_id},
            occurred_at=now,
        )
    actions = db.query(CustomerAction).filter(
        CustomerAction.customer_id == customer_id,
        CustomerAction.owner_user_id == old_user_id,
        CustomerAction.status.in_(("pending", "snoozed")),
    ).with_for_update().all()
    for action in actions:
        feedback = dict(action.feedback_json or {})
        feedback["owner_transfer"] = {
            "from_user_id": old_user_id,
            "to_user_id": new_user_id,
            "operated_by": operated_by,
        }
        action.owner_user_id = new_user_id
        action.feedback_json = feedback
        action.updated_at = now
    account.updated_at = now
    db.flush()
    return replacement


def _scope_review(
    db: Session,
    *,
    customer_id: int,
    scope_type: str,
    scope_ref_id: str | None,
) -> CustomerQualificationReview | None:
    query = db.query(CustomerQualificationReview).filter(
        CustomerQualificationReview.customer_id == customer_id,
        CustomerQualificationReview.scope_type == scope_type,
        CustomerQualificationReview.is_current.is_(True),
    )
    query = query.filter(
        CustomerQualificationReview.scope_ref_id.is_(None)
        if scope_ref_id is None
        else CustomerQualificationReview.scope_ref_id == scope_ref_id
    )
    return query.with_for_update().one_or_none()


def claim_public_pool_customer(
    db: Session,
    *,
    customer_id: int,
    claimant_user_id: int,
    operated_by: int,
    scope_type: str,
    scope_ref_id: str | None,
    allowed_user_ids: set[int],
    per_user_quota: int,
) -> CustomerAssignment:
    _active_user_for_update(db, claimant_user_id)
    account = _account_for_update(db, customer_id)
    if operated_by != claimant_user_id:
        _active_user(db, operated_by)
    current = _current_primary(db, customer_id)
    if current is not None:
        if current.user_id != claimant_user_id:
            raise CustomerWorkflowConflict("ALREADY_CLAIMED")
    if account.identity_status == "disputed":
        raise CustomerWorkflowConflict("IDENTITY_DISPUTED")
    if account.relationship_stage == "inactive":
        raise CustomerWorkflowConflict("RELATIONSHIP_INACTIVE")
    projection = db.query(CustomerListProjection).filter(
        CustomerListProjection.customer_id == customer_id
    ).with_for_update().one_or_none()
    if projection is None:
        raise CustomerWorkflowConflict("PROFILE_NOT_READY")
    now = beijing_now()
    if projection.global_claim_blocked:
        raise CustomerWorkflowConflict("CLAIM_BLOCKED")
    if projection.claim_cooldown_until is not None and projection.claim_cooldown_until > now:
        raise CustomerWorkflowConflict("CLAIM_COOLDOWN")
    review = _scope_review(
        db,
        customer_id=customer_id,
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
    )
    if review is None or review.decision != "approved" or review.reason_code != "qualified":
        raise CustomerWorkflowConflict("QUALIFICATION_REQUIRED")
    from app.sales_automation.public_pool_service import is_development_denied

    if is_development_denied(db, customer_id, scope_type, scope_ref_id):
        raise CustomerWorkflowConflict("DO_NOT_CONTACT")
    if claimant_user_id not in allowed_user_ids:
        raise CustomerWorkflowConflict("TEAM_SCOPE_DENIED")
    if per_user_quota <= 0:
        raise CustomerWorkflowConflict("CLAIM_QUOTA_EXCEEDED")
    active_claim_count = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.user_id == claimant_user_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.assignment_source == "public_pool_claim",
        CustomerAssignment.effective_to.is_(None),
        CustomerAssignment.customer_id != customer_id,
    ).count()
    if active_claim_count >= per_user_quota:
        raise CustomerWorkflowConflict("CLAIM_QUOTA_EXCEEDED")
    if scope_type == "target_profile":
        if not str(scope_ref_id or "").isdigit():
            raise CustomerWorkflowConflict("TARGET_MATCH_REQUIRED")
        target_match = db.query(CustomerTargetMatch).filter(
            CustomerTargetMatch.customer_id == customer_id,
            CustomerTargetMatch.target_profile_id == int(scope_ref_id),
            CustomerTargetMatch.is_current.is_(True),
            CustomerTargetMatch.match_status == "qualified",
        ).one_or_none()
        if (
            target_match is None
            or (
                target_match.expires_at is not None
                and target_match.expires_at <= now
            )
        ):
            raise CustomerWorkflowConflict("TARGET_MATCH_REQUIRED")
    conflicting_opportunity = db.query(CustomerOpportunity.id).filter(
        CustomerOpportunity.customer_id == customer_id,
        CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
        CustomerOpportunity.owner_user_id.isnot(None),
        CustomerOpportunity.owner_user_id != claimant_user_id,
    ).first()
    if conflicting_opportunity is not None:
        raise CustomerWorkflowConflict("OPPORTUNITY_OWNER_CONFLICT")
    claim_opportunities = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.customer_id == customer_id,
        CustomerOpportunity.status.in_(OPEN_OPPORTUNITY_STATUSES),
        or_(
            CustomerOpportunity.owner_user_id.is_(None),
            CustomerOpportunity.owner_user_id == claimant_user_id,
        ),
    ).with_for_update().all()
    assignment = assign_customer(
        db,
        customer_id=customer_id,
        user_id=claimant_user_id,
        assignment_role="primary",
        assignment_source="public_pool_claim",
        operated_by=operated_by,
        change_reason="public_pool_claim",
    )
    opportunity_ids = []
    for opportunity in claim_opportunities:
        opportunity_ids.append(opportunity.id)
        if opportunity.owner_user_id == claimant_user_id:
            continue
        opportunity.owner_user_id = claimant_user_id
        opportunity.updated_at = now
        append_opportunity_event(
            db,
            opportunity=opportunity,
            event_type="assigned",
            actor_user_id=operated_by,
            event_payload={
                "old_owner_user_id": None,
                "new_owner_user_id": claimant_user_id,
                "assignment_id": assignment.id,
            },
            occurred_at=now,
        )
    if opportunity_ids:
        actions = db.query(CustomerAction).filter(
            CustomerAction.customer_id == customer_id,
            CustomerAction.opportunity_id.in_(opportunity_ids),
            CustomerAction.status == "pending",
        ).with_for_update().all()
        for action in actions:
            feedback = dict(action.feedback_json or {})
            feedback["queue_assignment"] = {
                "mode": "claimed_primary_owner",
                "does_not_confer_customer_ownership": False,
                "assignment_id": assignment.id,
            }
            action.owner_user_id = claimant_user_id
            action.feedback_json = feedback
            action.updated_at = now
    if account.relationship_stage == "qualified" and opportunity_ids:
        append_customer_event(
            db,
            customer_id=customer_id,
            event_type="relationship.stage_changed",
            event_source="manual",
            event_title="客户进入开发阶段",
            event_summary="公海领取后已有主负责人和开放机会",
            event_payload={"reason_code": "sales_development_ready"},
            payload_schema_version="customer_event_v1",
            occurred_at=now,
            source_ref_type="customer",
            source_ref_id=str(customer_id),
            actor_user_id=operated_by,
            target_relationship_stage="developing",
            transition_trigger="sales_development_ready",
        )
    db.flush()
    return assignment


def _event_binds_opportunity(
    db: Session,
    *,
    event: CustomerEvent,
    opportunity: CustomerOpportunity,
) -> bool:
    bindings: list[bool] = []
    payload_opportunity_id = (event.event_payload or {}).get("opportunity_id")
    if payload_opportunity_id is not None:
        bindings.append(str(payload_opportunity_id) == str(opportunity.id))
    if event.source_ref_type == "action" and str(event.source_ref_id or "").isdigit():
        action = db.get(CustomerAction, int(event.source_ref_id))
        bindings.append(
            action is not None
            and action.customer_id == opportunity.customer_id
            and action.opportunity_id == opportunity.id
        )
    if event.source_ref_type == "message" and str(event.source_ref_id or "").isdigit():
        message = db.get(CustomerMessage, int(event.source_ref_id))
        conversation = (
            db.get(CustomerConversation, message.conversation_id)
            if message is not None
            else None
        )
        if opportunity.source_ref_type == "message":
            bindings.append(str(opportunity.source_ref_id) == str(event.source_ref_id))
        elif opportunity.source_ref_type == "conversation":
            bindings.append(
                conversation is not None
                and str(opportunity.source_ref_id) == str(conversation.id)
            )
    return bool(bindings) and all(bindings)


def _event_supports_stage(
    db: Session,
    *,
    event: CustomerEvent,
    opportunity: CustomerOpportunity,
    new_status: str,
) -> bool:
    if not _event_binds_opportunity(db, event=event, opportunity=opportunity):
        return False
    if event.occurred_at < opportunity.stage_entered_at:
        return False
    payload = event.event_payload or {}
    if new_status == "contacted":
        return (
            event.event_type == "message.sent"
            or (
                event.event_type == "sales_activity.logged"
                and payload.get("outcome_code")
                in {"contacted", "replied", "meeting_booked"}
            )
        )
    if new_status == "replied":
        return event.event_type == "message.received"
    if new_status == "quoted":
        return (
            bool(opportunity.quote_ref)
            and event.event_type == "message.sent"
        )
    return False


def transition_opportunity(
    db: Session,
    *,
    opportunity_id: int,
    new_status: str,
    actor_user_id: int,
    reason: str | None = None,
    close_reason_code: str | None = None,
    close_reason_text: str | None = None,
    evidence_fact_ids: Sequence[int] = (),
    evidence_event_ids: Sequence[int] = (),
    linked_order_id: int | None = None,
    occurred_at: datetime | None = None,
    can_manage: bool = False,
) -> CustomerOpportunity:
    candidate = db.get(CustomerOpportunity, opportunity_id)
    if candidate is None:
        raise CustomerWorkflowNotFound("OPPORTUNITY_NOT_FOUND")
    _account_for_update(db, candidate.customer_id)
    opportunity = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.id == opportunity_id
    ).with_for_update().one_or_none()
    if opportunity is None:
        raise CustomerWorkflowNotFound("OPPORTUNITY_NOT_FOUND")
    actor = _active_user(db, actor_user_id)
    if not can_manage:
        assignment = db.query(CustomerAssignment.id).filter(
            CustomerAssignment.customer_id == opportunity.customer_id,
            CustomerAssignment.user_id == actor_user_id,
            CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
            CustomerAssignment.assignment_status == "active",
            CustomerAssignment.effective_to.is_(None),
        ).first()
        if assignment is None or opportunity.owner_user_id != actor_user_id:
            raise CustomerWorkflowConflict("OPPORTUNITY_ACTOR_FORBIDDEN")
    if new_status not in OPPORTUNITY_TRANSITIONS.get(opportunity.status, set()):
        raise CustomerWorkflowConflict("OPPORTUNITY_TRANSITION_INVALID")
    closing = new_status in OPPORTUNITY_CLOSE_REASON_CODES
    if closing:
        if close_reason_code not in OPPORTUNITY_CLOSE_REASON_CODES[new_status]:
            raise CustomerWorkflowError("OPPORTUNITY_CLOSE_REASON_INVALID")
        if close_reason_text is not None and len(close_reason_text.strip()) > 1000:
            raise CustomerWorkflowError("OPPORTUNITY_CLOSE_REASON_TEXT_INVALID")
        normalized_close_text = (
            close_reason_text.strip() if close_reason_text is not None else None
        )
        manual_won_exception = (
            new_status == "won" and close_reason_code == "manual_confirmed"
        )
        if manual_won_exception:
            if linked_order_id is not None:
                raise CustomerWorkflowError("OPPORTUNITY_INPUT_INVALID")
            if not normalized_close_text:
                raise CustomerWorkflowError("OPPORTUNITY_CLOSE_REASON_TEXT_INVALID")
            actor_permissions = set(get_user_permissions(actor))
            actor_roles = set(get_user_roles(actor))
            if (
                "super_admin" not in actor_roles
                and "customer_opportunity:confirm_without_order"
                not in actor_permissions
            ):
                raise CustomerWorkflowConflict("MANUAL_WON_PERMISSION_REQUIRED")
        event_reason = normalized_close_text or close_reason_code
    else:
        if close_reason_code is not None or close_reason_text is not None:
            raise CustomerWorkflowError("OPPORTUNITY_CLOSE_REASON_INVALID")
        normalized_close_text = None
        manual_won_exception = False
        event_reason = (reason or "stage_updated").strip()
    evidence = _fact_ids(
        db,
        customer_id=opportunity.customer_id,
        values=evidence_fact_ids,
    )
    events = []
    if evidence_event_ids:
        events = db.query(CustomerEvent).filter(
            CustomerEvent.customer_id == opportunity.customer_id,
            CustomerEvent.id.in_(set(evidence_event_ids)),
        ).all()
        if {row.id for row in events} != set(evidence_event_ids):
            raise CustomerWorkflowConflict("OPPORTUNITY_EVIDENCE_INVALID")
    if new_status in {"contacted", "replied", "quoted"}:
        if not events:
            raise CustomerWorkflowConflict("OPPORTUNITY_EVIDENCE_REQUIRED")
        if not all(
            _event_supports_stage(
                db,
                event=row,
                opportunity=opportunity,
                new_status=new_status,
            )
            for row in events
        ):
            raise CustomerWorkflowConflict("OPPORTUNITY_EVIDENCE_INVALID")
    if new_status == "won" and not manual_won_exception:
        order = db.query(CustomerOrder).filter(
            CustomerOrder.id == linked_order_id,
            CustomerOrder.customer_id == opportunity.customer_id,
            CustomerOrder.is_valid_business_order.is_(True),
        ).one_or_none()
        if order is None:
            raise CustomerWorkflowConflict("VALID_ORDER_REQUIRED")
        opportunity.linked_order_id = order.id
    now = to_beijing_naive(occurred_at or beijing_now())
    if (
        now < opportunity.stage_entered_at
        or (events and now < max(event.occurred_at for event in events))
    ):
        raise CustomerWorkflowConflict("OPPORTUNITY_STAGE_TIME_INVALID")
    previous = opportunity.status
    opportunity.status = new_status
    opportunity.stage_entered_at = now
    opportunity.updated_at = now
    if closing:
        opportunity.close_reason_code = close_reason_code
        opportunity.close_reason_text = normalized_close_text
    elif previous in {"lost", "dismissed"} and new_status == "pending":
        opportunity.close_reason_code = None
        opportunity.close_reason_text = None
    db.flush()
    opportunity_event_payload = {
        "reason": event_reason,
        "evidence_event_ids": sorted(set(evidence_event_ids)),
        "linked_order_id": linked_order_id,
    }
    customer_event_payload = {
        "from_status": previous,
        "to_status": new_status,
        "reason": event_reason,
    }
    if close_reason_code is not None:
        opportunity_event_payload["close_reason_code"] = close_reason_code
        customer_event_payload["close_reason_code"] = close_reason_code
    if normalized_close_text is not None:
        opportunity_event_payload["close_reason_text"] = normalized_close_text
        customer_event_payload["close_reason_text"] = normalized_close_text
    if manual_won_exception:
        opportunity_event_payload["manual_won_exception"] = True
        customer_event_payload["manual_won_exception"] = True
    append_opportunity_event(
        db,
        opportunity=opportunity,
        event_type=(
            "reopened"
            if previous in {"lost", "dismissed"}
            else "closed"
            if new_status in {"won", "lost", "dismissed"}
            else "stage_changed"
        ),
        actor_user_id=actor_user_id,
        event_payload=opportunity_event_payload,
        evidence_fact_ids=evidence,
        from_status=previous,
        to_status=new_status,
        occurred_at=now,
    )
    append_customer_event(
        db,
        customer_id=opportunity.customer_id,
        event_type="opportunity.stage_changed",
        event_source="opportunity",
        event_title="销售机会阶段已更新",
        event_summary=event_reason,
        event_payload=customer_event_payload,
        payload_schema_version="customer_event_v1",
        occurred_at=now,
        source_ref_type="opportunity",
        source_ref_id=str(opportunity.id),
        evidence_fact_ids=evidence,
        actor_user_id=actor_user_id,
        data_classification=(
            "restricted_internal"
            if manual_won_exception
            else "internal_business"
        ),
        visibility_scope=(
            "management" if manual_won_exception else "customer_team"
        ),
        classification_reason=(
            "manual won exception requires dedicated permission"
            if manual_won_exception
            else None
        ),
    )
    return opportunity


def complete_action(
    db: Session,
    *,
    action_id: int,
    completed_by: int,
    occurred_at: datetime,
    channel: str,
    outcome_code: str,
    summary: str,
    next_step: str,
) -> CustomerAction:
    if outcome_code not in ACTION_OUTCOME_CODES:
        raise CustomerWorkflowError("ACTION_OUTCOME_INVALID")
    if channel not in ACTION_CHANNELS:
        raise CustomerWorkflowError("ACTION_CHANNEL_INVALID")
    normalized_summary = summary.strip()
    normalized_next_step = next_step.strip()
    if not normalized_summary or len(normalized_summary) > 1000:
        raise CustomerWorkflowError("ACTION_SUMMARY_INVALID")
    if len(normalized_next_step) > 1000:
        raise CustomerWorkflowError("ACTION_NEXT_STEP_INVALID")
    occurred = to_beijing_naive(occurred_at)
    if occurred > beijing_now():
        raise CustomerWorkflowError("ACTION_OCCURRED_AT_INVALID")
    candidate = db.get(CustomerAction, action_id)
    if candidate is None:
        raise CustomerWorkflowNotFound("ACTION_NOT_FOUND")
    _account_for_update(db, candidate.customer_id)
    action = db.query(CustomerAction).filter(
        CustomerAction.id == action_id
    ).with_for_update().one_or_none()
    if action is None:
        raise CustomerWorkflowNotFound("ACTION_NOT_FOUND")
    _active_user(db, completed_by)
    if action.owner_user_id != completed_by:
        raise CustomerWorkflowConflict("ACTION_OWNER_REQUIRED")
    assignment = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == action.customer_id,
        CustomerAssignment.user_id == completed_by,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first()
    opportunity = (
        db.get(CustomerOpportunity, action.opportunity_id)
        if action.opportunity_id is not None
        else None
    )
    if (
        assignment is None
        or (
            opportunity is not None
            and opportunity.owner_user_id != completed_by
        )
    ):
        raise CustomerWorkflowConflict("ACTION_ACTOR_FORBIDDEN")
    if action.status == "done":
        return action
    if action.status != "pending":
        raise CustomerWorkflowConflict("ACTION_NOT_PENDING")
    action.status = "done"
    action.completed_at = occurred
    action.completed_by = completed_by
    action.outcome_code = outcome_code
    action.feedback_json = {
        **dict(action.feedback_json or {}),
        "completion": {
            "channel": channel,
            "outcome_code": outcome_code,
            "summary": normalized_summary,
            "next_step": normalized_next_step,
        },
    }
    action.updated_at = beijing_now()
    db.flush()
    payload = {
        "action_id": action.id,
        "customer_id": action.customer_id,
        "channel": channel,
        "occurred_at": occurred.isoformat(),
        "outcome_code": outcome_code,
        "summary": normalized_summary,
        "next_step": normalized_next_step,
    }
    if action.opportunity_id is not None:
        payload["opportunity_id"] = action.opportunity_id
    if action.contact_id is not None:
        payload["contact_id"] = action.contact_id
    activity = append_customer_event(
        db,
        customer_id=action.customer_id,
        event_type="sales_activity.logged",
        event_source="manual",
        event_title="记录销售活动",
        event_summary=normalized_summary,
        event_payload=payload,
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        source_ref_type="action",
        source_ref_id=str(action.id),
        actor_user_id=completed_by,
    )
    completion = dict((action.feedback_json or {}).get("completion") or {})
    completion["activity_event_id"] = activity.id
    action.feedback_json = {
        **dict(action.feedback_json or {}),
        "completion": completion,
    }
    db.flush()
    return action


def activate_customer_from_order(db: Session, order_id: int) -> bool:
    candidate = db.get(CustomerOrder, order_id)
    if candidate is None:
        raise CustomerWorkflowNotFound("ORDER_NOT_FOUND")
    account = _account_for_update(db, candidate.customer_id)
    order = db.query(CustomerOrder).filter(
        CustomerOrder.id == order_id
    ).with_for_update().one_or_none()
    if order is None:
        raise CustomerWorkflowNotFound("ORDER_NOT_FOUND")
    source = db.get(CustomerSourceRecord, order.source_record_id)
    if source is None or source.customer_id != order.customer_id:
        raise CustomerWorkflowConflict("ORDER_SOURCE_INVALID")
    before = account.relationship_stage
    occurred = (
        datetime.combine(order.account_date, datetime_time.min)
        if order.account_date is not None
        else source.occurred_at or order.synced_at
    )
    historical = (
        before == "inactive"
        and occurred <= account.relationship_stage_changed_at
    )
    append_customer_event(
        db,
        customer_id=order.customer_id,
        event_type="order.placed",
        event_source=order.source_system,
        event_title="客户订单已同步",
        event_summary=order.order_no or order.external_order_id,
        event_payload={
            "is_valid_business_order": bool(order.is_valid_business_order),
            "historical_replay": historical,
        },
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        source_ref_type="order",
        source_ref_id=str(order.id),
        target_relationship_stage=(
            "active_customer" if order.is_valid_business_order else None
        ),
        transition_trigger=(
            "historical_order_replay"
            if order.is_valid_business_order and historical
            else "valid_order"
            if order.is_valid_business_order
            else None
        ),
    )
    db.flush()
    return before != account.relationship_stage


def supersede_related_proposals(
    db: Session,
    *,
    executing_proposal_id: int,
    expected_execution_idempotency_key: str,
) -> list[CustomerChangeProposal]:
    executing = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.id == executing_proposal_id
    ).with_for_update().one_or_none()
    if executing is None:
        raise CustomerWorkflowNotFound("CHANGE_PROPOSAL_NOT_FOUND")
    if executing.action_type not in {"merge", "split"}:
        raise CustomerWorkflowError("CHANGE_PROPOSAL_ACTION_INVALID")
    stored_key = executing.execution_idempotency_key or ""
    expected_key = expected_execution_idempotency_key or ""
    if (
        not stored_key
        or not expected_key
        or not secrets.compare_digest(stored_key, expected_key)
    ):
        raise CustomerWorkflowConflict("CHANGE_PROPOSAL_EXECUTION_KEY_MISMATCH")
    if executing.status == "executed":
        return []
    if executing.status != "approved":
        raise CustomerWorkflowConflict("CHANGE_PROPOSAL_NOT_APPROVED")
    if (
        not executing.approved_action_hash
        or not secrets.compare_digest(
            executing.approved_action_hash,
            executing.action_hash,
        )
        or executing.expires_at <= beijing_now()
    ):
        raise CustomerWorkflowConflict("CHANGE_PROPOSAL_APPROVAL_INVALID")
    payload = executing.payload_json or {}
    if executing.action_type == "merge":
        if executing.target_customer_id is None:
            raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
        customer_ids = {executing.customer_id, executing.target_customer_id}
        if payload.get("keep_customer_id") not in customer_ids:
            raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
        if payload.get("proposal_redirects") or payload.get("redirected_proposal_ids"):
            raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
        redirected_proposal_ids: set[int] = set()
    else:
        declared_customers = payload.get("new_customer_ids")
        declared_redirects = payload.get("proposal_redirects", [])
        if (
            not isinstance(declared_customers, list)
            or not declared_customers
            or any(type(item) is not int or item <= 0 for item in declared_customers)
            or not isinstance(declared_redirects, list)
            or "redirected_proposal_ids" in payload
        ):
            raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
        customer_ids = {executing.customer_id, *declared_customers}
        if (
            executing.target_customer_id is not None
            and executing.target_customer_id not in customer_ids
        ):
            raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
        existing_customers = db.query(CustomerAccount.id).filter(
            CustomerAccount.id.in_(customer_ids),
            CustomerAccount.record_status == "active",
        ).all()
        if {row.id for row in existing_customers} != customer_ids:
            raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
        redirect_plan: dict[int, tuple[int, int]] = {}
        for item in declared_redirects:
            if (
                not isinstance(item, Mapping)
                or set(item) != {
                    "proposal_id",
                    "target_customer_id",
                    "target_profile_version_id",
                }
                or any(type(item[key]) is not int or item[key] <= 0 for key in item)
                or item["target_customer_id"] not in customer_ids
                or item["proposal_id"] in redirect_plan
            ):
                raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
            redirect_plan[item["proposal_id"]] = (
                item["target_customer_id"],
                item["target_profile_version_id"],
            )
        redirected_proposal_ids = set(redirect_plan)
        if redirected_proposal_ids:
            redirects = db.query(CustomerChangeProposal).filter(
                CustomerChangeProposal.id.in_(redirected_proposal_ids),
                CustomerChangeProposal.status.in_(PROPOSAL_OPEN_STATUSES),
            ).with_for_update().all()
            if {row.id for row in redirects} != redirected_proposal_ids:
                raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
            for redirect in redirects:
                target_customer_id, target_profile_version_id = redirect_plan[
                    redirect.id
                ]
                profile = db.query(CustomerProfileVersion.id).filter(
                    CustomerProfileVersion.id == target_profile_version_id,
                    CustomerProfileVersion.customer_id == target_customer_id,
                ).one_or_none()
                if (
                    profile is None
                    or redirect.customer_id != target_customer_id
                    or redirect.profile_version_id != target_profile_version_id
                ):
                    raise CustomerWorkflowConflict("CHANGE_PROPOSAL_SCOPE_INVALID")
                if (
                    redirect.status == "approved"
                    or redirect.approved_action_hash is not None
                    or redirect.decided_by is not None
                    or redirect.decided_at is not None
                ):
                    raise CustomerWorkflowConflict(
                        "CHANGE_PROPOSAL_REDIRECT_APPROVAL_STALE"
                    )
    excluded = {executing_proposal_id, *redirected_proposal_ids}
    rows = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.id.notin_(excluded),
        CustomerChangeProposal.status.in_(PROPOSAL_OPEN_STATUSES),
        or_(
            CustomerChangeProposal.customer_id.in_(customer_ids),
            CustomerChangeProposal.target_customer_id.in_(customer_ids),
        ),
    ).with_for_update().all()
    now = beijing_now()
    for row in rows:
        row.status = "superseded"
        row.updated_at = now
    db.flush()
    return rows


__all__ = [
    "CustomerWorkflowConflict",
    "CustomerWorkflowError",
    "CustomerWorkflowNotFound",
    "QualificationWorkflowResult",
    "activate_customer_from_order",
    "append_opportunity_event",
    "assign_customer",
    "claim_public_pool_customer",
    "complete_action",
    "create_action",
    "orchestrate_qualification_review",
    "supersede_related_proposals",
    "transfer_primary_owner",
    "transition_opportunity",
    "upsert_opportunity",
]
