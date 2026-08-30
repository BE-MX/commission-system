"""Read-only customer profile projection for insight consumers.

The unified customer account and its immutable profile version are the only source of
truth.  This module deliberately has no name-based matching or profile event writer.
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.customer.models import (
    CustomerAccount,
    CustomerAgentContext,
    CustomerAssignment,
    CustomerListProjection,
    CustomerOpportunity,
    CustomerProfileVersion,
)


def _profile_row(db: Session, account: CustomerAccount, *, access=None) -> dict:
    version = None
    if account.current_profile_version_id is not None:
        version = db.query(CustomerProfileVersion).filter(
            CustomerProfileVersion.id == account.current_profile_version_id,
            CustomerProfileVersion.customer_id == account.id,
        ).one_or_none()
    projection = db.get(CustomerListProjection, account.id)
    primary = db.query(CustomerAssignment).filter(
        CustomerAssignment.customer_id == account.id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).one_or_none()
    restricted_profile_allowed = (
        access is not None
        and access.can_manage
        and access.max_data_classification == "restricted_internal"
        and access.allows_visibility("management")
    )
    if version is None:
        profile_json = {}
        profile_projection = "unavailable"
    elif restricted_profile_allowed:
        profile_json = dict(version.profile_json or {})
        profile_projection = "customer_profile_v1"
    elif access is not None and (
        not access.allows_classification("internal_business")
        or not access.allows_visibility("customer_team")
    ):
        profile_json = {}
        profile_projection = "public_business"
    else:
        context = db.get(CustomerAgentContext, account.id)
        profile_json = (
            dict(context.context_json or {})
            if context is not None
            and context.profile_version_id == version.id
            and context.max_data_classification == "internal_business"
            else {}
        )
        profile_projection = "customer_context_v1"
    if profile_projection == "public_business":
        return {
            "customer_id": account.id,
            "profile_json": {},
            "profile_projection": "public_business",
            "redacted": True,
        }
    return {
        "customer_id": account.id,
        "customer_code": account.customer_code,
        "display_name": account.display_name,
        "canonical_company_name": account.canonical_company_name,
        "entity_type": account.entity_type,
        "identity_status": account.identity_status,
        "relationship_stage": account.relationship_stage,
        "record_status": account.record_status,
        "primary_owner_user_id": primary.user_id if primary is not None else None,
        "profile_version_id": version.id if version is not None else None,
        "profile_version_no": version.version_no if version is not None else None,
        "profile_json": profile_json,
        "profile_projection": profile_projection,
        "profile_compiled_at": version.compiled_at if version is not None else None,
        "profile_data_as_of": version.data_as_of if version is not None else None,
        "commercial_value_score": (
            projection.commercial_value_score if projection is not None else 0
        ),
        "data_quality_score": projection.data_quality_score if projection is not None else 0,
        "open_opportunity_count": (
            projection.open_opportunity_count if projection is not None else 0
        ),
        "next_action_at": projection.next_action_at if projection is not None else None,
    }


def get_profile(db: Session, customer_id: int, *, access=None) -> dict | None:
    account = db.get(CustomerAccount, customer_id)
    if account is None:
        return None
    return _profile_row(db, account, access=access)


def get_profile_by_opportunity(db: Session, opportunity_id: int) -> dict | None:
    opportunity = db.get(CustomerOpportunity, opportunity_id)
    if opportunity is None:
        return None
    return get_profile(db, opportunity.customer_id)


def list_profiles(
    db: Session,
    owner_user_id: int,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    query = db.query(CustomerAccount).join(
        CustomerAssignment,
        CustomerAssignment.customer_id == CustomerAccount.id,
    ).filter(
        CustomerAssignment.user_id == owner_user_id,
        CustomerAssignment.assignment_role == "primary",
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    )
    if status:
        query = query.filter(CustomerAccount.record_status == status)
    else:
        query = query.filter(CustomerAccount.record_status == "active")
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(
            CustomerAccount.display_name.ilike(pattern),
            CustomerAccount.canonical_company_name.ilike(pattern),
            CustomerAccount.customer_code.ilike(pattern),
        ))
    total = query.count()
    accounts = (
        query.order_by(CustomerAccount.updated_at.desc(), CustomerAccount.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_profile_row(db, account) for account in accounts],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


__all__ = ["get_profile", "get_profile_by_opportunity", "list_profiles"]
