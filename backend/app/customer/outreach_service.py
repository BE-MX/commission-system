"""Read-only Ark snapshot used by the trusted outreach confirmation operator."""

from sqlalchemy.orm import Session

from app.customer.access_service import CustomerAccess, apply_record_access
from app.customer.models import (
    CustomerAccount,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerFact,
    CustomerProfileVersion,
    CustomerSourceRecord,
    CustomerSuppressionRegistry,
)
from app.core.time import beijing_now
from app.sales_automation import public_pool_service, service


def get_outreach_context(db: Session, access: CustomerAccess) -> dict:
    customer_id = access.customer_id
    customer = db.query(CustomerAccount).filter(CustomerAccount.id == customer_id).one_or_none()
    if customer is None:
        raise service.NotFoundError("客户不存在")
    profile = None
    if customer.current_profile_version_id is not None:
        profile = db.query(CustomerProfileVersion).filter(
            CustomerProfileVersion.id == customer.current_profile_version_id,
            CustomerProfileVersion.customer_id == customer.id,
        ).one_or_none()

    relationships = db.query(CustomerContactRelationship).filter(
        CustomerContactRelationship.customer_id == customer.id,
        CustomerContactRelationship.effective_to.is_(None),
        CustomerContactRelationship.verification_status.in_(("identified", "verified")),
    ).all()
    contact_ids = sorted({row.contact_id for row in relationships})
    contacts = {
        row.id: row for row in db.query(CustomerContact).filter(
            CustomerContact.id.in_(contact_ids),
            CustomerContact.record_status == "active",
        ).all()
    } if contact_ids else {}
    email_points = db.query(CustomerContactPoint).filter(
        CustomerContactPoint.contact_id.in_(contacts),
        CustomerContactPoint.point_type == "email",
        CustomerContactPoint.data_classification.in_(access.allowed_classifications()),
    ).all() if contacts else []
    email_point_ids = [point.id for point in email_points]
    suppressed_point_ids = {
        row[0] for row in db.query(CustomerSuppressionRegistry.mapped_contact_point_id).filter(
        CustomerSuppressionRegistry.mapped_contact_point_id.in_(email_point_ids),
        CustomerSuppressionRegistry.status == "active",
        CustomerSuppressionRegistry.effective_at <= beijing_now(),
    ).all()
    } if email_point_ids else set()

    fact_ids = sorted(set(profile.evidence_fact_ids or [])) if profile else []
    fact_query = apply_record_access(
        db.query(CustomerFact).filter(CustomerFact.id.in_(fact_ids)),
        CustomerFact,
        access,
    ) if fact_ids else None
    facts = fact_query.order_by(CustomerFact.id).all() if fact_query is not None else []
    source_ids = sorted({
        source_id for source_id in (
            [row.source_record_id for row in facts]
            + [row.source_record_id for row in email_points]
        ) if source_id is not None
    })
    source_query = apply_record_access(
        db.query(CustomerSourceRecord).filter(CustomerSourceRecord.id.in_(source_ids)),
        CustomerSourceRecord,
        access,
    ) if source_ids else None
    sources = {
        row.id: row for row in source_query.all()
    } if source_query is not None else {}
    facts = [
        row for row in facts
        if row.source_record_id is None or row.source_record_id in sources
    ]
    email_points = [
        row for row in email_points
        if row.source_record_id is None or row.source_record_id in sources
    ]

    return {
        "customer_id": customer.id,
        "record_status": customer.record_status,
        "identity_status": customer.identity_status,
        "current_profile_version_id": customer.current_profile_version_id,
        "suppressed": public_pool_service.is_development_denied(
            db, customer.id, "channel", "email",
        ),
        "contacts": [{
            "contact_id": point.contact_id,
            "contact_point_id": point.id,
            "email": point.normalized_value,
            "email_status": point.verification_status,
            "contactability_status": point.contactability_status,
            "suppressed": point.id in suppressed_point_ids,
            "verified_at": point.verified_at.isoformat() if point.verified_at else None,
        } for point in email_points],
        "evidence": [{
            "fact_id": fact.id,
            "fact_fingerprint": fact.fact_fingerprint,
            "source_record_id": fact.source_record_id,
            "source_url": sources.get(fact.source_record_id).source_url
            if fact.source_record_id in sources else None,
        } for fact in facts],
    }


__all__ = ["get_outreach_context"]
