"""Governed customer lookup for Agent tools."""

from __future__ import annotations

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

from app.customer.access_service import (
    CLASSIFICATION_ORDER,
    CustomerAccessDenied,
    apply_customer_scope,
)
from app.customer.agent_query_service import ascending_id_page, finish_keyset_page, id_key
from app.customer.agent_tool_contract import MAX_LIST_BYTES, deny, envelope
from app.customer.logical_customer_service import logical_subject_matches_customer
from app.customer.models import (
    CustomerAccount,
    CustomerContactPoint,
    CustomerExternalIdentity,
    CustomerName,
)


_READ_PERMISSIONS = {"customer:read", "customer:read_all", "customer:admin"}


def search_customers(
    db: Session, *, user: dict, keyword: str | None = None,
    identifier_type: str | None = None, cursor: str | None = None, limit: int = 20,
) -> dict:
    try:
        query = apply_customer_scope(
            db.query(CustomerAccount), user=user, read_permissions=_READ_PERMISSIONS,
            include_public_pool=False,
        )
    except CustomerAccessDenied:
        deny()
    cleaned = (keyword or "").strip()
    if identifier_type:
        if identifier_type in {"email", "phone", "whatsapp", "website", "social", "domain"}:
            point_type = "website" if identifier_type == "domain" else identifier_type
            run_ceiling = (user.get("_agent_run") or {}).get(
                "max_data_classification", "restricted_internal",
            )
            if run_ceiling not in CLASSIFICATION_ORDER:
                run_ceiling = "internal_business"
            allowed = CLASSIFICATION_ORDER[:CLASSIFICATION_ORDER.index(run_ceiling) + 1]
            query = query.filter(exists().where(and_(
                CustomerContactPoint.point_type == point_type,
                CustomerContactPoint.normalized_value.ilike(
                    f"%{cleaned}%" if identifier_type == "domain" else cleaned,
                ),
                CustomerContactPoint.verification_status.notin_(("invalid", "disputed")),
                CustomerContactPoint.data_classification.in_(allowed),
                logical_subject_matches_customer(
                    CustomerContactPoint, "contact_point", CustomerAccount,
                ),
            )))
        else:
            query = query.filter(exists().where(and_(
                CustomerExternalIdentity.identifier_type == identifier_type,
                CustomerExternalIdentity.normalized_value == cleaned,
                CustomerExternalIdentity.status == "active",
                logical_subject_matches_customer(
                    CustomerExternalIdentity, "external_identity", CustomerAccount,
                ),
            )))
    elif cleaned:
        pattern = f"%{cleaned}%"
        names = db.query(CustomerName.customer_id).filter(
            CustomerName.normalized_name.ilike(pattern),
        )
        query = query.filter(or_(
            CustomerAccount.display_name.ilike(pattern),
            CustomerAccount.canonical_company_name.ilike(pattern),
            CustomerAccount.customer_code.ilike(pattern),
            CustomerAccount.id.in_(names),
        ))
    filters = {"keyword": cleaned, "identifier_type": identifier_type}
    rows, has_more = ascending_id_page(
        query, CustomerAccount.id, user=user, customer_id=None, filters=filters,
        profile_version=None, cursor=cursor, limit=limit,
    )
    result = envelope(profile_version=None, data_as_of=None, items=[{
        "customer_id": row.id, "customer_code": row.customer_code,
        "display_name": row.display_name,
        "canonical_company_name": row.canonical_company_name,
        "entity_type": row.entity_type, "identity_status": row.identity_status,
        "relationship_stage": row.relationship_stage,
    } for row in rows])
    return finish_keyset_page(
        result, rows, max_bytes=MAX_LIST_BYTES, has_more=has_more,
        key_for_row=id_key, user=user, customer_id=None, filters=filters,
        profile_version=None,
    )
