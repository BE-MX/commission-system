"""Human-confirmed recipient preparation; public discovery never implies consent or validity."""

import hashlib
import json
import logging
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.time import beijing_now
from app.customer.access_service import CustomerAccess, apply_record_access
from app.customer.models import CustomerAccount, CustomerContact, CustomerContactPoint, CustomerContactRelationship, CustomerFact, CustomerSourceRecord, CustomerSuppressionRegistry
from app.mail_outreach.errors import bad_request, conflict, forbidden, not_found
from app.mail_outreach.schemas import RecipientPrepareRequest
from app.sales_automation import public_pool_service


logger = logging.getLogger(__name__)

def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def prepare_recipient(db: Session, access: CustomerAccess, user: dict, payload) -> dict:
    data = payload if isinstance(payload, RecipientPrepareRequest) else RecipientPrepareRequest.model_validate(payload)
    actor = int(user["sub"])
    if actor != access.actor_user_id or not access.allows_classification("personal_contact"):
        raise forbidden("当前用户无权维护个人联系资料")
    email = data.email.casefold().strip()
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email) or any(ord(c) < 32 for c in email):
        raise bad_request("邮箱格式不正确", error_code="invalid_email")
    try:
        ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise bad_request("请输入有效 IANA 时区", error_code="invalid_timezone") from exc
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", data.language_tag):
        raise bad_request("语言代码不正确", error_code="invalid_language")
    account = db.query(CustomerAccount).filter(CustomerAccount.id == access.customer_id, CustomerAccount.record_status == "active").with_for_update().one_or_none()
    if account is None:
        raise not_found()
    now = beijing_now()
    matches = db.query(CustomerContactPoint).filter(CustomerContactPoint.point_type == "email", CustomerContactPoint.normalized_value == email).with_for_update().all()
    # Never resurrect another occurrence of an opted-out/bounced address.
    if any(p.contactability_status in ("opted_out", "bounced", "blocked") or p.verification_status in ("invalid", "disputed") for p in matches):
        raise conflict("该邮箱已有禁止联系或无效记录，请先处理限制", error_code="recipient_suppressed")
    suppression = db.query(CustomerSuppressionRegistry.id).filter(
        CustomerSuppressionRegistry.status == "active", CustomerSuppressionRegistry.effective_at <= now,
        or_(CustomerSuppressionRegistry.mapped_contact_point_id.in_([p.id for p in matches]),
            CustomerSuppressionRegistry.mapped_customer_id == account.id,
            # Unmapped HMAC entries cannot safely be disproved without the registry key.
            (CustomerSuppressionRegistry.identifier_type.in_(("email", "domain"))) & (CustomerSuppressionRegistry.mapping_status != "mapped")),
    ).first()
    if suppression or public_pool_service.is_development_denied(db, account.id, "channel", "email"):
        raise conflict("存在生效中的联系限制，须先核实抑制记录", error_code="recipient_suppressed")
    fact = None
    source_classification = "personal_contact"
    source_visibility = "customer_team"
    if data.source_fact_id:
        fact = apply_record_access(db.query(CustomerFact).filter(CustomerFact.id == data.source_fact_id), CustomerFact, access, logical_object_type="fact").one_or_none()
        if fact is None:
            raise not_found("联系依据不存在或无权访问")
        if fact.fact_key != "research.source.business_contact":
            raise bad_request("请选择公开商业联系事实作为依据", error_code="invalid_recipient_source")
        if fact.visibility_scope == "management":
            source_visibility = "management"
        if fact.verification_status in ("rejected", "disputed", "superseded") or fact.effective_to or (fact.expires_at and fact.expires_at <= now):
            raise bad_request("联系依据已失效", error_code="invalid_recipient_source")
        if email not in json.dumps(fact.value_json, ensure_ascii=False).casefold():
            raise bad_request("所选事实不包含该邮箱", error_code="invalid_recipient_source")
        if fact.source_record_id:
            source = apply_record_access(db.query(CustomerSourceRecord).filter(CustomerSourceRecord.id == fact.source_record_id), CustomerSourceRecord, access, logical_object_type="source_record").one_or_none()
            if source is None:
                raise not_found("联系信源不存在或无权访问")
            source_classification = source.data_classification
            if source.visibility_scope == "management":
                source_visibility = "management"
    # Direct conversations and business cards have no URL; the explicit human
    # verification basis remains mandatory and is retained in the source record.
    if data.source_url:
        parsed = urlsplit(data.source_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise bad_request("邮箱来源必须是无凭据的 HTTP(S) 链接", error_code="invalid_recipient_source")
    relationship = None
    point = None
    for candidate in matches:
        relation = db.query(CustomerContactRelationship).filter(CustomerContactRelationship.customer_id == account.id, CustomerContactRelationship.contact_id == candidate.contact_id, CustomerContactRelationship.effective_to.is_(None), CustomerContactRelationship.verification_status.in_(("identified", "verified"))).first()
        if relation:
            if candidate.data_classification not in access.allowed_classifications():
                raise not_found()
            if candidate.source_record_id:
                existing_source = apply_record_access(db.query(CustomerSourceRecord).filter(CustomerSourceRecord.id == candidate.source_record_id), CustomerSourceRecord, access, logical_object_type="source_record").one_or_none()
                if existing_source is None:
                    raise not_found("已有联系信源不存在或无权访问")
                if existing_source.data_classification == "restricted_internal":
                    source_classification = "restricted_internal"
                if existing_source.visibility_scope == "management":
                    source_visibility = "management"
            point, relationship = candidate, relation
            break
    if matches and point is None:
        raise conflict("该邮箱已有其他主体记录，需先确认归属，避免重复建档", error_code="recipient_duplicate")
    contact = db.get(CustomerContact, point.contact_id) if point else None
    if contact and contact.record_status != "active":
        raise conflict("该联系人已停用，需先确认身份", error_code="recipient_duplicate")
    if contact:
        other_relationship = db.query(CustomerContactRelationship.id).filter(CustomerContactRelationship.contact_id == contact.id, CustomerContactRelationship.customer_id != account.id, CustomerContactRelationship.effective_to.is_(None)).first()
        if other_relationship:
            raise conflict("联系人关联多个客户，请通过联系人治理入口维护", error_code="recipient_duplicate")
    classification = "restricted_internal" if ((point and point.data_classification == "restricted_internal") or (fact and fact.data_classification == "restricted_internal") or source_classification == "restricted_internal") else "personal_contact"
    provenance = {"email": email, "display_name": data.display_name, "source_fact_id": data.source_fact_id, "source_url": data.source_url, "verification_basis": data.verification_basis, "verified": data.verified, "contact_allowed": data.contact_allowed, "actor_user_id": actor, "language_tag": data.language_tag, "timezone": data.timezone, "country_code": data.country_code}
    provenance["data_classification"] = classification
    provenance["visibility_scope"] = source_visibility
    source_key = _digest([account.id, email, "recipient_prepare"])
    content_hash = _digest(provenance)
    source = db.query(CustomerSourceRecord).filter(CustomerSourceRecord.external_record_key_hash == source_key, CustomerSourceRecord.content_hash == content_hash).one_or_none()
    if source is None:
        source = CustomerSourceRecord(customer_id=account.id, source_system="manual", source_account_key="internal", authority_level="first_party", source_entity_type="contact", external_record_id=source_key, external_record_key_hash=source_key, source_url=data.source_url, data_classification=classification, visibility_scope=source_visibility, classification_reason="Human-entered recipient identity and verification basis", payload_schema_version="mail_recipient_v1", payload_json=provenance, content_hash=content_hash, captured_at=now, occurred_at=now, processing_status="processed")
        db.add(source)
        db.flush()
    if contact is None:
        contact = CustomerContact(display_name=data.display_name, identity_status="identified", confidence=1, confidence_method_version="human_confirmed_v1", confidence_components_json={"manual_confirmation": True}, record_status="active", created_by=actor)
        db.add(contact)
        db.flush()
        relationship = CustomerContactRelationship(customer_id=account.id, contact_id=contact.id, relationship_type="other", buying_role="unknown", verification_status="identified", confidence=1, confidence_method_version="human_confirmed_v1", confidence_components_json={"manual_confirmation": True}, source_fact_id=data.source_fact_id, relationship_fingerprint=_digest([account.id, contact.id, "recipient_prepare"]), effective_from=now, created_by=actor, updated_by=actor)
        point = CustomerContactPoint(contact_id=contact.id, point_type="email", raw_value=email, normalized_value=email, email_domain_type="unknown", verification_status="unknown", contactability_status="unknown", is_primary=True, data_classification="personal_contact", point_fingerprint=_digest([contact.id, "email", email]), first_seen_at=now, last_seen_at=now, created_by=actor)
        db.add_all([relationship, point])
    contact.display_name = data.display_name
    contact.default_language = data.language_tag
    contact.timezone = data.timezone
    contact.country_code = data.country_code.upper()
    contact.updated_by = actor
    point.source_record_id = source.id
    # Existing personal identity stays protected even when the email itself is public.
    point.data_classification = classification
    point.verification_status = "valid" if data.verified else "unknown"
    point.verified_at = now if data.verified else None
    point.contactability_status = "allowed" if data.contact_allowed else "unknown"
    point.contactability_reason_code = "verified" if data.contact_allowed else "unknown"
    point.contactability_source = "manual"
    point.contactability_reviewed_by = actor
    point.contactability_effective_at = now
    point.last_seen_at = now
    point.updated_by = actor
    account.profile_input_seq = int(account.profile_input_seq or 0) + 1
    account.updated_at = now
    db.flush()
    result = {"customer_id": account.id, "contact_id": contact.id, "contact_point_id": point.id, "email": point.normalized_value, "verification_status": point.verification_status, "contactability_status": point.contactability_status}
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Recipient preparation transaction failed")
        print("[mail_outreach] Recipient preparation transaction failed", flush=True)
        raise
    return result
