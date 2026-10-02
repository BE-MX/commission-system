"""触达安全快照：生成/审批共用的客户证据视图。

在 app.customer.outreach_service.get_outreach_context 的基础上补齐：
客户/联系人两级语言、时区、国家，联系人身份与采购角色，事实正文，
以及每个邮箱点的资格快评（eligible + missing[]）。
鉴权模式沿用：入参为已完成 require_customer_access 的 CustomerAccess。
"""

import json
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now
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
from app.mail_outreach.errors import not_found
from app.sales_automation import public_pool_service

# 联系人关系只采纳当前有效且已识别/已核验的（与 outreach_service 口径一致）
_RELATIONSHIP_OK_STATUSES = ("identified", "verified")


def _point_quick_missing(
    point: CustomerContactPoint,
    *,
    contact: CustomerContact | None,
    customer: CustomerAccount,
    suppressed: bool,
    customer_suppressed: bool,
) -> list[str]:
    """联系点级资格快评缺项；与 eligibility_service 的规则编码保持一致。"""
    missing: list[str] = []
    if not ((contact and contact.timezone) or customer.timezone):
        missing.append("timezone")
    if not ((contact and contact.default_language) or customer.default_language):
        missing.append("language")
    if point.verification_status != "valid":
        missing.append("email_verification")
    if point.contactability_status != "allowed":
        missing.append("contactability")
    if suppressed or customer_suppressed:
        missing.append("suppression")
    return missing


def build_outreach_snapshot(db: Session, access: CustomerAccess, user: dict | None = None) -> dict:
    """组装触达安全快照；所有查询过 access.allowed_classifications() 投影。"""
    customer_id = access.customer_id
    customer = db.query(CustomerAccount).filter(CustomerAccount.id == customer_id).one_or_none()
    if customer is None:
        raise not_found("客户不存在")

    profile = None
    if customer.current_profile_version_id is not None:
        profile = db.query(CustomerProfileVersion).filter(
            CustomerProfileVersion.id == customer.current_profile_version_id,
            CustomerProfileVersion.customer_id == customer.id,
        ).one_or_none()

    relationships = db.query(CustomerContactRelationship).filter(
        CustomerContactRelationship.customer_id == customer.id,
        CustomerContactRelationship.effective_to.is_(None),
        CustomerContactRelationship.verification_status.in_(_RELATIONSHIP_OK_STATUSES),
    ).all()
    rel_by_contact = {row.contact_id: row for row in relationships}
    contact_ids = sorted(rel_by_contact)
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
        row[0] for row in db.query(
            CustomerSuppressionRegistry.mapped_contact_point_id,
        ).filter(
            CustomerSuppressionRegistry.mapped_contact_point_id.in_(email_point_ids),
            CustomerSuppressionRegistry.status == "active",
            CustomerSuppressionRegistry.effective_at <= beijing_now(),
        ).all()
    } if email_point_ids else set()
    customer_suppressed = public_pool_service.is_development_denied(
        db, customer.id, "channel", "email",
    )

    candidate_facts = apply_record_access(
        db.query(CustomerFact).filter(
            CustomerFact.fact_key == "research.source.business_contact",
            CustomerFact.verification_status.notin_(("rejected", "disputed", "superseded")),
            CustomerFact.effective_to.is_(None),
            or_(CustomerFact.expires_at.is_(None), CustomerFact.expires_at > beijing_now()),
        ), CustomerFact, access, logical_object_type="fact",
    ).all()
    fact_ids = sorted(set((profile.evidence_fact_ids or []) if profile else []) | {fact.id for fact in candidate_facts})
    fact_query = apply_record_access(
        db.query(CustomerFact).filter(CustomerFact.id.in_(fact_ids), CustomerFact.verification_status.notin_(("rejected", "disputed", "superseded")), CustomerFact.effective_to.is_(None), or_(CustomerFact.expires_at.is_(None), CustomerFact.expires_at > beijing_now())),
        CustomerFact,
        access, logical_object_type="fact",
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
        access, logical_object_type="source_record",
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

    visible_contact_ids = {point.contact_id for point in email_points}
    contacts = {key: value for key, value in contacts.items() if key in visible_contact_ids}
    points_by_contact: dict[int, list] = {}
    for point in email_points:
        contact = contacts.get(point.contact_id)
        suppressed = point.id in suppressed_point_ids
        missing = _point_quick_missing(
            point, contact=contact, customer=customer,
            suppressed=suppressed, customer_suppressed=customer_suppressed,
        )
        points_by_contact.setdefault(point.contact_id, []).append({
            "contact_point_id": point.id,
            "email": point.normalized_value,
            "verification_status": point.verification_status,
            "contactability_status": point.contactability_status,
            "suppressed": suppressed,
            "verified_at": point.verified_at.isoformat() if point.verified_at else None,
            "eligible": not missing,
            "missing": missing,
        })

    visible_fact_ids = {fact.id for fact in facts}
    recipient_candidates = []
    for fact in candidate_facts:
        if fact.id not in visible_fact_ids:
            continue
        value = fact.value_json or {}
        text = json.dumps(value, ensure_ascii=False)
        for email in sorted(set(re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))):
            recipient_candidates.append({"fact_id": fact.id, "source_fact_id": fact.id, "email": email,
                "display_name": value.get("display_name") or value.get("name") or "",
                "value_json": value, "verification_status": fact.verification_status,
                "source_url": sources[fact.source_record_id].source_url if fact.source_record_id in sources else None,
                "language_tag": customer.default_language, "timezone": customer.timezone, "country_code": customer.primary_country_code})
    return {
        "customer_id": customer.id,
        "display_name": customer.display_name,
        "canonical_company_name": customer.canonical_company_name,
        "record_status": customer.record_status,
        "identity_status": customer.identity_status,
        "default_language": customer.default_language,
        "timezone": customer.timezone,
        "primary_country_code": customer.primary_country_code,
        "current_profile_version_id": customer.current_profile_version_id,
        "customer_level_suppressed": customer_suppressed,
        "contacts": [{
            "contact_id": contact.id,
            "display_name": contact.display_name,
            "canonical_name": contact.canonical_name,
            "default_language": contact.default_language,
            "timezone": contact.timezone,
            "country_code": contact.country_code,
            "job_title": rel_by_contact[contact.id].job_title,
            "buying_role": rel_by_contact[contact.id].buying_role,
            "relationship_type": rel_by_contact[contact.id].relationship_type,
            "points": points_by_contact.get(contact.id, []),
        } for contact in (contacts[cid] for cid in sorted(contacts))],
        "evidence": [{
            "fact_id": fact.id,
            "fact_key": fact.fact_key,
            "value_json": fact.value_json,
            "fact_fingerprint": fact.fact_fingerprint,
            "verification_status": fact.verification_status,
            "source_record_id": fact.source_record_id,
            "source_url": sources.get(fact.source_record_id).source_url
            if fact.source_record_id in sources else None,
        } for fact in facts],
        "contact_candidates": recipient_candidates,
        "knowledge_items": _company_knowledge(db, user) if user else [],
        "captured_at": beijing_now().isoformat(),
    }


__all__ = ["build_outreach_snapshot"]


def _company_knowledge(db: Session, user: dict) -> list[dict]:
    """Only active company libraries and their current published revisions pass ACL."""
    from app.knowledge import access as knowledge_access
    from app.knowledge.models import KnowledgeDocument, KnowledgeLibrary, KnowledgeRevision
    if not knowledge_access.has_platform(user, "knowledge:read"):
        return []
    libraries = db.query(KnowledgeLibrary).filter(KnowledgeLibrary.category == "company", KnowledgeLibrary.status == "active", KnowledgeLibrary.deleted_at.is_(None)).all()
    allowed = [library.id for library in libraries if knowledge_access.can(db, user, library.id, "read")]
    if not allowed:
        return []
    rows = db.query(KnowledgeDocument, KnowledgeRevision).join(KnowledgeRevision, (KnowledgeRevision.id == KnowledgeDocument.published_revision_id) & (KnowledgeRevision.document_id == KnowledgeDocument.id)).filter(KnowledgeDocument.library_id.in_(allowed), KnowledgeDocument.deleted_at.is_(None), KnowledgeDocument.node_type == "document").order_by(KnowledgeDocument.id).limit(20).all()
    return [{"knowledge_version_id": revision.id, "document_id": doc.id, "library_id": doc.library_id, "title": revision.title, "content_text": revision.content_text[:12000]} for doc, revision in rows]
