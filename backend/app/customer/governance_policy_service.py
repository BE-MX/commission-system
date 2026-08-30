"""Deterministic executors for approved customer policy proposals."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.contracts import FACT_REGISTRY
from app.customer.fact_service import (
    HumanReviewEvidence,
    append_customer_event,
    append_fact,
    link_fact_evidence,
)
from app.customer.governance_policy_contract import (
    RISK_CONFIRMED_FACT_KEYS,
    RISK_SOURCE_FACT_KEYS,
    ConfirmMaterialRiskPayload,
    RemoveDncPayload,
    SetDncPayload,
    canonical_value_hash,
    parse_confirm_material_risk,
    parse_remove_dnc,
    parse_set_dnc,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAgentContext,
    CustomerAnnotation,
    CustomerChangeProposal,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerEvent,
    CustomerFact,
    CustomerProfileVersion,
    CustomerSuppressionRegistry,
)
from app.customer.proposal_service import canonical_action_hash


class GovernancePolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GovernanceExecutionResult:
    proposal: CustomerChangeProposal
    annotation_id: int | None = None
    confirmed_fact_id: int | None = None
    contactability_still_blocked: bool | None = None
    remaining_blockers: tuple[str, ...] = ()


def _lock_proposal(db: Session, proposal_id: int) -> CustomerChangeProposal:
    row = db.query(CustomerChangeProposal).filter(
        CustomerChangeProposal.id == proposal_id,
    ).with_for_update().one_or_none()
    if row is None:
        raise GovernancePolicyError("PROPOSAL_NOT_FOUND")
    return row


def _require_human(db: Session, actor_user_id: int) -> None:
    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise GovernancePolicyError("GOVERNANCE_ACTOR_INVALID")
    user = db.query(ArkUser.id).filter(
        ArkUser.id == actor_user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    if user is None:
        raise GovernancePolicyError("GOVERNANCE_ACTOR_INVALID")


def _validate_approval(row: CustomerChangeProposal) -> None:
    current_hash = canonical_action_hash(
        action_type=row.action_type,
        customer_id=row.customer_id,
        target_customer_id=row.target_customer_id,
        payload_json=dict(row.payload_json or {}),
        profile_version_id=row.profile_version_id,
        evidence_fact_ids=list(row.evidence_fact_ids or []),
    )
    if (
        row.status != "approved"
        or not row.approved_action_hash
        or not secrets.compare_digest(row.action_hash, current_hash)
        or not secrets.compare_digest(row.approved_action_hash, row.action_hash)
    ):
        raise GovernancePolicyError("PROPOSAL_APPROVAL_INVALID")
    if row.expires_at <= beijing_now():
        raise GovernancePolicyError("PROPOSAL_EXPIRED")
    if row.target_customer_id is not None:
        raise GovernancePolicyError("GOVERNANCE_TARGET_INVALID")


def _lock_live_basis(
    db: Session,
    row: CustomerChangeProposal,
    payload: SetDncPayload | RemoveDncPayload | ConfirmMaterialRiskPayload,
) -> CustomerAccount:
    if (
        payload.customer_id != row.customer_id
        or payload.profile_version_id != row.profile_version_id
        or tuple(row.evidence_fact_ids or ()) != payload.evidence_fact_ids
    ):
        raise GovernancePolicyError("GOVERNANCE_PAYLOAD_STALE")
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == row.customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise GovernancePolicyError("GOVERNANCE_CUSTOMER_INVALID")
    if (
        account.current_profile_version_id != row.profile_version_id
        or int(account.profile_input_seq) != payload.expected_profile_input_seq
    ):
        raise GovernancePolicyError("GOVERNANCE_PROFILE_STALE")
    profile = db.query(CustomerProfileVersion.id).filter(
        CustomerProfileVersion.id == row.profile_version_id,
        CustomerProfileVersion.customer_id == row.customer_id,
        CustomerProfileVersion.input_seq == payload.expected_profile_input_seq,
    ).one_or_none()
    if profile is None:
        raise GovernancePolicyError("GOVERNANCE_PROFILE_STALE")
    now = beijing_now()
    fact_ids = set(payload.evidence_fact_ids)
    facts = db.query(CustomerFact).filter(
        CustomerFact.id.in_(fact_ids),
        CustomerFact.customer_id == row.customer_id,
        CustomerFact.verification_status.in_(("unverified", "candidate", "verified")),
        CustomerFact.effective_to.is_(None),
        or_(CustomerFact.effective_from.is_(None), CustomerFact.effective_from <= now),
        or_(CustomerFact.expires_at.is_(None), CustomerFact.expires_at > now),
    ).with_for_update().all()
    if {fact.id for fact in facts} != fact_ids or any(
        not FACT_REGISTRY.get(fact.fact_key)
        or not FACT_REGISTRY[fact.fact_key].supports_high_impact
        for fact in facts
    ):
        raise GovernancePolicyError("GOVERNANCE_EVIDENCE_STALE")
    return account


def _invalidate_profile(db: Session, account: CustomerAccount) -> None:
    account.current_profile_version_id = None
    account.profile_compiled_at = None
    account.data_as_of = None
    db.query(CustomerAgentContext).filter(
        CustomerAgentContext.customer_id == account.id,
    ).delete(synchronize_session=False)


def _scope_filter(scope_type: str, scope_ref_id: str | None):
    return and_(
        CustomerAnnotation.policy_scope_type == scope_type,
        CustomerAnnotation.policy_scope_ref_id.is_(None)
        if scope_ref_id is None
        else CustomerAnnotation.policy_scope_ref_id == scope_ref_id,
    )


def _remaining_contactability_blockers(db: Session, customer_id: int) -> tuple[str, ...]:
    blockers: set[str] = set()
    if db.query(CustomerSuppressionRegistry.id).filter(
        CustomerSuppressionRegistry.mapped_customer_id == customer_id,
        CustomerSuppressionRegistry.status == "active",
        CustomerSuppressionRegistry.effective_at <= beijing_now(),
    ).first() is not None:
        blockers.add("central_suppression")
    related_contacts = db.query(CustomerContactRelationship.contact_id).filter(
        CustomerContactRelationship.customer_id == customer_id,
        CustomerContactRelationship.effective_to.is_(None),
        CustomerContactRelationship.verification_status.in_(("identified", "verified")),
    )
    points = db.query(CustomerContactPoint.contactability_reason_code).filter(
        or_(
            CustomerContactPoint.customer_id == customer_id,
            CustomerContactPoint.contact_id.in_(related_contacts),
        ),
        or_(
            CustomerContactPoint.contactability_status.in_(("bounced", "opted_out", "blocked")),
            CustomerContactPoint.contactability_reason_code.in_((
                "hard_bounce", "recipient_opt_out", "manual_block", "invalid_address",
            )),
        ),
    ).all()
    for (reason,) in points:
        blockers.add(reason or "contact_point_blocked")
    return tuple(sorted(blockers))


def _replay_result(
    db: Session, row: CustomerChangeProposal,
) -> GovernanceExecutionResult:
    event_type = {
        "set_dnc": "policy.dnc_set",
        "remove_dnc": "policy.dnc_removed",
        "confirm_material_risk": "risk.material_confirmed",
    }.get(row.action_type)
    events = db.query(CustomerEvent).filter(
        CustomerEvent.customer_id == row.customer_id,
        CustomerEvent.event_type == event_type,
    ).all() if event_type else []
    event = next((
        item for item in events
        if (item.event_payload or {}).get("proposal_id") == row.id
    ), None)
    if event is None:
        raise GovernancePolicyError("GOVERNANCE_EXECUTION_RESULT_MISSING")
    payload = event.event_payload or {}
    blockers = tuple(payload.get("remaining_blockers") or ())
    return GovernanceExecutionResult(
        proposal=row,
        annotation_id=payload.get("annotation_id"),
        confirmed_fact_id=payload.get("confirmed_fact_id"),
        contactability_still_blocked=payload.get("contactability_still_blocked"),
        remaining_blockers=blockers,
    )


def _execute_set_dnc(
    db: Session, row: CustomerChangeProposal, payload: SetDncPayload,
    actor_user_id: int, account: CustomerAccount,
) -> GovernanceExecutionResult:
    existing = db.query(CustomerAnnotation.id).filter(
        CustomerAnnotation.customer_id == row.customer_id,
        CustomerAnnotation.annotation_type == "do_not_contact",
        CustomerAnnotation.status == "active",
        _scope_filter(payload.scope_type, payload.scope_ref_id),
    ).with_for_update().first()
    if existing is not None:
        raise GovernancePolicyError("DNC_SCOPE_ALREADY_ACTIVE")
    now = beijing_now()
    annotation = CustomerAnnotation(
        customer_id=row.customer_id,
        annotation_type="do_not_contact",
        content_schema_version="v1",
        content_json={
            "reason_code": payload.reason_code,
            "reason_text": payload.reason_text,
            "proposal_id": row.id,
        },
        policy_scope_type=payload.scope_type,
        policy_scope_ref_id=payload.scope_ref_id,
        policy_effective_at=payload.policy_effective_at,
        visibility="management",
        data_classification="restricted_internal",
        status="active",
        authored_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(annotation)
    db.flush()
    event_payload = {
        "proposal_id": row.id,
        "annotation_id": annotation.id,
        "scope_type": payload.scope_type,
        "reason_code": payload.reason_code,
    }
    if payload.scope_ref_id is not None:
        event_payload["scope_ref_id"] = payload.scope_ref_id
    append_customer_event(
        db, customer_id=row.customer_id, event_type="policy.dnc_set",
        event_source="governance", event_title="禁止联系政策已生效",
        event_payload=event_payload, payload_schema_version="customer_event_v1",
        occurred_at=now, source_ref_type="annotation",
        source_ref_id=str(annotation.id), importance="critical",
        data_classification="restricted_internal", visibility_scope="management",
        evidence_fact_ids=payload.evidence_fact_ids, actor_user_id=actor_user_id,
    )
    _invalidate_profile(db, account)
    return GovernanceExecutionResult(proposal=row, annotation_id=annotation.id)


def _execute_remove_dnc(
    db: Session, row: CustomerChangeProposal, payload: RemoveDncPayload,
    actor_user_id: int, account: CustomerAccount,
) -> GovernanceExecutionResult:
    annotation = db.query(CustomerAnnotation).filter(
        CustomerAnnotation.id == payload.annotation_id,
        CustomerAnnotation.customer_id == row.customer_id,
        CustomerAnnotation.annotation_type == "do_not_contact",
        CustomerAnnotation.status == "active",
        _scope_filter(payload.scope_type, payload.scope_ref_id),
    ).with_for_update().one_or_none()
    if annotation is None:
        raise GovernancePolicyError("DNC_ANNOTATION_STALE")
    now = beijing_now()
    annotation.status = "revoked"
    annotation.revoked_by = actor_user_id
    annotation.revoked_at = now
    annotation.updated_at = now
    blockers = _remaining_contactability_blockers(db, row.customer_id)
    event_payload = {
        "proposal_id": row.id,
        "annotation_id": annotation.id,
        "scope_type": payload.scope_type,
        "removal_reason": payload.removal_reason,
        "contactability_still_blocked": bool(blockers),
        "remaining_blockers": list(blockers),
    }
    if payload.scope_ref_id is not None:
        event_payload["scope_ref_id"] = payload.scope_ref_id
    append_customer_event(
        db, customer_id=row.customer_id, event_type="policy.dnc_removed",
        event_source="governance", event_title="禁止联系政策已撤销",
        event_payload=event_payload, payload_schema_version="customer_event_v1",
        occurred_at=now, source_ref_type="annotation",
        source_ref_id=str(annotation.id), importance="critical",
        data_classification="restricted_internal", visibility_scope="management",
        evidence_fact_ids=payload.evidence_fact_ids, actor_user_id=actor_user_id,
    )
    _invalidate_profile(db, account)
    return GovernanceExecutionResult(
        proposal=row, annotation_id=annotation.id,
        contactability_still_blocked=bool(blockers), remaining_blockers=blockers,
    )


def _execute_confirm_risk(
    db: Session, row: CustomerChangeProposal, payload: ConfirmMaterialRiskPayload,
    actor_user_id: int, account: CustomerAccount,
) -> GovernanceExecutionResult:
    if payload.source_fact_id not in payload.evidence_fact_ids:
        raise GovernancePolicyError("GOVERNANCE_EVIDENCE_STALE")
    source = db.query(CustomerFact).filter(
        CustomerFact.id == payload.source_fact_id,
        CustomerFact.customer_id == row.customer_id,
        CustomerFact.fact_key == RISK_SOURCE_FACT_KEYS[payload.risk_type],
        CustomerFact.fact_layer == "source",
        CustomerFact.verification_status.in_(("unverified", "candidate", "verified")),
        CustomerFact.effective_to.is_(None),
    ).with_for_update().one_or_none()
    now = beijing_now()
    if (
        source is None
        or source.expires_at is not None and source.expires_at <= now
        or source.effective_from is not None and source.effective_from > now
        or not secrets.compare_digest(source.fact_fingerprint, payload.source_fact_fingerprint)
        or not secrets.compare_digest(canonical_value_hash(source.value_json), payload.source_value_hash)
    ):
        raise GovernancePolicyError("MATERIAL_RISK_SOURCE_STALE")
    confirmed = append_fact(
        db, customer_id=row.customer_id, subject_type="customer",
        fact_key=RISK_CONFIRMED_FACT_KEYS[payload.risk_type], value_type="object",
        value=dict(source.value_json["value"]), fact_layer="confirmed",
        verification_status="verified", confidence=1,
        confidence_method_version="human_confirmed_risk_v1",
        confidence_components={"human_confirmation": 1, "source_fact_id": source.id},
        source_system="manual", source_entity_type="customer", observed_at=now,
        data_classification="restricted_internal", visibility_scope="management",
        classification_reason="Human-confirmed material risk; restricted to management",
        human_review=HumanReviewEvidence(
            reviewer_id=actor_user_id, reviewed_at=now,
            review_reference=f"customer_change_proposal:{row.id}",
            supporting_fact_ids=(source.id,),
        ),
        rule_version="material_risk_confirmation_v1",
    )
    link_fact_evidence(
        db,
        fact_id=confirmed.id,
        evidence_kind="fact",
        supporting_fact_id=source.id,
        relation_type="supports",
        evidence_content_hash=source.fact_fingerprint,
        locator={"proposal_id": row.id, "risk_type": payload.risk_type},
        data_classification="restricted_internal",
    )
    append_customer_event(
        db, customer_id=row.customer_id, event_type="risk.material_confirmed",
        event_source="governance", event_title="重大风险已人工确认",
        event_payload={
            "proposal_id": row.id, "risk_type": payload.risk_type,
            "source_fact_id": source.id, "confirmed_fact_id": confirmed.id,
        }, payload_schema_version="customer_event_v1", occurred_at=now,
        source_ref_type="fact", source_ref_id=str(confirmed.id), importance="critical",
        data_classification="restricted_internal", visibility_scope="management",
        evidence_fact_ids=payload.evidence_fact_ids, actor_user_id=actor_user_id,
    )
    _invalidate_profile(db, account)
    return GovernanceExecutionResult(proposal=row, confirmed_fact_id=confirmed.id)


def execute_governance_policy(
    db: Session, *, proposal_id: int, actor_user_id: int, idempotency_key: str,
) -> GovernanceExecutionResult:
    """Execute one approved DNC or material-risk proposal atomically."""
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 64:
        raise GovernancePolicyError("PROPOSAL_EXECUTION_KEY_INVALID")
    row = _lock_proposal(db, proposal_id)
    _require_human(db, actor_user_id)
    if row.status == "executed":
        if row.executed_by != actor_user_id:
            raise GovernancePolicyError("PROPOSAL_EXECUTION_ACTOR_MISMATCH")
        if row.execution_idempotency_key and secrets.compare_digest(
            row.execution_idempotency_key, idempotency_key,
        ):
            return _replay_result(db, row)
        raise GovernancePolicyError("PROPOSAL_EXECUTION_KEY_MISMATCH")
    _validate_approval(row)
    parsers = {
        "set_dnc": parse_set_dnc,
        "remove_dnc": parse_remove_dnc,
        "confirm_material_risk": parse_confirm_material_risk,
    }
    schema_versions = {
        "set_dnc": "customer_set_dnc_v1",
        "remove_dnc": "customer_remove_dnc_v1",
        "confirm_material_risk": "customer_confirm_material_risk_v1",
    }
    parser = parsers.get(row.action_type)
    if parser is None:
        raise GovernancePolicyError("GOVERNANCE_ACTION_UNSUPPORTED")
    if row.payload_schema_version != schema_versions[row.action_type]:
        raise GovernancePolicyError("GOVERNANCE_PAYLOAD_SCHEMA_INVALID")
    payload = parser(row.payload_json or {})
    account = _lock_live_basis(db, row, payload)
    with db.begin_nested():
        if row.action_type == "set_dnc":
            result = _execute_set_dnc(db, row, payload, actor_user_id, account)
        elif row.action_type == "remove_dnc":
            result = _execute_remove_dnc(db, row, payload, actor_user_id, account)
        else:
            result = _execute_confirm_risk(db, row, payload, actor_user_id, account)
        now = beijing_now()
        row.execution_idempotency_key = idempotency_key
        row.executed_by = actor_user_id
        row.executed_at = now
        row.status = "executed"
        row.updated_at = now
        db.flush()
    return result


__all__ = [
    "GovernanceExecutionResult", "GovernancePolicyError", "execute_governance_policy",
]
