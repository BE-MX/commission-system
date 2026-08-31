"""Shared builders for customer proposal contract tests."""

from datetime import timedelta

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer import models
from app.customer.proposal_service import canonical_action_hash


def basis(db, *, suffix: str = "A"):
    now = beijing_now()
    actor = ArkUser(
        username=f"proposal-executor-{suffix}", password_hash="x",
        real_name="Proposal Executor", is_active=True,
    )
    customer = models.CustomerAccount(
        customer_code=f"PE-{suffix}", display_name=f"Proposal {suffix}",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="qualified", relationship_stage_changed_at=now,
        relationship_stage_reason="test", record_status="active",
        identity_confidence=1, profile_completeness=80, profile_input_seq=1,
    )
    db.add_all([actor, customer])
    db.flush()
    profile = models.CustomerProfileVersion(
        customer_id=customer.id, version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1", input_seq=1, profile_json={},
        section_hashes={}, section_data_as_of={}, evidence_fact_ids=[],
        change_summary={}, compiler_version="test",
        profile_fingerprint=(f"{customer.id:x}" * 64)[:64],
        compiled_at=now, created_at=now,
    )
    fact = models.CustomerFact(
        customer_id=customer.id, subject_type="customer",
        fact_key="identity.company_name", fact_layer="confirmed",
        value_type="string", value_json={"value": customer.display_name},
        verification_status="verified", confidence=1,
        confidence_method_version="test", confidence_components_json={},
        data_classification="restricted_internal", visibility_scope="management",
        classification_reason="proposal evidence", evidence_json={},
        fact_fingerprint=(f"{customer.id + 1:x}" * 64)[:64], observed_at=now,
    )
    db.add_all([profile, fact])
    db.flush()
    customer.current_profile_version_id = profile.id
    db.flush()
    return actor, customer, profile, fact


def set_dnc_payload(customer, profile, fact):
    return {
        "customer_id": customer.id,
        "profile_version_id": profile.id,
        "expected_profile_input_seq": customer.profile_input_seq,
        "scope_type": "global",
        "scope_ref_id": None,
        "reason_code": "customer_request",
        "reason_text": "Do not contact",
        "policy_effective_at": beijing_now().isoformat(),
        "expected_active_annotation_id": None,
        "evidence_fact_ids": [fact.id],
    }


def approved(
    db, *, customer, profile, fact, actor, action_type, payload,
    target=None, row_id=None,
):
    action_hash = canonical_action_hash(
        action_type=action_type, customer_id=customer.id,
        target_customer_id=target.id if target else None,
        payload_json=payload, profile_version_id=profile.id,
        evidence_fact_ids=[fact.id],
    )
    row = models.CustomerChangeProposal(
        id=row_id, customer_id=customer.id,
        target_customer_id=target.id if target else None,
        action_type=action_type,
        payload_schema_version=f"customer_{action_type}_v1",
        payload_json=payload, profile_version_id=profile.id,
        evidence_fact_ids=[fact.id], risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management",
        action_hash=action_hash, approved_action_hash=action_hash,
        status="approved", proposed_by=actor.id, decided_by=actor.id,
        decided_at=beijing_now(), expires_at=beijing_now() + timedelta(days=1),
    )
    db.add(row)
    db.flush()
    return row
