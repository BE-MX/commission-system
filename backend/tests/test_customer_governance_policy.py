"""Approved DNC and material-risk proposal executor contracts."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

import app.customer.governance_policy_service as service
from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.core.time import beijing_now
from app.customer.governance_policy_contract import canonical_value_hash
from app.customer.fact_service import append_customer_event
from app.customer.identity_service import CustomerDomainError
from app.customer.models import (
    CustomerAccount,
    CustomerAgentContext,
    CustomerAnnotation,
    CustomerChangeProposal,
    CustomerEvent,
    CustomerFact,
    CustomerFactEvidenceLink,
    CustomerProfileVersion,
    CustomerSuppressionRegistry,
)
from app.customer.proposal_service import canonical_action_hash
from app.customer.profile_service import compile_customer_profile


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _human(db, suffix: str) -> ArkUser:
    permission = ArkPermission(
        code=f"customer:write:{suffix}", module="customer", action="write",
        label="Customer write", kind="action", is_legacy=0, sort=0,
    )
    # fact_service recognizes the exact stable permission code.
    permission.code = "customer:write"
    role = ArkRole(
        name=f"governance-{suffix}", label="Governance reviewer",
        is_system=True, permissions=[permission],
    )
    user = ArkUser(
        username=f"governance-{suffix}", password_hash="test-only",
        real_name="Governance Reviewer", is_active=True, roles=[role],
    )
    db.add(user)
    db.flush()
    return user


def _customer(db, suffix: str) -> CustomerAccount:
    now = beijing_now()
    row = CustomerAccount(
        customer_code=f"G-{suffix}", display_name=f"Governance {suffix}",
        canonical_company_name=f"{suffix} LLC", entity_type="registered_company",
        identity_status="verified", relationship_stage="qualified",
        relationship_stage_changed_at=now, relationship_stage_reason="test",
        record_status="active", identity_confidence=Decimal("0.9000"),
        profile_completeness=Decimal("50.00"), profile_input_seq=1,
    )
    db.add(row)
    db.flush()
    return row


def _fact(db, customer, suffix: str, *, risk_type: str | None = None) -> CustomerFact:
    now = beijing_now()
    value = {"finding": "restricted detail", "severity": "material"}
    row = CustomerFact(
        customer_id=customer.id, subject_type="customer", subject_id=None,
        fact_key=(f"risk.source.{risk_type}" if risk_type else "commercial.has_valid_order"),
        value_type="object" if risk_type else "boolean",
        value_json={"value": value if risk_type else True},
        fact_layer="source" if risk_type else "observed",
        verification_status="candidate" if risk_type else "verified",
        confidence=Decimal("0.9000"), confidence_method_version="test_v1",
        confidence_components_json={"source_authority": 0.9},
        data_classification="restricted_internal" if risk_type else "internal_business",
        visibility_scope="management" if risk_type else "customer_team",
        classification_reason="test evidence", evidence_json={"fact_ids": []},
        rule_version="risk_source_v1" if risk_type else "order_v1",
        fact_fingerprint=_digest(f"{customer.id}|{suffix}|{risk_type}"),
        effective_from=now - timedelta(days=1), observed_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30) if risk_type else None,
    )
    db.add(row)
    customer.profile_input_seq += 1
    db.flush()
    return row


def _profile(db, customer) -> CustomerProfileVersion:
    now = beijing_now()
    row = CustomerProfileVersion(
        customer_id=customer.id, version_no=1,
        profile_schema_version="customer_profile_v1", canonicalization_version="jcs_v1",
        input_seq=customer.profile_input_seq, profile_json={}, section_hashes={},
        section_data_as_of={}, evidence_fact_ids=[], change_summary={"changes": []},
        compiler_version="test_v1", profile_fingerprint=_digest(f"profile|{customer.id}"),
        compiled_at=now, created_at=now,
    )
    db.add(row)
    db.flush()
    customer.current_profile_version_id = row.id
    customer.profile_compiled_at = now
    db.add(CustomerAgentContext(
        customer_id=customer.id, profile_version_id=row.id,
        context_schema_version="customer_context_v1", context_json={},
        max_data_classification="internal_business", context_hash=_digest("context" + str(customer.id)),
        built_at=now, updated_at=now,
    ))
    db.flush()
    return row


def _proposal(db, *, customer, profile, evidence, action_type, payload, suffix):
    action_hash = canonical_action_hash(
        action_type=action_type, customer_id=customer.id, target_customer_id=None,
        payload_json=payload, profile_version_id=profile.id,
        evidence_fact_ids=[item.id for item in evidence],
    )
    row = CustomerChangeProposal(
        customer_id=customer.id, action_type=action_type,
        payload_schema_version={
            "set_dnc": "customer_set_dnc_v1",
            "remove_dnc": "customer_remove_dnc_v1",
            "confirm_material_risk": "customer_confirm_material_risk_v1",
        }[action_type],
        payload_json=payload, profile_version_id=profile.id,
        evidence_fact_ids=[item.id for item in evidence], risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management",
        action_hash=action_hash, approved_action_hash=action_hash,
        expires_at=beijing_now() + timedelta(days=1), status="approved",
        decided_at=beijing_now(), created_at=beijing_now(), updated_at=beijing_now(),
    )
    db.add(row)
    db.flush()
    return row


def _set_payload(customer, profile, evidence):
    return {
        "customer_id": customer.id, "profile_version_id": profile.id,
        "expected_profile_input_seq": customer.profile_input_seq,
        "scope_type": "global", "scope_ref_id": None,
        "reason_code": "customer_request", "reason_text": "Do not contact",
        "policy_effective_at": beijing_now().isoformat(),
        "expected_active_annotation_id": None,
        "evidence_fact_ids": [item.id for item in evidence],
    }


def test_set_dnc_is_exact_idempotent_and_invalidates_current_profile(db):
    human = _human(db, "set")
    customer = _customer(db, "set")
    evidence = [_fact(db, customer, "set")]
    profile = _profile(db, customer)
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=evidence,
        action_type="set_dnc", payload=_set_payload(customer, profile, evidence), suffix="set",
    )
    input_seq_before = customer.profile_input_seq

    result = service.execute_governance_policy(
        db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="set-key",
    )
    replay = service.execute_governance_policy(
        db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="set-key",
    )

    annotation = db.get(CustomerAnnotation, result.annotation_id)
    assert annotation.status == "active"
    assert annotation.visibility == "management"
    assert replay.annotation_id == result.annotation_id
    assert customer.profile_input_seq == input_seq_before + 1
    assert proposal.status == replay.proposal.status == "executed"
    assert customer.current_profile_version_id is None
    assert db.get(CustomerAgentContext, customer.id) is None
    assert db.query(CustomerEvent).filter_by(event_type="policy.dnc_set").count() == 1
    with pytest.raises(CustomerDomainError) as executed_event_error:
        append_customer_event(
            db, customer_id=customer.id, event_type="policy.dnc_set",
            event_source="governance", event_title="late duplicate",
            event_payload={
                "proposal_id": proposal.id,
                "annotation_id": annotation.id,
                "scope_type": "global",
                "reason_code": "customer_request",
            }, payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(), source_ref_type="annotation",
            source_ref_id=str(annotation.id),
            evidence_fact_ids=[item.id for item in evidence],
            actor_user_id=human.id, data_classification="restricted_internal",
            visibility_scope="management",
        )
    assert executed_event_error.value.error_code == "EVENT_REFERENCE_INVALID"
    assert customer.profile_input_seq == input_seq_before + 1
    with pytest.raises(service.GovernancePolicyError, match="KEY_MISMATCH"):
        service.execute_governance_policy(
            db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="other-key",
        )


def test_set_dnc_stale_scope_and_event_failure_roll_back_everything(db, monkeypatch):
    human = _human(db, "rollback")
    customer = _customer(db, "rollback")
    evidence = [_fact(db, customer, "rollback")]
    profile = _profile(db, customer)
    payload = _set_payload(customer, profile, evidence)
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=evidence,
        action_type="set_dnc", payload=payload, suffix="rollback",
    )
    monkeypatch.setattr(service, "append_customer_event", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event failed")))

    with pytest.raises(RuntimeError, match="event failed"):
        service.execute_governance_policy(
            db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="rollback-key",
        )
    db.expire_all()

    assert db.query(CustomerAnnotation).count() == 0
    assert db.get(CustomerChangeProposal, proposal.id).status == "approved"
    assert db.get(CustomerAccount, customer.id).current_profile_version_id == profile.id
    assert db.get(CustomerAgentContext, customer.id) is not None


def test_remove_dnc_revokes_only_annotation_and_keeps_central_suppression(db):
    human = _human(db, "remove")
    customer = _customer(db, "remove")
    evidence = [_fact(db, customer, "remove")]
    now = beijing_now()
    annotation = CustomerAnnotation(
        customer_id=customer.id, annotation_type="do_not_contact",
        content_schema_version="v1", content_json={"reason": "request"},
        policy_scope_type="global", policy_effective_at=now,
        visibility="management", data_classification="restricted_internal",
        status="active", authored_by=human.id, created_at=now, updated_at=now,
    )
    db.add(annotation)
    db.flush()
    suppression = CustomerSuppressionRegistry(
        identifier_type="email", source_system="global", source_account_key="global",
        normalized_value_hmac=_digest("blocked@example.com"), hmac_key_version="v1",
        scope_type="global", reason_code="hard_bounce", source_ref_type="provider_event",
        source_ref_id="bounce-1", status="active", mapping_status="mapped",
        mapped_customer_id=customer.id, suppression_fingerprint=_digest("suppression"),
        effective_at=now, created_at=now, updated_at=now,
    )
    db.add(suppression)
    profile = _profile(db, customer)
    payload = {
        "customer_id": customer.id, "profile_version_id": profile.id,
        "expected_profile_input_seq": customer.profile_input_seq,
        "scope_type": "global", "scope_ref_id": None,
        "annotation_id": annotation.id, "expected_active_annotation_id": annotation.id,
        "removal_reason": "approved customer request",
        "evidence_fact_ids": [item.id for item in evidence],
    }
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=evidence,
        action_type="remove_dnc", payload=payload, suffix="remove",
    )
    input_seq_before = customer.profile_input_seq

    result = service.execute_governance_policy(
        db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="remove-key",
    )

    assert annotation.status == "revoked"
    assert suppression.status == "active"
    assert result.contactability_still_blocked is True
    assert result.remaining_blockers == ("central_suppression",)
    assert customer.profile_input_seq == input_seq_before + 1
    replay = service.execute_governance_policy(
        db, proposal_id=proposal.id, actor_user_id=human.id,
        idempotency_key="remove-key",
    )
    assert replay.annotation_id == annotation.id
    assert customer.profile_input_seq == input_seq_before + 1


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


def test_payload_extra_field_and_profile_input_change_fail_closed(db):
    human = _human(db, "payload-stale")
    customer = _customer(db, "payload-stale")
    evidence = [_fact(db, customer, "payload-stale")]
    profile = _profile(db, customer)
    payload = _set_payload(customer, profile, evidence)
    payload["unapproved_extra"] = True
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=evidence,
        action_type="set_dnc", payload=payload, suffix="payload-stale",
    )
    with pytest.raises(ValueError, match="GOVERNANCE_PAYLOAD_INVALID"):
        service.execute_governance_policy(
            db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="payload-key",
        )

    del payload["unapproved_extra"]
    proposal.payload_json = payload
    proposal.action_hash = canonical_action_hash(
        action_type="set_dnc", customer_id=customer.id, target_customer_id=None,
        payload_json=payload, profile_version_id=profile.id,
        evidence_fact_ids=[item.id for item in evidence],
    )
    proposal.approved_action_hash = proposal.action_hash
    customer.profile_input_seq += 1
    db.flush()
    with pytest.raises(service.GovernancePolicyError, match="GOVERNANCE_PROFILE_STALE"):
        service.execute_governance_policy(
            db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="stale-profile-key",
        )


def test_existing_dnc_scope_rejects_set_without_overwriting(db):
    human = _human(db, "duplicate-dnc")
    customer = _customer(db, "duplicate-dnc")
    evidence = [_fact(db, customer, "duplicate-dnc")]
    now = beijing_now()
    existing = CustomerAnnotation(
        customer_id=customer.id, annotation_type="do_not_contact",
        content_schema_version="v1", content_json={"reason": "existing"},
        policy_scope_type="global", policy_effective_at=now,
        visibility="management", data_classification="restricted_internal",
        status="active", authored_by=human.id, created_at=now, updated_at=now,
    )
    db.add(existing)
    profile = _profile(db, customer)
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=evidence,
        action_type="set_dnc", payload=_set_payload(customer, profile, evidence),
        suffix="duplicate-dnc",
    )

    with pytest.raises(service.GovernancePolicyError, match="DNC_SCOPE_ALREADY_ACTIVE"):
        service.execute_governance_policy(
            db, proposal_id=proposal.id, actor_user_id=human.id, idempotency_key="duplicate-key",
        )
    db.refresh(existing)
    assert existing.status == "active"
    assert existing.content_json == {"reason": "existing"}


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


def test_generic_event_entry_rejects_fake_dnc_proposal_without_bumping_seq(db):
    human = _human(db, "fake-dnc-proposal")
    customer = _customer(db, "fake-dnc-proposal")
    now = beijing_now()
    annotation = CustomerAnnotation(
        customer_id=customer.id, annotation_type="do_not_contact",
        content_schema_version="v1", content_json={"proposal_id": 999, "reason_code": "request"},
        policy_scope_type="global", policy_effective_at=now,
        visibility="management", data_classification="restricted_internal",
        status="active", authored_by=human.id, created_at=now, updated_at=now,
    )
    db.add(annotation)
    db.flush()
    input_seq_before = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as exc_info:
        append_customer_event(
            db, customer_id=customer.id, event_type="policy.dnc_set",
            event_source="governance", event_title="fake",
            event_payload={
                "proposal_id": 999, "annotation_id": annotation.id,
                "scope_type": "global", "reason_code": "request",
            },
            payload_schema_version="customer_event_v1", occurred_at=now,
            source_ref_type="annotation", source_ref_id=str(annotation.id),
            actor_user_id=human.id, data_classification="restricted_internal",
            visibility_scope="management",
        )
    assert exc_info.value.error_code == "EVENT_REFERENCE_INVALID"
    assert customer.profile_input_seq == input_seq_before


def test_generic_event_entry_rejects_dnc_scope_not_approved_by_proposal(db):
    human = _human(db, "fake-dnc-scope")
    customer = _customer(db, "fake-dnc-scope")
    evidence = [_fact(db, customer, "fake-dnc-scope")]
    profile = _profile(db, customer)
    proposal = _proposal(
        db, customer=customer, profile=profile, evidence=evidence,
        action_type="set_dnc", payload=_set_payload(customer, profile, evidence),
        suffix="fake-dnc-scope",
    )
    now = beijing_now()
    annotation = CustomerAnnotation(
        customer_id=customer.id, annotation_type="do_not_contact",
        content_schema_version="v1",
        content_json={"proposal_id": proposal.id, "reason_code": "customer_request"},
        policy_scope_type="channel", policy_scope_ref_id="email",
        policy_effective_at=now, visibility="management",
        data_classification="restricted_internal", status="active",
        authored_by=human.id, created_at=now, updated_at=now,
    )
    db.add(annotation)
    db.flush()
    input_seq_before = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as exc_info:
        append_customer_event(
            db, customer_id=customer.id, event_type="policy.dnc_set",
            event_source="governance", event_title="fake scope",
            event_payload={
                "proposal_id": proposal.id, "annotation_id": annotation.id,
                "scope_type": "channel", "scope_ref_id": "email",
                "reason_code": "customer_request",
            }, payload_schema_version="customer_event_v1", occurred_at=now,
            source_ref_type="annotation", source_ref_id=str(annotation.id),
            evidence_fact_ids=[item.id for item in evidence], actor_user_id=human.id,
            data_classification="restricted_internal", visibility_scope="management",
        )
    assert exc_info.value.error_code == "EVENT_REFERENCE_INVALID"
    assert customer.profile_input_seq == input_seq_before


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
