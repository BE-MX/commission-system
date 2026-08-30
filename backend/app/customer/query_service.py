"""Ark-only, SQL-scoped reads for the human Customer Hub."""

from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.customer.access_service import (
    CLASSIFICATION_ORDER,
    VISIBILITY_ORDER,
    CustomerAccess,
    apply_customer_scope,
    apply_record_access,
    require_customer_access,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerEvent,
    CustomerListProjection,
    CustomerOpportunity,
    CustomerProfileVersion,
    CustomerResearchTask,
)


BEIJING = timezone(timedelta(hours=8))
CUSTOMER_READ = {"customer:read", "customer:read_all"}
RESEARCH_READ = {"sales_automation:read", "customer:read_all"}
OPPORTUNITY_READ = {"customer_opportunity:read", "customer:read_all"}
ACTION_READ = {"customer_radar:read", "customer:read_all"}


def iso_beijing(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING)
    return value.astimezone(BEIJING).isoformat()


def _access(
    db: Session, customer_id: int, user: dict, *,
    read_permissions=CUSTOMER_READ, allow_public_pool=True,
) -> CustomerAccess:
    return require_customer_access(
        db,
        customer_id=customer_id,
        user=user,
        action_permissions=read_permissions,
        manage_permissions={"customer:admin"},
        allow_public_pool=allow_public_pool,
    )


def scoped_customer_query(
    db: Session, user: dict, *, read_permissions=CUSTOMER_READ,
    include_public_pool=True,
):
    return apply_customer_scope(
        db.query(CustomerAccount),
        user=user,
        read_permissions=read_permissions,
        include_public_pool=include_public_pool,
    )


def _has_primary(db: Session, customer_id: int) -> bool:
    return db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == customer_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first() is not None


def _summary(db: Session, row: CustomerAccount) -> dict:
    projection = db.get(CustomerListProjection, row.id)
    return {
        "customer_id": row.id,
        "customer_code": row.customer_code,
        "display_name": row.display_name,
        "canonical_company_name": row.canonical_company_name,
        "identity_status": row.identity_status,
        "relationship_stage": row.relationship_stage,
        "primary_country_code": row.primary_country_code,
        "profile_completeness": float(row.profile_completeness),
        "primary_industry": projection.primary_industry if projection else None,
        "primary_market": projection.primary_market if projection else None,
        "engagement_health": projection.engagement_health if projection else None,
        "is_public_pool": not _has_primary(db, row.id),
        "updated_at": iso_beijing(row.updated_at),
    }


def list_customers(db: Session, user: dict, *, page: int, page_size: int, keyword=None):
    query = scoped_customer_query(db, user)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(
            CustomerAccount.customer_code.ilike(pattern),
            CustomerAccount.display_name.ilike(pattern),
            CustomerAccount.canonical_company_name.ilike(pattern),
        ))
    total = query.count()
    rows = query.order_by(CustomerAccount.updated_at.desc(), CustomerAccount.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return [_summary(db, row) for row in rows], total


def get_customer(db: Session, user: dict, customer_id: int) -> dict:
    access = _access(db, customer_id, user)
    row = scoped_customer_query(db, user).filter(CustomerAccount.id == customer_id).one()
    data = _summary(db, row)
    data["access_scope"] = access.scope_kind
    if access.scope_kind == "public_pool":
        return data
    from app.insight.customer_profile_service import get_profile
    projection = get_profile(db, row.id, access=access)
    data["profile"] = projection["profile_json"] if projection else None
    data["profile_projection"] = projection["profile_projection"] if projection else "unavailable"
    annotations = apply_record_access(
        db.query(CustomerAnnotation),
        CustomerAnnotation,
        access,
        visibility_field="visibility",
        author_field="authored_by",
    ).filter(CustomerAnnotation.status == "active").all()
    data["annotations"] = [{
        "annotation_id": item.id,
        "type": item.annotation_type,
        "content": item.content_json,
        "visibility": item.visibility,
        "created_at": iso_beijing(item.created_at),
    } for item in annotations]
    return data


def list_timeline(db: Session, user: dict, customer_id: int, *, page, page_size):
    access = _access(db, customer_id, user)
    if access.scope_kind == "public_pool":
        query = db.query(CustomerEvent).filter(
            CustomerEvent.customer_id == customer_id,
            CustomerEvent.data_classification.in_(("public_business", "internal_business")),
            CustomerEvent.visibility_scope == "all_authorized",
        )
    else:
        query = apply_record_access(db.query(CustomerEvent), CustomerEvent, access)
    total = query.count()
    rows = query.order_by(CustomerEvent.occurred_at.desc(), CustomerEvent.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return [{
        "event_id": row.id,
        "event_type": row.event_type,
        "title": row.event_title,
        "summary": row.event_summary,
        "importance": row.importance,
        "occurred_at": iso_beijing(row.occurred_at),
    } for row in rows], total


def _scoped_ids(
    db: Session, user: dict, *, read_permissions=CUSTOMER_READ,
    include_public_pool: bool = True,
):
    return scoped_customer_query(
        db, user, read_permissions=read_permissions,
        include_public_pool=include_public_pool,
    ).with_entities(CustomerAccount.id)


def _research_limits(user: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    permissions = set(user.get("permissions") or [])
    roles = set(user.get("roles") or [])
    run = user.get("_agent_run") or None
    has_frozen_permissions = run is not None and "permissions_at_start" in run
    if has_frozen_permissions:
        permissions &= set(run.get("permissions_at_start") or [])
    classification = "restricted_internal"
    visibility = (
        "management"
        if ("super_admin" in roles and run is None)
        or "customer:read_all" in permissions
        else "customer_team"
    )
    if run is not None:
        run_classification = run.get("max_data_classification")
        if run_classification in CLASSIFICATION_ORDER:
            classification = min(
                classification, run_classification,
                key=CLASSIFICATION_ORDER.index,
            )
        run_visibility = run.get("max_visibility_scope")
        if run_visibility in VISIBILITY_ORDER:
            visibility = min(
                visibility, run_visibility, key=VISIBILITY_ORDER.index,
            )
    return (
        CLASSIFICATION_ORDER[:CLASSIFICATION_ORDER.index(classification) + 1],
        VISIBILITY_ORDER[:VISIBILITY_ORDER.index(visibility) + 1],
    )


def scoped_research_query(db: Session, user: dict):
    full_ids = _scoped_ids(
        db, user, read_permissions=RESEARCH_READ, include_public_pool=False,
    )
    all_ids = _scoped_ids(
        db, user, read_permissions=RESEARCH_READ, include_public_pool=True,
    )
    classifications, visibilities = _research_limits(user)
    return db.query(CustomerResearchTask).filter(or_(
        and_(
            CustomerResearchTask.customer_id.in_(full_ids),
            CustomerResearchTask.data_classification.in_(classifications),
            CustomerResearchTask.visibility_scope.in_(visibilities),
        ),
        and_(
            CustomerResearchTask.customer_id.in_(all_ids),
            CustomerResearchTask.customer_id.notin_(full_ids),
            CustomerResearchTask.data_classification.in_(("public_business", "internal_business")),
            CustomerResearchTask.visibility_scope == "all_authorized",
        ),
    ))


def serialize_research_task(row, access: CustomerAccess, *, include_content=False):
    public = access.scope_kind == "public_pool"
    result = {
        "research_task_id": row.id,
        "customer_id": row.customer_id,
        "task_type": row.task_type,
        "tier": row.tier,
        "task_status": row.task_status,
        "gate_status": row.gate_status,
        "result_review_status": row.result_review_status,
        "research_policy_version": row.research_policy_version,
        "result_schema_version": row.result_schema_version,
        "data_classification": row.data_classification,
        "visibility_scope": row.visibility_scope,
        "content_redacted": public or not include_content,
        "updated_at": iso_beijing(row.updated_at),
    }
    if not public:
        result.update({
            "source_ref_type": row.source_ref_type,
            "source_ref_id": row.source_ref_id,
            "attempt_count": row.attempt_count,
            "error_code": row.error_code,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": iso_beijing(row.reviewed_at),
            "started_at": iso_beijing(row.started_at),
            "finished_at": iso_beijing(row.finished_at),
            "created_at": iso_beijing(row.created_at),
        })
    if include_content and not public:
        result.update({
            "selection_reason": row.selection_reason or [],
            "input_snapshot": row.input_snapshot or {},
            "result_json": row.result_json,
            "research_summary": row.research_summary,
            "evidence_fact_ids": row.evidence_fact_ids or [],
        })
    return result


def list_research_tasks(db: Session, user: dict, *, page, page_size):
    query = scoped_research_query(db, user)
    total = query.count()
    rows = query.order_by(CustomerResearchTask.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [serialize_research_task(
        row, _access(
            db, row.customer_id, user, read_permissions=RESEARCH_READ,
        ),
    ) for row in rows], total


def get_research_task(db: Session, user: dict, task_id: int):
    row = scoped_research_query(db, user).filter(
        CustomerResearchTask.id == task_id,
    ).one_or_none()
    if row is None:
        raise LookupError("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")
    access = _access(
        db, row.customer_id, user, read_permissions=RESEARCH_READ,
    )
    return serialize_research_task(row, access, include_content=True)


def list_opportunities(db: Session, user: dict, *, page, page_size):
    query = db.query(CustomerOpportunity).filter(
        CustomerOpportunity.customer_id.in_(_scoped_ids(
            db, user, read_permissions=OPPORTUNITY_READ,
            include_public_pool=False,
        ))
    )
    total = query.count()
    rows = query.order_by(CustomerOpportunity.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [serialize_opportunity(row) for row in rows], total


def serialize_opportunity(row) -> dict:
    return {
        "opportunity_id": row.id,
        "customer_id": row.customer_id,
        "title": row.title,
        "status": row.status,
        "priority_level": row.priority_level,
        "owner_user_id": row.owner_user_id,
        "due_at": iso_beijing(row.due_at),
        "updated_at": iso_beijing(row.updated_at),
    }


def list_actions(db: Session, user: dict, *, page, page_size):
    query = db.query(CustomerAction).filter(
        CustomerAction.customer_id.in_(_scoped_ids(
            db, user, read_permissions=ACTION_READ,
            include_public_pool=False,
        ))
    )
    total = query.count()
    rows = query.order_by(CustomerAction.updated_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [serialize_action(row) for row in rows], total


def serialize_action(row) -> dict:
    return {
        "action_id": row.id,
        "customer_id": row.customer_id,
        "opportunity_id": row.opportunity_id,
        "action_type": row.action_type,
        "status": row.status,
        "priority": row.priority,
        "owner_user_id": row.owner_user_id,
        "due_at": iso_beijing(row.due_at),
        "updated_at": iso_beijing(row.updated_at),
    }
