"""Logical governance evidence and material-risk contracts."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

import app.customer.governance_policy_service as service
from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.governance_policy_contract import canonical_value_hash
from app.customer.fact_service import append_customer_event
from app.customer.identity_service import CustomerDomainError
from app.customer.models import (
    CustomerAgentContext, CustomerAnnotation, CustomerChangeProposal,
    CustomerEvent, CustomerFact, CustomerFactEvidenceLink,
    CustomerObjectOwnership, CustomerProfileVersion,
)
from app.customer.profile_service import compile_customer_profile
from app.customer.proposal_service import (
    ProposalConflict, approve_proposal, create_proposal, execute_proposal,
    submit_proposal,
)
from tests.test_customer_governance_policy import (
    _customer, _digest, _fact, _human, _profile, _proposal, _set_payload,
)

def test_confirm_material_risk_appends_confirmed_fact_without_mutating_source(db):
    human = _human(db, "risk")
    customer = _customer(db, "risk")
    source = _fact(db, customer, "risk", risk_type="fraud")
    profile = _profile(db, customer)
    payload = {
        "customer_id": customer.id, "profile_version_id": profile.id,
        "expected_profile_input_seq": customer.profile_input_seq,
        "risk_type": "fraud", "source_fact_id": source.id,
        "source_fact_fingerprint": source.fact_fingerprint,
        "source_value_hash": canonical_value_hash(source.value_json),
        "confirmation_reason": "Two-person review completed",
        "evidence_fact_ids": [source.id],
    }
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=[source],
        action_type="confirm_material_risk", payload=payload, suffix="risk",
    )
    original = (source.fact_layer, source.verification_status, dict(source.value_json))
    input_seq_before = customer.profile_input_seq

    result = service.execute_governance_policy(
        db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="risk-key",
    )
    confirmed = db.get(CustomerFact, result.confirmed_fact_id)

    assert (source.fact_layer, source.verification_status, source.value_json) == original
    assert confirmed.fact_key == "risk.confirmed.fraud"
    assert confirmed.fact_layer == "confirmed"
    assert confirmed.data_classification == "restricted_internal"
    assert confirmed.visibility_scope == "management"
    assert db.query(CustomerFactEvidenceLink).filter_by(
        fact_id=confirmed.id,
        evidence_kind="fact",
        supporting_fact_id=source.id,
        relation_type="supports",
    ).count() == 1
    assert customer.profile_input_seq == input_seq_before + 2
    assert db.query(CustomerEvent).filter_by(event_type="risk.material_confirmed").count() == 1
    replay = service.execute_governance_policy(
        db, proposal_id=proposal.id, actor_user_id=human.id,
        idempotency_key="risk-key",
    )
    assert replay.confirmed_fact_id == confirmed.id
    assert customer.profile_input_seq == input_seq_before + 2

    second_payload = dict(payload)
    second_payload["confirmation_reason"] = "new independent approval"
    second = _proposal(
        db, customer=customer, profile=profile, evidence=[source],
        action_type="confirm_material_risk", payload=second_payload,
        suffix="risk-second",
    )
    with pytest.raises(CustomerDomainError) as old_link_error:
        append_customer_event(
            db, customer_id=customer.id, event_type="risk.material_confirmed",
            event_source="governance", event_title="reuse old confirmation",
            event_payload={
                "proposal_id": second.id, "risk_type": "fraud",
                "source_fact_id": source.id, "confirmed_fact_id": confirmed.id,
            }, payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(), source_ref_type="fact",
            source_ref_id=str(confirmed.id), evidence_fact_ids=[source.id],
            actor_user_id=human.id, data_classification="restricted_internal",
            visibility_scope="management",
        )
    assert old_link_error.value.error_code == "EVENT_REFERENCE_INVALID"
    assert customer.profile_input_seq == input_seq_before + 2


def test_stale_profile_input_and_changed_risk_value_hash_fail_closed(db):
    human = _human(db, "stale")
    customer = _customer(db, "stale")
    source = _fact(db, customer, "stale", risk_type="sanctions")
    profile = _profile(db, customer)
    payload = {
        "customer_id": customer.id, "profile_version_id": profile.id,
        "expected_profile_input_seq": customer.profile_input_seq,
        "risk_type": "sanctions", "source_fact_id": source.id,
        "source_fact_fingerprint": source.fact_fingerprint,
        "source_value_hash": "0" * 64, "confirmation_reason": "reviewed",
        "evidence_fact_ids": [source.id],
    }
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=[source],
        action_type="confirm_material_risk", payload=payload, suffix="stale",
    )

    with pytest.raises(service.GovernancePolicyError, match="SOURCE_STALE"):
        service.execute_governance_policy(
            db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="stale-key",
        )
    assert db.query(CustomerFact).filter_by(fact_key="risk.confirmed.sanctions").count() == 0


def test_restricted_confirmed_material_risk_is_in_profile_but_not_agent_context(db):
    customer = _customer(db, "risk-redaction")
    now = beijing_now()
    risk = CustomerFact(
        customer_id=customer.id, subject_type="customer", subject_id=None,
        fact_key="risk.confirmed.material_legal", value_type="object",
        value_json={"value": {"case": "restricted legal detail"}},
        fact_layer="confirmed", verification_status="verified",
        confidence=Decimal("1.0000"), confidence_method_version="human_v1",
        confidence_components_json={"human_confirmation": 1},
        data_classification="restricted_internal", visibility_scope="management",
        classification_reason="restricted management risk",
        evidence_json={"fact_ids": [999]}, rule_version="risk_v1",
        fact_fingerprint=_digest("risk-redaction"), effective_from=now,
        observed_at=now, reviewed_at=now,
    )
    db.add(risk)
    customer.profile_input_seq += 1
    db.flush()
    db.commit()

    compiled = compile_customer_profile(sessionmaker(bind=db.get_bind()), customer.id)
    db.expire_all()
    version = db.get(CustomerProfileVersion, compiled.profile_version_id)
    context = db.get(CustomerAgentContext, customer.id)

    assert version.profile_json["risks"]["items"][0]["risk_type"] == "material_legal"
    assert version.profile_json["risks"]["items"][0]["value"] == {
        "case": "restricted legal detail"
    }
    assert context.context_json["risks"]["items"] == []


def test_generic_event_entry_rejects_commercial_fact_as_confirmed_material_risk(db):
    human = _human(db, "fake-risk")
    customer = _customer(db, "fake-risk")
    risk_source = _fact(db, customer, "fake-risk-source", risk_type="fraud")
    ordinary = _fact(db, customer, "fake-risk-commercial")
    profile = _profile(db, customer)
    payload = {
        "customer_id": customer.id, "profile_version_id": profile.id,
        "expected_profile_input_seq": customer.profile_input_seq,
        "risk_type": "fraud", "source_fact_id": risk_source.id,
        "source_fact_fingerprint": risk_source.fact_fingerprint,
        "source_value_hash": canonical_value_hash(risk_source.value_json),
        "confirmation_reason": "reviewed",
        "evidence_fact_ids": [risk_source.id],
    }
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=[risk_source],
        action_type="confirm_material_risk", payload=payload, suffix="fake-risk",
    )
    input_seq_before = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as exc_info:
        append_customer_event(
            db, customer_id=customer.id, event_type="risk.material_confirmed",
            event_source="governance", event_title="fake risk",
            event_payload={
                "proposal_id": proposal.id, "risk_type": "fraud",
                "source_fact_id": risk_source.id, "confirmed_fact_id": ordinary.id,
            }, payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(), source_ref_type="fact",
            source_ref_id=str(ordinary.id), evidence_fact_ids=[risk_source.id],
            actor_user_id=human.id, data_classification="restricted_internal",
            visibility_scope="management",
        )
    assert exc_info.value.error_code == "EVENT_REFERENCE_INVALID"
    assert customer.profile_input_seq == input_seq_before


def test_set_dnc_full_lifecycle_accepts_logically_owned_storage_fact(db):
    proposer = _human(db, "logical-dnc")
    approver = ArkUser(
        username="logical-dnc-approver", password_hash="test-only",
        real_name="Logical DNC Approver", is_active=True,
    )
    storage = _customer(db, "logical-storage")
    target = _customer(db, "logical-target")
    other = _customer(db, "logical-other")
    evidence = _fact(db, storage, "logical-evidence")
    storage_profile = _profile(db, storage)
    target_profile = _profile(db, target)
    historical = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=storage_profile.id,
        evidence_fact_ids=[evidence.id], risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management",
        action_hash=_digest("logical-history"), status="executed",
        expires_at=beijing_now() + timedelta(days=1),
    )
    db.add_all([approver, historical])
    db.flush()
    ownership = CustomerObjectOwnership(
        object_type="fact", object_id=evidence.id,
        storage_customer_id=storage.id, current_customer_id=target.id,
        ownership_version=1, last_change_proposal_id=historical.id,
        last_action_type="split",
    )
    db.add(ownership)
    db.flush()
    payload = _set_payload(target, target_profile, [evidence])

    proposal = create_proposal(
        db, customer_id=target.id, target_customer_id=None,
        action_type="set_dnc", payload_schema_version="customer_set_dnc_v1",
        payload_json=payload, profile_version_id=target_profile.id,
        evidence_fact_ids=[evidence.id], risk_level="critical",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=proposer.id,
    )
    submit_proposal(db, proposal_id=proposal.id, actor_user_id=proposer.id)
    approve_proposal(db, proposal_id=proposal.id, actor_user_id=approver.id)
    ownership.current_customer_id = other.id
    db.flush()
    with pytest.raises(ProposalConflict, match="PROPOSAL_EVIDENCE_INVALID"):
        execute_proposal(
            db, proposal_id=proposal.id, actor_user_id=proposer.id,
            idempotency_key="logical-dnc-cross-owner",
        )
    ownership.current_customer_id = target.id
    db.flush()
    execute_proposal(
        db, proposal_id=proposal.id, actor_user_id=proposer.id,
        idempotency_key="logical-dnc-execution",
    )

    live = db.get(CustomerChangeProposal, proposal.id)
    annotation = db.query(CustomerAnnotation).filter_by(
        customer_id=target.id, annotation_type="do_not_contact", status="active",
    ).one()
    assert live.status == "executed"
    assert annotation.content_json["proposal_id"] == proposal.id
