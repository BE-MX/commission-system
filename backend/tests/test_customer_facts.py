"""Immutable source, fact, evidence, conflict, and event ledger contracts."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.time import beijing_now
from app.customer.fact_service import (
    append_customer_event,
    append_fact,
    append_source_record,
    link_fact_evidence,
    open_fact_conflict,
)
from app.customer.identity_service import CustomerDomainError, resolve_business_context
from app.customer.models import (
    CustomerAccount,
    CustomerConversation,
    CustomerEvent,
    CustomerFact,
    CustomerFactConflict,
    CustomerFactEvidenceLink,
    CustomerSourceRecord,
)


def _customer(db, suffix: str) -> CustomerAccount:
    return resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="facts-test",
        source_entity_type="inquiry",
        external_context_id=f"inq-{suffix}",
    ).customer


def _source(db, customer: CustomerAccount, *, external_id: str, payload=None):
    return append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id=external_id,
        source_version="v1",
        payload_schema_version="public_company_page_v1",
        payload_json=payload or {"industry": "Hair products"},
        publisher_key="example.com",
        source_family_key=f"page:{external_id}",
        source_url=f"https://example.com/{external_id}",
        occurred_at=beijing_now() - timedelta(days=1),
    )


def _industry_fact(db, customer, source, value="Hair products", **overrides):
    values = {
        "customer_id": customer.id,
        "subject_type": "customer",
        "fact_key": "business.industry",
        "value_type": "string",
        "value": value,
        "fact_layer": "source",
        "verification_status": "candidate",
        "confidence": 0.8,
        "confidence_method_version": "confidence_v1",
        "confidence_components": {"source_authority": 0.8},
        "source_record_id": source.id,
        "source_system": "public_web",
        "source_entity_type": "company_page",
        "observed_at": source.occurred_at,
        "evidence": {"source_record_ids": [source.id]},
    }
    values.update(overrides)
    return append_fact(db, **values)


def test_source_record_replay_is_idempotent_and_changed_content_appends_version(db):
    customer = _customer(db, "source-replay")
    initial_seq = customer.profile_input_seq
    first = _source(db, customer, external_id="about", payload={"industry": "Hair"})
    first_payload = dict(first.payload_json)
    first_seq = customer.profile_input_seq
    replay = _source(db, customer, external_id="about", payload={"industry": "Hair"})
    changed = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="about",
        source_version="v2",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair extensions"},
        publisher_key="example.com",
        source_family_key="page:about",
        source_url="https://example.com/about",
        occurred_at=beijing_now(),
    )

    assert replay.id == first.id
    assert changed.id != first.id
    assert first.payload_json == first_payload
    assert first.content_hash != changed.content_hash
    assert customer.profile_input_seq == initial_seq + 2
    assert first_seq == initial_seq + 1


def test_source_payload_is_copied_and_hash_is_canonical(db):
    customer = _customer(db, "source-copy")
    payload = {"b": [2, 1], "a": {"name": "莱莎"}}
    first = _source(db, customer, external_id="canonical", payload=payload)
    payload["a"]["name"] = "caller mutation"
    replay = _source(
        db,
        customer,
        external_id="canonical",
        payload={"a": {"name": "莱莎"}, "b": [2, 1]},
    )

    assert first.id == replay.id
    assert first.payload_json["a"]["name"] == "莱莎"
    assert len(first.content_hash) == 64


def test_unregistered_source_and_fact_fail_closed(db):
    customer = _customer(db, "registry")
    with pytest.raises(CustomerDomainError) as source_error:
        append_source_record(
            db,
            customer_id=customer.id,
            source_system="unknown_vendor",
            source_account_key="global",
            source_entity_type="mystery",
            external_record_id="1",
            payload_schema_version="v1",
            payload_json={},
        )
    assert source_error.value.error_code == "SOURCE_NOT_REGISTERED"

    source = _source(db, customer, external_id="known")
    with pytest.raises(CustomerDomainError) as fact_error:
        _industry_fact(db, customer, source, fact_key="business.secret_unregistered")
    assert fact_error.value.error_code == "FACT_NOT_REGISTERED"


def test_fact_source_policy_and_classification_are_enforced_not_caller_lowered(db):
    customer = _customer(db, "classification")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="okki",
        source_account_key="tenant-a",
        source_entity_type="customer",
        external_record_id="okki-customer-1",
        payload_schema_version="okki_customer_v1",
        payload_json={"industry": "Hair"},
        data_classification="public_business",
    )
    fact = append_fact(
        db,
        customer_id=customer.id,
        subject_type="customer",
        fact_key="business.industry",
        value_type="string",
        value="Hair",
        fact_layer="source",
        verification_status="verified",
        confidence=1,
        confidence_method_version="confidence_v1",
        confidence_components={"source_authority": 1},
        source_record_id=source.id,
        source_system="okki",
        source_entity_type="customer",
        observed_at=beijing_now(),
        data_classification="public_business",
    )

    assert source.data_classification == "internal_business"
    assert fact.data_classification == "internal_business"

    with pytest.raises(CustomerDomainError) as wrong_source:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="business.industry",
            value_type="string",
            value="Hair",
            fact_layer="source",
            verification_status="candidate",
            confidence=0.5,
            confidence_method_version="confidence_v1",
            confidence_components={},
            source_system="agent",
            source_entity_type="research_report",
            observed_at=beijing_now(),
        )
    assert wrong_source.value.error_code == "FACT_SOURCE_NOT_ALLOWED"

    with pytest.raises(CustomerDomainError) as missing_source_record:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="business.industry",
            value_type="string",
            value="Hair",
            fact_layer="source",
            verification_status="candidate",
            confidence=0.5,
            confidence_method_version="confidence_v1",
            confidence_components={"source_authority": 0.5},
            source_system="public_web",
            source_entity_type="company_page",
            observed_at=beijing_now(),
        )
    assert missing_source_record.value.error_code == "FACT_SOURCE_RECORD_REQUIRED"


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("string", 4),
        ("number", True),
        ("boolean", "yes"),
        ("date", "not-a-date"),
        ("datetime", "2026-08-30"),
        ("list", {}),
        ("object", []),
    ],
)
def test_fact_typed_value_validation_rejects_mismatches(db, value_type, value):
    customer = _customer(db, f"typed-{value_type}")
    source = _source(db, customer, external_id=f"typed-{value_type}")

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(db, customer, source, value_type=value_type, value=value)

    assert invalid.value.error_code == "FACT_VALUE_INVALID"


def test_fact_replay_is_idempotent_with_temporal_freshness_and_sequence(db):
    customer = _customer(db, "fact-replay")
    source = _source(db, customer, external_id="fact-replay")
    initial_seq = customer.profile_input_seq
    observed_at = beijing_now() - timedelta(days=2)
    first = _industry_fact(db, customer, source, observed_at=observed_at)
    first_seq = customer.profile_input_seq
    replay = _industry_fact(db, customer, source, observed_at=observed_at)

    assert replay.id == first.id
    assert first.effective_from == observed_at
    assert first.expires_at == observed_at + timedelta(days=365)
    assert first_seq == initial_seq + 1
    assert customer.profile_input_seq == first_seq


def test_fact_requires_versioned_nonempty_confidence_components(db):
    customer = _customer(db, "confidence-contract")
    source = _source(db, customer, external_id="confidence-contract")

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(
            db,
            customer,
            source,
            confidence_method_version="",
            confidence_components={},
        )

    assert invalid.value.error_code == "FACT_CONFIDENCE_INVALID"

    with pytest.raises(CustomerDomainError) as empty:
        _industry_fact(
            db,
            customer,
            source,
            confidence_method_version="confidence_v1",
            confidence_components={},
        )
    assert empty.value.error_code == "FACT_CONFIDENCE_INVALID"


def test_expressed_observed_and_inferred_semantics_require_matching_keys(db):
    customer = _customer(db, "layers")
    inquiry = append_source_record(
        db,
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_record_id="inquiry-layer",
        payload_schema_version="alibaba_inquiry_v1",
        payload_json={"color": "gold"},
    )
    conversation = CustomerConversation(
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        external_conversation_id="conversation-layer",
        channel="alibaba",
        conversation_status="active",
        latest_source_record_id=inquiry.id,
    )
    db.add(conversation)
    db.flush()
    expressed = append_fact(
        db,
        customer_id=customer.id,
        subject_type="conversation",
        subject_id=conversation.id,
        fact_key="preference.expressed.color",
        value_type="string",
        value="gold",
        fact_layer="expressed",
        verification_status="candidate",
        confidence=0.9,
        confidence_method_version="confidence_v1",
        confidence_components={"exactness": 1},
        source_record_id=inquiry.id,
        source_system="alibaba",
        source_entity_type="inquiry",
        observed_at=beijing_now(),
    )
    assert expressed.fact_layer == "expressed"

    with pytest.raises(CustomerDomainError) as mismatch:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="preference.expressed.color",
            value_type="string",
            value="gold",
            fact_layer="inferred",
            verification_status="candidate",
            confidence=0.6,
                confidence_method_version="confidence_v1",
                confidence_components={"model_uncertainty": 0.4},
                source_record_id=inquiry.id,
                source_system="alibaba",
            source_entity_type="inquiry",
            observed_at=beijing_now(),
        )
    assert mismatch.value.error_code == "FACT_LAYER_INVALID"


def test_inferred_fact_requires_rule_and_evidence_fact_ids(db):
    customer = _customer(db, "inferred-evidence")

    with pytest.raises(CustomerDomainError) as missing:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="behavior.inferred.churn_risk",
            value_type="string",
            value="medium",
            fact_layer="inferred",
            verification_status="candidate",
            confidence=0.6,
            confidence_method_version="confidence_v1",
            confidence_components={"model_uncertainty": 0.4},
            source_system="agent",
            source_entity_type="research_report",
            observed_at=beijing_now(),
            evidence={},
        )

    assert missing.value.error_code == "FACT_INFERENCE_EVIDENCE_REQUIRED"

    source = _source(db, customer, external_id="inference-source")
    supporting = _industry_fact(db, customer, source)
    inferred = append_fact(
        db,
        customer_id=customer.id,
        subject_type="customer",
        fact_key="behavior.inferred.churn_risk",
        value_type="string",
        value="medium",
        fact_layer="inferred",
        verification_status="candidate",
        confidence=0.6,
        confidence_method_version="confidence_v1",
        confidence_components={"model_uncertainty": 0.4},
        source_system="agent",
        source_entity_type="research_report",
        observed_at=beijing_now(),
        evidence={"fact_ids": [supporting.id]},
        rule_version="churn_risk_v1",
    )
    assert inferred.evidence_json["fact_ids"] == [supporting.id]


def test_derived_fact_inherits_highest_evidence_classification(db):
    customer = _customer(db, "inferred-classification")
    restricted = append_fact(
        db,
        customer_id=customer.id,
        subject_type="customer",
        fact_key="behavior.confirmed.relationship_note",
        value_type="string",
        value="Restricted account note",
        fact_layer="confirmed",
        verification_status="verified",
        confidence=1,
        confidence_method_version="confidence_v1",
        confidence_components={"human_confirmation": 1},
        source_system="manual",
        source_entity_type="customer",
        observed_at=beijing_now(),
        reviewed_by=1,
        reviewed_at=beijing_now(),
    )

    inferred = append_fact(
        db,
        customer_id=customer.id,
        subject_type="customer",
        fact_key="behavior.inferred.churn_risk",
        value_type="string",
        value="medium",
        fact_layer="inferred",
        verification_status="candidate",
        confidence=0.6,
        confidence_method_version="confidence_v1",
        confidence_components={"model_uncertainty": 0.4},
        source_system="agent",
        source_entity_type="research_report",
        observed_at=beijing_now(),
        evidence={"fact_ids": [restricted.id]},
        rule_version="churn_risk_v1",
    )

    assert restricted.data_classification == "restricted_internal"
    assert inferred.data_classification == "restricted_internal"


def test_cross_customer_direct_source_and_evidence_are_rejected_without_leaking_ids(db):
    left = _customer(db, "cross-left")
    right = _customer(db, "cross-right")
    left_source = _source(db, left, external_id="cross-left")
    right_source = _source(db, right, external_id="cross-right")
    fact = _industry_fact(db, left, left_source)

    with pytest.raises(CustomerDomainError) as direct:
        _industry_fact(db, left, right_source)
    assert direct.value.error_code == "CUSTOMER_REFERENCE_INVALID"
    assert str(left.id) not in str(direct.value)
    assert str(right.id) not in str(direct.value)

    with pytest.raises(CustomerDomainError) as link:
        link_fact_evidence(
            db,
            fact_id=fact.id,
            evidence_kind="source_record",
            source_record_id=right_source.id,
            relation_type="supports",
            evidence_content_hash=right_source.content_hash,
            locator={"json_path": "$.industry"},
        )
    assert link.value.error_code == "CUSTOMER_REFERENCE_INVALID"
    assert str(left.id) not in str(link.value)
    assert str(right.id) not in str(link.value)


def test_evidence_link_requires_exact_hash_and_locator_and_is_append_only_idempotent(db):
    customer = _customer(db, "evidence")
    source = _source(db, customer, external_id="evidence")
    fact = _industry_fact(db, customer, source)
    initial_seq = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as bad_hash:
        link_fact_evidence(
            db,
            fact_id=fact.id,
            evidence_kind="source_record",
            source_record_id=source.id,
            relation_type="supports",
            evidence_content_hash="0" * 64,
            locator={"json_path": "$.industry"},
        )
    assert bad_hash.value.error_code == "EVIDENCE_HASH_MISMATCH"

    first = link_fact_evidence(
        db,
        fact_id=fact.id,
        evidence_kind="source_record",
        source_record_id=source.id,
        relation_type="supports",
        evidence_content_hash=source.content_hash,
        locator={"json_path": "$.industry"},
    )
    seq_after_first = customer.profile_input_seq
    replay = link_fact_evidence(
        db,
        fact_id=fact.id,
        evidence_kind="source_record",
        source_record_id=source.id,
        relation_type="supports",
        evidence_content_hash=source.content_hash,
        locator={"json_path": "$.industry"},
    )

    assert replay.id == first.id
    assert first.locator_json == {"json_path": "$.industry"}
    assert seq_after_first == initial_seq + 1
    assert customer.profile_input_seq == seq_after_first
    assert db.query(CustomerFactEvidenceLink).count() == 1


def test_fact_conflict_requires_same_key_active_incompatible_facts_and_has_no_winner(db):
    customer = _customer(db, "conflict")
    source = _source(db, customer, external_id="conflict")
    left = _industry_fact(db, customer, source, value="Hair products")
    right = _industry_fact(
        db,
        customer,
        source,
        value="Textiles",
        observed_at=left.observed_at + timedelta(seconds=1),
    )
    initial_seq = customer.profile_input_seq
    first = open_fact_conflict(db, left.id, right.id, detection_rule_version="conflict_v1")
    seq_after_first = customer.profile_input_seq
    replay = open_fact_conflict(db, right.id, left.id, detection_rule_version="conflict_v1")

    assert first.id == replay.id
    assert first.left_fact_id < first.right_fact_id
    assert first.status == "open"
    assert first.resolution_fact_id is None
    assert left.verification_status != "rejected"
    assert right.verification_status != "rejected"
    assert seq_after_first == initial_seq + 1
    assert customer.profile_input_seq == seq_after_first


def test_fact_conflict_rejects_compatible_or_non_overlapping_facts(db):
    customer = _customer(db, "no-conflict")
    source = _source(db, customer, external_id="no-conflict")
    left = _industry_fact(db, customer, source, value="Hair")
    same = _industry_fact(
        db,
        customer,
        source,
        value="Hair",
        observed_at=left.observed_at + timedelta(seconds=1),
    )
    with pytest.raises(CustomerDomainError) as compatible:
        open_fact_conflict(db, left.id, same.id, detection_rule_version="conflict_v1")
    assert compatible.value.error_code == "FACTS_NOT_IN_CONFLICT"

    stale_observed = beijing_now() - timedelta(days=400)
    stale_left = _industry_fact(
        db,
        customer,
        source,
        value="Old Hair",
        observed_at=stale_observed,
    )
    stale_right = _industry_fact(
        db,
        customer,
        source,
        value="Old Textiles",
        observed_at=stale_observed + timedelta(seconds=1),
    )
    with pytest.raises(CustomerDomainError) as stale:
        open_fact_conflict(
            db,
            stale_left.id,
            stale_right.id,
            detection_rule_version="conflict_v1",
        )
    assert stale.value.error_code == "FACTS_NOT_IN_CONFLICT"


def test_customer_event_replay_is_idempotent_and_current_order_activates_inactive(db):
    customer = _customer(db, "event-current")
    customer.relationship_stage = "inactive"
    customer.relationship_stage_changed_at = beijing_now() - timedelta(days=30)
    customer.relationship_stage_reason = "manual_inactivation"
    db.flush()
    initial_seq = customer.profile_input_seq
    order_time = beijing_now()
    first = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id="ORDER-CURRENT",
        event_title="有效订单",
        event_payload={"is_valid_business_order": True},
        occurred_at=order_time,
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
        transition_condition_met=True,
    )
    seq_after_first = customer.profile_input_seq
    replay = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id="ORDER-CURRENT",
        event_title="有效订单重放",
        event_payload={"is_valid_business_order": True},
        occurred_at=order_time,
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
        transition_condition_met=True,
    )

    assert first.id == replay.id
    assert customer.relationship_stage == "active_customer"
    assert customer.relationship_stage_changed_at == order_time
    assert seq_after_first == initial_seq + 1
    assert customer.profile_input_seq == seq_after_first


def test_new_order_on_active_customer_does_not_reset_stage_start_time(db):
    customer = _customer(db, "event-already-active")
    active_since = beijing_now() - timedelta(days=60)
    customer.relationship_stage = "active_customer"
    customer.relationship_stage_changed_at = active_since
    customer.relationship_stage_reason = "first_valid_order"
    db.flush()

    append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id="ORDER-REPEAT-ACTIVE",
        event_title="活跃客户新订单",
        event_payload={"is_valid_business_order": True},
        occurred_at=beijing_now(),
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
        transition_condition_met=True,
    )

    assert customer.relationship_stage == "active_customer"
    assert customer.relationship_stage_changed_at == active_since
    assert customer.relationship_stage_reason == "first_valid_order"


def test_historical_order_replay_is_recorded_but_cannot_reactivate_inactive(db):
    customer = _customer(db, "event-history")
    inactive_at = beijing_now()
    customer.relationship_stage = "inactive"
    customer.relationship_stage_changed_at = inactive_at
    customer.relationship_stage_reason = "manual_inactivation"
    db.flush()

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id="ORDER-HISTORY",
        event_title="历史有效订单补录",
        event_payload={"is_valid_business_order": True, "historical_replay": True},
        occurred_at=inactive_at - timedelta(days=90),
        target_relationship_stage="active_customer",
        transition_trigger="historical_order_replay",
        transition_condition_met=True,
    )

    assert event.id is not None
    assert customer.relationship_stage == "inactive"
    assert customer.relationship_stage_changed_at == inactive_at


def test_old_order_timestamp_cannot_reactivate_inactive_even_with_current_trigger(db):
    customer = _customer(db, "event-old-valid-trigger")
    inactive_at = beijing_now()
    customer.relationship_stage = "inactive"
    customer.relationship_stage_changed_at = inactive_at
    customer.relationship_stage_reason = "manual_inactivation"
    db.flush()

    append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id="ORDER-OLD-WITH-CURRENT-TRIGGER",
        event_title="迟到的历史订单同步",
        event_payload={"is_valid_business_order": True},
        occurred_at=inactive_at - timedelta(seconds=1),
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
        transition_condition_met=True,
    )

    assert customer.relationship_stage == "inactive"
    assert customer.relationship_stage_changed_at == inactive_at


def test_invalid_relationship_transition_rejects_entire_event_mutation(db):
    customer = _customer(db, "event-invalid")
    before_seq = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as invalid:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="relationship.stage_changed",
            event_source="manual",
            source_ref_type="customer",
            source_ref_id=str(customer.id),
            event_title="非法阶段推进",
            event_payload={},
            occurred_at=beijing_now(),
            target_relationship_stage="developing",
            transition_trigger="sales_development_ready",
            transition_condition_met=True,
            has_primary_assignment=False,
            has_open_opportunity=True,
        )
    assert invalid.value.error_code == "RELATIONSHIP_TRANSITION_INVALID"
    assert db.query(CustomerEvent).filter_by(customer_id=customer.id).count() == 0
    assert customer.profile_input_seq == before_seq
