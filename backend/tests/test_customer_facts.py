"""Immutable source, fact, evidence, conflict, and event ledger contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.core.time import beijing_now
from app.customer.contracts import FACT_REGISTRY
from app.customer.fact_service import (
    DirectFactEvidence,
    EventEvidenceRef,
    HumanReviewEvidence,
    append_customer_event,
    append_fact,
    append_source_record,
    link_fact_evidence,
    open_fact_conflict,
)
from app.customer.identity_service import (
    CustomerDomainError,
    attach_identity_candidate,
    confirm_identity,
    resolve_business_context,
)
from app.customer.models import (
    CustomerAccount,
    CustomerAnnotation,
    CustomerContactRelationship,
    CustomerConversation,
    CustomerEvent,
    CustomerFact,
    CustomerFactConflict,
    CustomerFactEvidenceLink,
    CustomerMessage,
    CustomerOrder,
    CustomerQualificationReview,
    CustomerResearchTask,
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


def _human(db, suffix: str) -> ArkUser:
    permission = ArkPermission(
        code="customer:write",
        module="customer",
        action="write",
        label="Customer write test permission",
        kind="action",
        is_legacy=0,
        sort=0,
    )
    role = ArkRole(
        name=f"customer_reviewer_{suffix}",
        label="Test super administrator",
        is_system=True,
        permissions=[permission],
    )
    row = ArkUser(
        username=f"customer-reviewer-{suffix}",
        password_hash="test-only",
        real_name=f"Reviewer {suffix}",
        is_active=True,
        roles=[role],
    )
    db.add(row)
    db.flush()
    return row


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
    }
    values.update(overrides)
    return append_fact(db, **values)


def _order(
    db,
    customer: CustomerAccount,
    *,
    external_id: str,
    valid: bool,
    occurred_at: datetime | None = None,
) -> CustomerOrder:
    business_time = occurred_at or beijing_now()
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="okki",
        source_account_key="tenant-events",
        source_entity_type="order",
        external_record_id=f"source-{external_id}",
        payload_schema_version="okki_order_v1",
        payload_json={"external_order_id": external_id, "valid": valid},
        occurred_at=business_time,
    )
    row = CustomerOrder(
        customer_id=customer.id,
        source_system="okki",
        source_account_key="tenant-events",
        external_order_id=external_id,
        order_status="confirmed",
        account_date=business_time.date(),
        amount_usd=100,
        is_valid_business_order=valid,
        source_record_id=source.id,
        source_hash=source.content_hash,
        synced_at=beijing_now(),
    )
    db.add(row)
    db.flush()
    return row


def test_source_record_replay_is_idempotent_and_changed_content_appends_version(db):
    customer = _customer(db, "source-replay")
    initial_seq = customer.profile_input_seq
    first = _source(db, customer, external_id="about", payload={"industry": "Hair"})
    first_payload = dict(first.payload_json)
    first_seq = customer.profile_input_seq
    replay = _source(db, customer, external_id="about", payload={"industry": "Hair"})
    same_content_new_external_version = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="about",
        source_version="v2",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair"},
    )
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
    assert same_content_new_external_version.id == first.id
    assert first.source_version == "v1"
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


def test_source_fingerprint_collision_material_is_rejected_but_raw_payload_is_preserved(db):
    customer = _customer(db, "source-control-collision")
    raw = append_source_record(
        db,
        customer_id=customer.id,
        source_system="okki",
        source_account_key="source-control-collision",
        source_entity_type="customer",
        external_record_id="raw-control-payload",
        payload_schema_version="okki_customer_v1",
        payload_json={"original_text": "line one\nline two"},
    )
    assert raw.payload_json["original_text"] == "line one\nline two"

    collision_materials = (
        {
            "source_account_key": "source-control-collision",
            "source_entity_type": "customer",
            "external_record_id": "order\x1fEXTERNAL-1",
        },
        {
            "source_account_key": "source-control-collision\x1fcustomer",
            "source_entity_type": "order",
            "external_record_id": "EXTERNAL-1",
        },
    )
    for material in collision_materials:
        with pytest.raises(CustomerDomainError) as invalid:
            append_source_record(
                db,
                customer_id=customer.id,
                source_system="okki",
                payload_schema_version="okki_customer_v1",
                payload_json={"stable": True},
                **material,
            )
        assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_system", "public_web\x00shadow"),
        ("payload_schema_version", "public_company_page_v1\x1fshadow"),
        ("publisher_key", "example.com\x7fshadow"),
        ("source_family_key", "page\nshadow"),
        ("source_url", "https://example.com/\rshadow"),
        ("source_version", "v1\tshadow"),
    ],
)
def test_source_metadata_rejects_ascii_controls(db, field, value):
    customer = _customer(db, f"source-control-{field}")
    arguments = {
        "customer_id": customer.id,
        "source_system": "public_web",
        "source_account_key": "global",
        "source_entity_type": "company_page",
        "external_record_id": f"source-control-{field}",
        "payload_schema_version": "public_company_page_v1",
        "payload_json": {"industry": "Hair"},
    }
    arguments[field] = value

    with pytest.raises(CustomerDomainError) as invalid:
        append_source_record(db, **arguments)

    assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


def test_source_replay_monotonically_tightens_security_metadata_once(db):
    customer = _customer(db, "source-security-tightening")
    arguments = {
        "customer_id": customer.id,
        "source_system": "public_web",
        "source_account_key": "global",
        "source_entity_type": "company_page",
        "external_record_id": "source-security-tightening",
        "payload_schema_version": "public_company_page_v1",
        "payload_json": {"industry": "Hair"},
    }
    first = append_source_record(
        db,
        **arguments,
        data_classification="public_business",
        visibility_scope="all_authorized",
        classification_reason="public source",
    )
    before_tightening = customer.profile_input_seq
    tightened = append_source_record(
        db,
        **arguments,
        data_classification="restricted_internal",
        visibility_scope="management",
        classification_reason="sensitive review",
    )
    after_tightening = customer.profile_input_seq
    replay = append_source_record(
        db,
        **arguments,
        data_classification="public_business",
        visibility_scope="all_authorized",
        classification_reason="attempted downgrade",
    )

    assert tightened.id == first.id == replay.id
    assert first.data_classification == "restricted_internal"
    assert first.visibility_scope == "management"
    assert first.classification_reason == "sensitive review"
    assert after_tightening == before_tightening + 1
    assert customer.profile_input_seq == after_tightening


def test_source_security_tightening_fails_closed_for_wider_derivative_graph(db):
    customer = _customer(db, "source-security-derivatives")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="source-security-derivatives-sensitive",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair"},
        visibility_scope="all_authorized",
        occurred_at=beijing_now() - timedelta(days=1),
    )
    base_source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="source-security-derivatives-base",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Beauty"},
        visibility_scope="all_authorized",
        occurred_at=beijing_now() - timedelta(days=1),
    )
    fact_a = _industry_fact(
        db,
        customer,
        base_source,
        value="Hair",
        visibility_scope="all_authorized",
    )
    link_fact_evidence(
        db,
        fact_id=fact_a.id,
        evidence_kind="source_record",
        source_record_id=source.id,
        relation_type="supports",
        evidence_content_hash=source.content_hash,
        locator={"json_path": "$.industry"},
    )
    fact_b = _industry_fact(
        db,
        customer,
        base_source,
        value="Synthetic Hair",
        observed_at=fact_a.observed_at + timedelta(seconds=1),
        visibility_scope="all_authorized",
        direct_evidence=[
            DirectFactEvidence("fact", fact_a.id, {"role": "supporting"}),
        ],
    )
    conflict = open_fact_conflict(
        db,
        fact_a.id,
        fact_b.id,
        detection_rule_version="source_security_v1",
        visibility_scope="all_authorized",
    )
    order = _order(db, customer, external_id="ORDER-SOURCE-SECURITY", valid=True)
    order_source = db.get(CustomerSourceRecord, order.source_record_id)
    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="Order placed",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=order_source.occurred_at,
        evidence_fact_ids=[fact_b.id],
        visibility_scope="all_authorized",
    )
    before_tightening = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as blocked:
        append_source_record(
            db,
            customer_id=customer.id,
            source_system="public_web",
            source_account_key="global",
            source_entity_type="company_page",
            external_record_id="source-security-derivatives-sensitive",
            payload_schema_version="public_company_page_v1",
            payload_json={"industry": "Hair"},
            visibility_scope="management",
            classification_reason="sensitive review",
        )

    assert blocked.value.error_code == "SOURCE_SECURITY_TIGHTENING_REQUIRES_REBUILD"
    assert source.visibility_scope == "all_authorized"
    assert fact_a.visibility_scope == "all_authorized"
    assert fact_b.visibility_scope == "all_authorized"
    assert conflict.visibility_scope == "all_authorized"
    assert event.visibility_scope == "customer_team"
    assert customer.profile_input_seq == before_tightening


def test_source_security_tightening_fails_closed_for_wider_direct_event(db):
    customer = _customer(db, "source-security-event")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_record_id="source-security-event",
        payload_schema_version="alibaba_inquiry_v1",
        payload_json={"subject": "Hair inquiry"},
        visibility_scope="all_authorized",
        occurred_at=beijing_now() - timedelta(days=1),
    )
    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="inquiry.received",
        event_source="alibaba",
        source_ref_type="source_record",
        source_ref_id=str(source.id),
        event_title="Inquiry received",
        event_payload={"channel": "alibaba"},
        payload_schema_version="customer_event_v1",
        occurred_at=source.occurred_at,
        visibility_scope="all_authorized",
    )
    before_tightening = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as blocked:
        append_source_record(
            db,
            customer_id=customer.id,
            source_system="alibaba",
            source_account_key="shop-a",
            source_entity_type="inquiry",
            external_record_id="source-security-event",
            payload_schema_version="alibaba_inquiry_v1",
            payload_json={"subject": "Hair inquiry"},
            visibility_scope="management",
        )

    assert blocked.value.error_code == "SOURCE_SECURITY_TIGHTENING_REQUIRES_REBUILD"
    assert source.visibility_scope == "all_authorized"
    assert event.visibility_scope == "all_authorized"
    assert customer.profile_input_seq == before_tightening


def test_source_security_tightening_fails_closed_for_generic_event_evidence(db):
    customer = _customer(db, "source-security-generic-event-evidence")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="source-security-generic-event-evidence",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair"},
        visibility_scope="all_authorized",
        occurred_at=beijing_now() - timedelta(days=1),
    )
    order = _order(db, customer, external_id="ORDER-GENERIC-EVENT-EVIDENCE", valid=True)
    order_source = db.get(CustomerSourceRecord, order.source_record_id)
    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="Order placed with public evidence",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=order_source.occurred_at,
        evidence_refs=[EventEvidenceRef("source_record", source.id)],
        visibility_scope="all_authorized",
    )
    before_tightening = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as blocked:
        append_source_record(
            db,
            customer_id=customer.id,
            source_system="public_web",
            source_account_key="global",
            source_entity_type="company_page",
            external_record_id="source-security-generic-event-evidence",
            payload_schema_version="public_company_page_v1",
            payload_json={"industry": "Hair"},
            visibility_scope="management",
        )

    assert blocked.value.error_code == "SOURCE_SECURITY_TIGHTENING_REQUIRES_REBUILD"
    assert source.visibility_scope == "all_authorized"
    assert event.visibility_scope == "customer_team"
    assert customer.profile_input_seq == before_tightening


@pytest.mark.parametrize("bind_customer", [False, True])
def test_unbound_source_tightening_checks_contact_identity_events(db, bind_customer):
    source = append_source_record(
        db,
        customer_id=None,
        source_system="alibaba",
        source_account_key="shop-unbound-security",
        source_entity_type="inquiry",
        external_record_id="unbound-contact-identity-source",
        payload_schema_version="alibaba_inquiry_v1",
        payload_json={"buyer_id": "UNBOUND-SECURITY-BUYER"},
        visibility_scope="all_authorized",
    )
    context = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="shop-unbound-security",
        source_entity_type="inquiry",
        external_context_id="unbound-contact-identity-context",
        contact_name="Unbound Buyer",
    )
    actor = _human(db, "unbound-contact-identity-security")
    identity = attach_identity_candidate(
        db,
        contact_id=context.contact.id,
        source_system="alibaba",
        source_account_key="shop-unbound-security",
        identifier_type="buyer_id",
        raw_value="UNBOUND-SECURITY-BUYER",
        source_record_id=source.id,
    )
    confirm_identity(db, identity.id)
    event = append_customer_event(
        db,
        customer_id=context.customer.id,
        event_type="identity.confirmed",
        event_source="manual",
        source_ref_type="identity",
        source_ref_id=str(identity.id),
        event_title="Contact identity confirmed",
        event_payload={"identity_id": identity.id},
        payload_schema_version="customer_event_v1",
        occurred_at=beijing_now(),
        actor_user_id=actor.id,
        visibility_scope="all_authorized",
    )
    before_tightening = context.customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as blocked:
        append_source_record(
            db,
            customer_id=context.customer.id if bind_customer else None,
            source_system="alibaba",
            source_account_key="shop-unbound-security",
            source_entity_type="inquiry",
            external_record_id="unbound-contact-identity-source",
            payload_schema_version="alibaba_inquiry_v1",
            payload_json={"buyer_id": "UNBOUND-SECURITY-BUYER"},
            visibility_scope="management",
        )

    assert blocked.value.error_code == "SOURCE_SECURITY_TIGHTENING_REQUIRES_REBUILD"
    assert source.customer_id is None
    assert source.visibility_scope == "all_authorized"
    assert event.visibility_scope == "all_authorized"
    assert context.customer.profile_input_seq == before_tightening


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


def test_fact_visibility_inherits_management_source(db):
    customer = _customer(db, "fact-management-visibility")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="fact-management-visibility",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair"},
        visibility_scope="management",
        occurred_at=beijing_now(),
    )

    fact = _industry_fact(
        db,
        customer,
        source,
        visibility_scope="all_authorized",
    )

    assert fact.visibility_scope == "management"


def test_fact_status_cannot_exceed_source_promotion_ceiling(db):
    customer = _customer(db, "promotion-ceiling")
    source = _source(db, customer, external_id="promotion-ceiling")

    with pytest.raises(CustomerDomainError) as promoted:
        _industry_fact(
            db,
            customer,
            source,
            verification_status="verified",
        )

    assert promoted.value.error_code == "FACT_PROMOTION_CEILING_EXCEEDED"


def test_confirmed_fact_requires_explicit_human_review_evidence(db):
    customer = _customer(db, "confirmed-review")

    with pytest.raises(CustomerDomainError) as missing:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="behavior.confirmed.relationship_note",
            value_type="string",
            value="Reviewed note",
            fact_layer="confirmed",
            verification_status="verified",
            confidence=1,
            confidence_method_version="confidence_v1",
            confidence_components={"human_confirmation": 1},
            source_system="manual",
            source_entity_type="customer",
            observed_at=beijing_now(),
        )

    assert missing.value.error_code == "FACT_REVIEW_EVIDENCE_REQUIRED"


def test_confirmed_fact_rejects_missing_or_inactive_reviewer(db):
    customer = _customer(db, "confirmed-reviewer-auth")
    source = _source(db, customer, external_id="confirmed-reviewer-auth")
    supporting = _industry_fact(db, customer, source)
    inactive = _human(db, "inactive-confirmed")
    inactive.is_active = False
    db.flush()

    with pytest.raises(CustomerDomainError) as unauthorized:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="behavior.confirmed.relationship_note",
            value_type="string",
            value="Reviewed note",
            fact_layer="confirmed",
            verification_status="verified",
            confidence=1,
            confidence_method_version="confidence_v1",
            confidence_components={"human_confirmation": 1},
            source_system="manual",
            source_entity_type="customer",
            observed_at=beijing_now(),
            human_review=HumanReviewEvidence(
                reviewer_id=inactive.id,
                reviewed_at=beijing_now(),
                review_reference="inactive-reviewer",
                supporting_fact_ids=(supporting.id,),
            ),
        )

    assert unauthorized.value.error_code == "FACT_REVIEWER_UNAUTHORIZED"


def test_public_web_cannot_write_confirmed_fact(db):
    customer = _customer(db, "public-confirmed")
    source = _source(db, customer, external_id="public-confirmed")
    supporting = _industry_fact(db, customer, source)

    with pytest.raises(CustomerDomainError) as promoted:
        _industry_fact(
            db,
            customer,
            source,
            fact_layer="confirmed",
            verification_status="verified",
            human_review=HumanReviewEvidence(
                reviewer_id=1,
                reviewed_at=beijing_now(),
                review_reference="review-public-1",
                supporting_fact_ids=(supporting.id,),
            ),
        )

    assert promoted.value.error_code == "FACT_PROMOTION_CEILING_EXCEEDED"


@pytest.mark.parametrize(
    ("value_type", "value", "error_code"),
    [
        ("string", 4, "FACT_VALUE_INVALID"),
        ("number", True, "FACT_VALUE_TYPE_INVALID"),
        ("boolean", "yes", "FACT_VALUE_TYPE_INVALID"),
        ("date", "not-a-date", "FACT_VALUE_TYPE_INVALID"),
        ("datetime", "2026-08-30", "FACT_VALUE_TYPE_INVALID"),
        ("list", {}, "FACT_VALUE_TYPE_INVALID"),
        ("object", [], "FACT_VALUE_TYPE_INVALID"),
    ],
)
def test_fact_typed_value_validation_rejects_mismatches(
    db,
    value_type,
    value,
    error_code,
):
    customer = _customer(db, f"typed-{value_type}")
    source = _source(db, customer, external_id=f"typed-{value_type}")

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(db, customer, source, value_type=value_type, value=value)

    assert invalid.value.error_code == error_code


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fact_key", "business.industry\x1fshadow"),
        ("value", "Hair\nProducts"),
        ("confidence_method_version", "confidence_v1\x00shadow"),
        ("classification_reason", "review\x7fshadow"),
        ("rule_version", "rule\tshadow"),
    ],
)
def test_fact_string_material_rejects_ascii_controls(db, field, value):
    customer = _customer(db, f"fact-control-{field}")
    source = _source(db, customer, external_id=f"fact-control-{field}")

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(db, customer, source, **{field: value})

    assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


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


def test_fact_confidence_is_quantized_half_up_before_fingerprint_and_storage(db):
    customer = _customer(db, "fact-confidence-quantized")
    source = _source(db, customer, external_id="fact-confidence-quantized")
    observed_at = source.occurred_at
    first = _industry_fact(
        db,
        customer,
        source,
        confidence=0.8,
        observed_at=observed_at,
    )
    seq_after_first = customer.profile_input_seq
    equivalent = _industry_fact(
        db,
        customer,
        source,
        confidence=Decimal("0.8000"),
        observed_at=observed_at,
    )
    rounded_up = _industry_fact(
        db,
        customer,
        source,
        confidence=Decimal("0.80005"),
        observed_at=observed_at,
    )

    assert equivalent.id == first.id
    assert first.confidence == Decimal("0.8000")
    assert rounded_up.id != first.id
    assert rounded_up.confidence == Decimal("0.8001")
    assert customer.profile_input_seq == seq_after_first + 1


def test_fact_confidence_quantization_normalizes_negative_zero_replay(db):
    customer = _customer(db, "fact-confidence-negative-zero")
    source = _source(db, customer, external_id="fact-confidence-negative-zero")
    observed_at = source.occurred_at
    first = _industry_fact(
        db,
        customer,
        source,
        confidence=0,
        observed_at=observed_at,
    )
    seq_after_first = customer.profile_input_seq
    equivalent = _industry_fact(
        db,
        customer,
        source,
        confidence=Decimal("-0.00004"),
        observed_at=observed_at,
    )

    assert equivalent.id == first.id
    assert first.confidence == Decimal("0.0000")
    assert customer.profile_input_seq == seq_after_first


def test_fact_material_status_change_appends_instead_of_replaying(db):
    customer = _customer(db, "fact-status-change")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="okki",
        source_account_key="tenant-facts",
        source_entity_type="customer",
        external_record_id="fact-status-change",
        payload_schema_version="okki_customer_v1",
        payload_json={"industry": "Hair"},
    )
    observed = beijing_now()
    candidate = append_fact(
        db,
        customer_id=customer.id,
        subject_type="customer",
        fact_key="business.industry",
        value_type="string",
        value="Hair",
        fact_layer="source",
        verification_status="candidate",
        confidence=0.8,
        confidence_method_version="confidence_v1",
        confidence_components={"source_authority": 0.8},
        source_system="okki",
        source_entity_type="customer",
        source_record_id=source.id,
        observed_at=observed,
    )
    before_verified = customer.profile_input_seq
    verified = append_fact(
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
        source_system="okki",
        source_entity_type="customer",
        source_record_id=source.id,
        observed_at=observed,
    )

    assert verified.id != candidate.id
    assert customer.profile_input_seq == before_verified + 1


def test_fact_fingerprint_keeps_independent_source_records_distinct(db):
    customer = _customer(db, "fact-lineage-records")
    left_source = _source(
        db,
        customer,
        external_id="publisher-record-left",
        payload={"industry": "Hair"},
    )
    right_source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="publisher-record-right",
        source_version="v1",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair"},
        publisher_key="independent.example",
        source_family_key="independent:right",
        source_url="https://independent.example/about",
    )
    observed = beijing_now()

    left = _industry_fact(db, customer, left_source, value="Hair", observed_at=observed)
    right = _industry_fact(db, customer, right_source, value="Hair", observed_at=observed)

    assert left.id != right.id
    assert left.fact_fingerprint != right.fact_fingerprint


def test_fact_fingerprint_includes_every_direct_evidence_locator(db):
    customer = _customer(db, "fact-lineage-locator")
    source = _source(db, customer, external_id="lineage-locator")
    observed = beijing_now()

    left = _industry_fact(
        db,
        customer,
        source,
        observed_at=observed,
        direct_evidence=[
            DirectFactEvidence("source_record", source.id, {"json_path": "$.industry"})
        ],
    )
    right = _industry_fact(
        db,
        customer,
        source,
        observed_at=observed,
        direct_evidence=[
            DirectFactEvidence("source_record", source.id, {"json_path": "$.industry_label"})
        ],
    )
    replay = _industry_fact(
        db,
        customer,
        source,
        observed_at=observed,
        direct_evidence=[
            DirectFactEvidence("source_record", source.id, {"json_path": "$.industry"})
        ],
    )

    assert left.id != right.id
    assert replay.id == left.id


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


def test_fact_value_type_must_match_registered_key_schema(db):
    customer = _customer(db, "fact-value-schema")
    source = _source(db, customer, external_id="fact-value-schema")

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(
            db,
            customer,
            source,
            value_type="boolean",
            value=True,
        )

    assert invalid.value.error_code == "FACT_VALUE_TYPE_INVALID"


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
        direct_evidence=[
            DirectFactEvidence("conversation", conversation.id, {"field": "customer_request"})
        ],
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


def test_expressed_fact_requires_same_customer_message_or_conversation_evidence(db):
    customer = _customer(db, "expressed-direct-evidence")
    inquiry = append_source_record(
        db,
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="inquiry",
        external_record_id="inquiry-no-direct-message",
        payload_schema_version="alibaba_inquiry_v1",
        payload_json={"color": "gold"},
    )

    with pytest.raises(CustomerDomainError) as missing:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
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

    assert missing.value.error_code == "FACT_DIRECT_EVIDENCE_REQUIRED"


def test_observed_fact_requires_registered_behavior_or_order_object(db):
    customer = _customer(db, "observed-direct-evidence")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="okki",
        source_account_key="tenant-a",
        source_entity_type="order",
        external_record_id="order-observed-source",
        payload_schema_version="okki_order_v1",
        payload_json={"valid": True},
    )

    with pytest.raises(CustomerDomainError) as missing:
        append_fact(
            db,
            customer_id=customer.id,
            subject_type="customer",
            fact_key="commercial.has_valid_order",
            value_type="boolean",
            value=True,
            fact_layer="observed",
            verification_status="verified",
            confidence=1,
            confidence_method_version="confidence_v1",
            confidence_components={"transactional": 1},
            source_record_id=source.id,
            source_system="okki",
            source_entity_type="order",
            observed_at=beijing_now(),
        )

    assert missing.value.error_code == "FACT_DIRECT_EVIDENCE_REQUIRED"


def test_valid_order_fact_must_match_authoritative_order_state_and_source(db):
    customer = _customer(db, "authoritative-valid-order-fact")
    order = _order(
        db,
        customer,
        external_id="ORDER-NOT-VALID",
        valid=False,
    )
    source = db.get(CustomerSourceRecord, order.source_record_id)
    common = {
        "customer_id": customer.id,
        "subject_type": "customer",
        "fact_key": "commercial.has_valid_order",
        "value_type": "boolean",
        "fact_layer": "observed",
        "verification_status": "verified",
        "confidence": 1,
        "confidence_method_version": "confidence_v1",
        "confidence_components": {"order_state": 1},
        "source_system": "okki",
        "source_entity_type": "order",
        "source_record_id": source.id,
        "observed_at": source.occurred_at,
        "direct_evidence": [
            DirectFactEvidence("order", order.id, {"json_path": "$.valid"})
        ],
    }

    fact = append_fact(db, **common, value=False)
    assert fact.value_json == {"value": False}

    with pytest.raises(CustomerDomainError) as forged:
        append_fact(db, **common, value=True)
    assert forged.value.error_code == "FACT_EVIDENCE_INVALID"


def test_message_evidence_inherits_underlying_source_classification(db):
    customer = _customer(db, "message-classification")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="message",
        external_record_id="message-classification-source",
        payload_schema_version="alibaba_message_v1",
        payload_json={"text": "gold"},
    )
    conversation = CustomerConversation(
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        external_conversation_id="message-classification-conversation",
        channel="alibaba",
        conversation_status="active",
        latest_source_record_id=source.id,
    )
    db.add(conversation)
    db.flush()
    message = CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="message-classification-1",
        direction="in",
        sender_type="customer_contact",
        content_type="text",
        content_text="gold",
        attachment_meta_json=[],
        source_record_id=source.id,
        content_hash="a" * 64,
        sent_at=beijing_now(),
        captured_at=beijing_now(),
    )
    db.add(message)
    db.flush()

    fact = append_fact(
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
        source_record_id=source.id,
        source_system="alibaba",
        source_entity_type="message",
        observed_at=beijing_now(),
        data_classification="public_business",
        direct_evidence=[
            DirectFactEvidence("message", message.id, {"text_span": [0, 4]})
        ],
    )

    assert fact.data_classification == "restricted_internal"


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
        direct_evidence=[DirectFactEvidence("fact", supporting.id, {"role": "input"})],
        rule_version="churn_risk_v1",
    )
    assert inferred.evidence_json["fact_ids"] == [supporting.id]


def test_derived_fact_inherits_highest_evidence_classification(db):
    customer = _customer(db, "inferred-classification")
    reviewer = _human(db, "inferred-classification")
    source = _source(db, customer, external_id="confirmed-review-source")
    supporting = _industry_fact(db, customer, source)
    reviewed_at = beijing_now()
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
        human_review=HumanReviewEvidence(
            reviewer_id=reviewer.id,
            reviewed_at=reviewed_at,
            review_reference="manual-review-1",
            supporting_fact_ids=(supporting.id,),
        ),
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
        direct_evidence=[DirectFactEvidence("fact", restricted.id, {"role": "input"})],
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


@pytest.mark.parametrize("relation_status", ["candidate", "disputed", "rejected"])
def test_contact_fact_requires_current_identified_relationship(db, relation_status):
    resolved = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="facts-contact",
        source_entity_type="inquiry",
        external_context_id=f"contact-relation-{relation_status}",
        contact_name="Mina",
    )
    source = _source(db, resolved.customer, external_id=f"contact-{relation_status}")
    relation = db.query(CustomerContactRelationship).filter_by(
        customer_id=resolved.customer.id,
        contact_id=resolved.contact.id,
    ).one()
    relation.verification_status = relation_status
    db.flush()

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(
            db,
            resolved.customer,
            source,
            subject_type="contact",
            subject_id=resolved.contact.id,
        )

    assert invalid.value.error_code == "CUSTOMER_REFERENCE_INVALID"


def test_contact_fact_rejects_archived_contact_and_ended_relationship(db):
    resolved = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="facts-contact",
        source_entity_type="inquiry",
        external_context_id="contact-inactive",
        contact_name="Mina",
    )
    source = _source(db, resolved.customer, external_id="contact-inactive")
    relation = db.query(CustomerContactRelationship).filter_by(
        customer_id=resolved.customer.id,
        contact_id=resolved.contact.id,
    ).one()
    relation.effective_to = beijing_now()
    resolved.contact.record_status = "archived"
    db.flush()

    with pytest.raises(CustomerDomainError) as invalid:
        _industry_fact(
            db,
            resolved.customer,
            source,
            subject_type="contact",
            subject_id=resolved.contact.id,
        )

    assert invalid.value.error_code == "CUSTOMER_REFERENCE_INVALID"


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


def test_fact_evidence_rejects_transitive_cycle_before_insert(db):
    customer = _customer(db, "fact-evidence-cycle")
    source = _source(db, customer, external_id="fact-evidence-cycle")
    fact_a = _industry_fact(db, customer, source, value="Hair")
    fact_b = _industry_fact(
        db,
        customer,
        source,
        value="Synthetic Hair",
        observed_at=fact_a.observed_at + timedelta(seconds=1),
    )
    link_fact_evidence(
        db,
        fact_id=fact_a.id,
        evidence_kind="fact",
        supporting_fact_id=fact_b.id,
        relation_type="supports",
        evidence_content_hash=fact_b.fact_fingerprint,
        locator={"fact_key": fact_b.fact_key},
    )
    before_cycle = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as cycle:
        link_fact_evidence(
            db,
            fact_id=fact_b.id,
            evidence_kind="fact",
            supporting_fact_id=fact_a.id,
            relation_type="supports",
            evidence_content_hash=fact_a.fact_fingerprint,
            locator={"fact_key": fact_a.fact_key},
        )

    assert cycle.value.error_code == "FACT_EVIDENCE_CYCLE"
    assert db.query(CustomerFactEvidenceLink).count() == 1
    assert customer.profile_input_seq == before_cycle


def test_fact_evidence_rejects_cycle_through_direct_fact_evidence(db):
    customer = _customer(db, "fact-evidence-mixed-cycle")
    source = _source(db, customer, external_id="fact-evidence-mixed-cycle")
    fact_a = _industry_fact(db, customer, source, value="Hair")
    fact_b = _industry_fact(
        db,
        customer,
        source,
        value="Synthetic Hair",
        observed_at=fact_a.observed_at + timedelta(seconds=1),
        direct_evidence=[
            DirectFactEvidence("fact", fact_a.id, {"role": "supporting"}),
        ],
    )
    before_cycle = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as cycle:
        link_fact_evidence(
            db,
            fact_id=fact_a.id,
            evidence_kind="fact",
            supporting_fact_id=fact_b.id,
            relation_type="supports",
            evidence_content_hash=fact_b.fact_fingerprint,
            locator={"fact_key": fact_b.fact_key},
        )

    assert cycle.value.error_code == "FACT_EVIDENCE_CYCLE"
    assert db.query(CustomerFactEvidenceLink).count() == 0
    assert customer.profile_input_seq == before_cycle


def test_evidence_locator_and_excerpt_reject_ascii_controls(db):
    customer = _customer(db, "evidence-control")
    source = _source(db, customer, external_id="evidence-control")
    fact = _industry_fact(db, customer, source)

    for locator, excerpt in (
        ({"json_path": "$.industry\x1fshadow"}, None),
        ({"json_path": "$.industry"}, "Hair\nProducts"),
    ):
        with pytest.raises(CustomerDomainError) as invalid:
            link_fact_evidence(
                db,
                fact_id=fact.id,
                evidence_kind="source_record",
                source_record_id=source.id,
                relation_type="supports",
                evidence_content_hash=source.content_hash,
                locator=locator,
                excerpt_text=excerpt,
            )
        assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


def test_evidence_link_rejects_visibility_downgrade_from_management_source(db):
    customer = _customer(db, "evidence-management-visibility")
    fact_source = _source(db, customer, external_id="evidence-management-fact")
    fact = _industry_fact(db, customer, fact_source)
    restricted_source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="evidence-management-source",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Restricted Hair"},
        visibility_scope="management",
    )

    with pytest.raises(CustomerDomainError) as invalid:
        link_fact_evidence(
            db,
            fact_id=fact.id,
            evidence_kind="source_record",
            source_record_id=restricted_source.id,
            relation_type="supports",
            evidence_content_hash=restricted_source.content_hash,
            locator={"json_path": "$.industry"},
        )

    assert invalid.value.error_code == "EVIDENCE_VISIBILITY_SCOPE_INVALID"


def test_evidence_link_security_and_excerpt_are_immutable_material(db):
    customer = _customer(db, "evidence-security-material")
    source = _source(db, customer, external_id="evidence-security-material")
    fact = _industry_fact(db, customer, source)
    first = link_fact_evidence(
        db,
        fact_id=fact.id,
        evidence_kind="source_record",
        source_record_id=source.id,
        relation_type="supports",
        evidence_content_hash=source.content_hash,
        locator={"json_path": "$.industry"},
        excerpt_text="Hair",
        data_classification="public_business",
    )
    before_changed = customer.profile_input_seq
    changed = link_fact_evidence(
        db,
        fact_id=fact.id,
        evidence_kind="source_record",
        source_record_id=source.id,
        relation_type="supports",
        evidence_content_hash=source.content_hash,
        locator={"json_path": "$.industry"},
        excerpt_text="Sensitive Hair",
        data_classification="restricted_internal",
    )

    assert changed.id != first.id
    assert changed.data_classification == "restricted_internal"
    assert changed.excerpt_text == "Sensitive Hair"
    assert customer.profile_input_seq == before_changed + 1


def test_message_evidence_link_inherits_underlying_source_classification(db):
    customer = _customer(db, "evidence-message-classification")
    fact_source = _source(db, customer, external_id="evidence-message-fact")
    fact = _industry_fact(db, customer, fact_source)
    message_source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="message",
        external_record_id="evidence-message-source",
        payload_schema_version="alibaba_message_v1",
        payload_json={"text": "evidence"},
    )
    conversation = CustomerConversation(
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        external_conversation_id="evidence-message-conversation",
        channel="alibaba",
        conversation_status="active",
        latest_source_record_id=message_source.id,
    )
    db.add(conversation)
    db.flush()
    message = CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="evidence-message-link-1",
        direction="in",
        sender_type="customer_contact",
        content_type="text",
        content_text="evidence",
        attachment_meta_json=[],
        source_record_id=message_source.id,
        content_hash="e" * 64,
        sent_at=beijing_now(),
        captured_at=beijing_now(),
    )
    db.add(message)
    db.flush()

    link = link_fact_evidence(
        db,
        fact_id=fact.id,
        evidence_kind="message",
        message_id=message.id,
        relation_type="supports",
        evidence_content_hash=message.content_hash,
        locator={"start_char": 0, "end_char": 8},
        data_classification="public_business",
    )

    assert link.data_classification == "restricted_internal"


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


def test_fact_conflict_type_and_visibility_are_immutable_material(db):
    customer = _customer(db, "conflict-material")
    source = _source(db, customer, external_id="conflict-material")
    left = _industry_fact(db, customer, source, value="Hair products")
    right = _industry_fact(
        db,
        customer,
        source,
        value="Textiles",
        observed_at=left.observed_at + timedelta(seconds=1),
    )
    first = open_fact_conflict(
        db,
        left.id,
        right.id,
        detection_rule_version="conflict_v1",
        conflict_type="contradictory",
        visibility_scope="customer_team",
    )
    before_changed = customer.profile_input_seq
    changed = open_fact_conflict(
        db,
        left.id,
        right.id,
        detection_rule_version="conflict_v1",
        conflict_type="identity_collision",
        visibility_scope="management",
    )

    assert changed.id != first.id
    assert changed.conflict_type == "identity_collision"
    assert changed.visibility_scope == "management"
    assert customer.profile_input_seq == before_changed + 1

    with pytest.raises(CustomerDomainError) as invalid_visibility:
        open_fact_conflict(
            db,
            left.id,
            right.id,
            detection_rule_version="conflict_v1",
            visibility_scope="public",
        )
    assert invalid_visibility.value.error_code == "VISIBILITY_SCOPE_INVALID"


def test_fact_conflict_inherits_visibility_and_rejects_control_material(db):
    customer = _customer(db, "conflict-security-boundary")
    public_source = _source(db, customer, external_id="conflict-security-public")
    management_source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="conflict-security-management",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Textiles"},
        visibility_scope="management",
        occurred_at=beijing_now(),
    )
    left = _industry_fact(db, customer, public_source, value="Hair")
    right = _industry_fact(
        db,
        customer,
        management_source,
        value="Textiles",
        observed_at=left.observed_at + timedelta(seconds=1),
    )

    conflict = open_fact_conflict(
        db,
        left.id,
        right.id,
        detection_rule_version="conflict_v1",
        visibility_scope="all_authorized",
    )
    assert conflict.visibility_scope == "management"

    with pytest.raises(CustomerDomainError) as invalid:
        open_fact_conflict(
            db,
            left.id,
            right.id,
            detection_rule_version="conflict_v1\x1fshadow",
        )
    assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


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
    order = _order(db, customer, external_id="ORDER-CURRENT", valid=True)
    initial_seq = customer.profile_input_seq
    order_time = db.get(CustomerSourceRecord, order.source_record_id).occurred_at
    first = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="有效订单",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=order_time,
        evidence_refs=[EventEvidenceRef("order", order.id)],
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
    )
    seq_after_first = customer.profile_input_seq
    replay = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="有效订单",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=order_time,
        evidence_refs=[EventEvidenceRef("order", order.id)],
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
    )

    assert first.id == replay.id
    assert customer.relationship_stage == "active_customer"
    assert customer.relationship_stage_changed_at == order_time
    assert seq_after_first == initial_seq + 1
    assert customer.profile_input_seq == seq_after_first


def test_event_title_and_summary_are_immutable_fingerprint_material(db):
    customer = _customer(db, "event-title-summary")
    order = _order(db, customer, external_id="ORDER-TITLE-SUMMARY", valid=True)
    occurred = db.get(CustomerSourceRecord, order.source_record_id).occurred_at
    event_args = {
        "customer_id": customer.id,
        "event_type": "order.placed",
        "event_source": "okki",
        "source_ref_type": "order",
        "source_ref_id": str(order.id),
        "event_payload": {"is_valid_business_order": True},
        "payload_schema_version": "customer_event_v1",
        "occurred_at": occurred,
        "evidence_refs": [EventEvidenceRef("order", order.id)],
    }
    first = append_customer_event(
        db,
        event_title="订单已确认",
        event_summary="客户本期订单",
        **event_args,
    )
    exact_replay = append_customer_event(
        db,
        event_title="订单已确认",
        event_summary="客户本期订单",
        **event_args,
    )
    changed_title = append_customer_event(
        db,
        event_title="客户订单已确认",
        event_summary="客户本期订单",
        **event_args,
    )
    changed_summary = append_customer_event(
        db,
        event_title="订单已确认",
        event_summary="客户追加订单",
        **event_args,
    )

    assert exact_replay.id == first.id
    assert changed_title.id != first.id
    assert changed_summary.id not in {first.id, changed_title.id}


def test_event_material_payload_change_appends_new_immutable_event(db):
    customer = _customer(db, "event-payload-change")
    order = _order(db, customer, external_id="ORDER-EVENT-PAYLOAD", valid=True)
    occurred = db.get(CustomerSourceRecord, order.source_record_id).occurred_at
    first = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="订单事件",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        evidence_refs=[EventEvidenceRef("order", order.id)],
    )
    before_changed = customer.profile_input_seq
    changed = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="订单事件",
        event_payload={"is_valid_business_order": True, "historical_replay": True},
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        evidence_refs=[EventEvidenceRef("order", order.id)],
    )

    assert changed.id != first.id
    assert customer.profile_input_seq == before_changed + 1


def test_fact_value_type_is_part_of_immutable_material(db, monkeypatch):
    customer = _customer(db, "fact-value-type")
    source = _source(db, customer, external_id="fact-value-type")
    test_registry = dict(FACT_REGISTRY)
    test_registry["business.industry"] = replace(
        FACT_REGISTRY["business.industry"],
        value_types=frozenset({"string", "number"}),
    )
    monkeypatch.setattr("app.customer.fact_service.FACT_REGISTRY", test_registry)
    observed = source.occurred_at
    string_fact = _industry_fact(
        db,
        customer,
        source,
        value="1",
        value_type="string",
        observed_at=observed,
    )
    before_number = customer.profile_input_seq
    number_fact = _industry_fact(
        db,
        customer,
        source,
        value=Decimal("1"),
        value_type="number",
        observed_at=observed,
    )
    number_replay = _industry_fact(
        db,
        customer,
        source,
        value=1.0,
        value_type="number",
        observed_at=observed,
    )

    assert number_fact.id != string_fact.id
    assert number_replay.id == number_fact.id
    assert string_fact.value_type == "string"
    assert number_fact.value_type == "number"
    assert type(number_fact.value_json["value"]) in {int, float}
    assert customer.profile_input_seq == before_number + 1


def test_fact_classification_reason_is_part_of_immutable_material(db):
    customer = _customer(db, "fact-classification-reason")
    source = _source(db, customer, external_id="fact-classification-reason")
    observed = source.occurred_at
    first = _industry_fact(
        db,
        customer,
        source,
        observed_at=observed,
        classification_reason="initial source review",
    )
    before_changed = customer.profile_input_seq
    changed = _industry_fact(
        db,
        customer,
        source,
        observed_at=observed,
        classification_reason="corrected source review",
    )

    assert changed.id != first.id
    assert changed.classification_reason == "corrected source review"
    assert customer.profile_input_seq == before_changed + 1


def test_event_security_and_importance_material_append_new_immutable_event(db):
    customer = _customer(db, "event-security-material")
    order = _order(db, customer, external_id="ORDER-EVENT-SECURITY", valid=True)
    occurred = db.get(CustomerSourceRecord, order.source_record_id).occurred_at
    first = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="订单事件",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        evidence_refs=[EventEvidenceRef("order", order.id)],
        importance="normal",
        visibility_scope="customer_team",
    )
    before_changed = customer.profile_input_seq
    changed = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="订单事件",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        evidence_refs=[EventEvidenceRef("order", order.id)],
        importance="high",
        data_classification="restricted_internal",
        visibility_scope="management",
    )

    assert changed.id != first.id
    assert changed.importance == "high"
    assert changed.data_classification == "restricted_internal"
    assert changed.visibility_scope == "management"
    assert customer.profile_input_seq == before_changed + 1


def test_new_order_on_active_customer_does_not_reset_stage_start_time(db):
    customer = _customer(db, "event-already-active")
    active_since = beijing_now() - timedelta(days=60)
    customer.relationship_stage = "active_customer"
    customer.relationship_stage_changed_at = active_since
    customer.relationship_stage_reason = "first_valid_order"
    db.flush()

    order = _order(db, customer, external_id="ORDER-REPEAT-ACTIVE", valid=True)
    append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="活跃客户新订单",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=beijing_now(),
        evidence_refs=[EventEvidenceRef("order", order.id)],
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
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

    order = _order(
        db,
        customer,
        external_id="ORDER-HISTORY",
        valid=True,
        occurred_at=inactive_at - timedelta(days=90),
    )
    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="历史有效订单补录",
        event_payload={"is_valid_business_order": True, "historical_replay": True},
        payload_schema_version="customer_event_v1",
        occurred_at=inactive_at - timedelta(days=90),
        evidence_refs=[EventEvidenceRef("order", order.id)],
        target_relationship_stage="active_customer",
        transition_trigger="historical_order_replay",
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

    order = _order(
        db,
        customer,
        external_id="ORDER-OLD-WITH-CURRENT-TRIGGER",
        valid=True,
        occurred_at=inactive_at - timedelta(seconds=1),
    )
    append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="迟到的历史订单同步",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=inactive_at - timedelta(seconds=1),
        evidence_refs=[EventEvidenceRef("order", order.id)],
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
    )

    assert customer.relationship_stage == "inactive"
    assert customer.relationship_stage_changed_at == inactive_at


def test_forged_transition_boolean_cannot_activate_without_valid_order(db):
    customer = _customer(db, "event-forged-condition")
    customer.relationship_stage = "inactive"
    customer.relationship_stage_changed_at = beijing_now() - timedelta(days=1)
    order = _order(db, customer, external_id="ORDER-INVALID", valid=False)
    db.flush()

    with pytest.raises(CustomerDomainError) as invalid:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="order.placed",
            event_source="okki",
            source_ref_type="order",
            source_ref_id=str(order.id),
            event_title="伪造有效订单",
            event_payload={"is_valid_business_order": True},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            evidence_refs=[EventEvidenceRef("order", order.id)],
            target_relationship_stage="active_customer",
            transition_trigger="valid_order",
            transition_condition_met=True,
        )

    assert invalid.value.error_code == "RELATIONSHIP_TRANSITION_INVALID"
    assert customer.relationship_stage == "inactive"


def test_old_order_business_time_cannot_be_overridden_by_event_time(db):
    customer = _customer(db, "event-authoritative-order-time")
    inactive_at = beijing_now() - timedelta(days=1)
    customer.relationship_stage = "inactive"
    customer.relationship_stage_changed_at = inactive_at
    order = _order(
        db,
        customer,
        external_id="ORDER-OLD-BUSINESS-TIME",
        valid=True,
        occurred_at=inactive_at - timedelta(days=90),
    )
    db.flush()

    append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="伪造当前事件时间",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=beijing_now(),
        evidence_refs=[EventEvidenceRef("order", order.id)],
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
    )

    assert customer.relationship_stage == "inactive"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", "order.placed\x1fshadow"),
        ("event_source", "okki\x00shadow"),
        ("source_ref_type", "order\nshadow"),
        ("source_ref_id", "1\x7fshadow"),
        ("event_title", "Order\rPlaced"),
        ("event_summary", "Summary\tShadow"),
        ("payload_schema_version", "customer_event_v1\x1fshadow"),
    ],
)
def test_event_string_material_rejects_ascii_controls(db, field, value):
    customer = _customer(db, f"event-control-{field}")
    order = _order(db, customer, external_id=f"ORDER-CONTROL-{field}", valid=True)
    source = db.get(CustomerSourceRecord, order.source_record_id)
    arguments = {
        "customer_id": customer.id,
        "event_type": "order.placed",
        "event_source": "okki",
        "source_ref_type": "order",
        "source_ref_id": str(order.id),
        "event_title": "Order placed",
        "event_summary": "Valid order",
        "event_payload": {"is_valid_business_order": True},
        "payload_schema_version": "customer_event_v1",
        "occurred_at": source.occurred_at,
    }
    arguments[field] = value

    with pytest.raises(CustomerDomainError) as invalid:
        append_customer_event(db, **arguments)

    assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


def test_event_payload_string_rejects_ascii_controls_before_schema_validation(db):
    customer = _customer(db, "event-payload-control")
    order = _order(db, customer, external_id="ORDER-PAYLOAD-CONTROL", valid=True)
    source = db.get(CustomerSourceRecord, order.source_record_id)

    with pytest.raises(CustomerDomainError) as invalid:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="order.placed",
            event_source="okki",
            source_ref_type="order",
            source_ref_id=str(order.id),
            event_title="Order placed",
            event_payload={
                "is_valid_business_order": True,
                "historical_replay": "false\nshadow",
            },
            payload_schema_version="customer_event_v1",
            occurred_at=source.occurred_at,
        )

    assert invalid.value.error_code == "ASCII_CONTROL_CHARACTER_INVALID"


def test_event_registry_rejects_unknown_type_and_arbitrary_payload(db):
    customer = _customer(db, "event-registry")
    with pytest.raises(CustomerDomainError) as unknown:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="mystery.happened",
            event_source="manual",
            event_title="Unknown",
            event_payload={},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            actor_user_id=1,
        )
    assert unknown.value.error_code == "EVENT_NOT_REGISTERED"

    order = _order(db, customer, external_id="ORDER-PAYLOAD", valid=True)
    with pytest.raises(CustomerDomainError) as payload:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="order.placed",
            event_source="okki",
            source_ref_type="order",
            source_ref_id=str(order.id),
            event_title="Arbitrary payload",
            event_payload={"is_valid_business_order": True, "admin_override": True},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            evidence_refs=[EventEvidenceRef("order", order.id)],
        )
    assert payload.value.error_code == "EVENT_PAYLOAD_INVALID"


def test_registered_identity_event_accepts_owned_reference_and_active_actor(db):
    customer = _customer(db, "event-identity-reference")
    actor = _human(db, "event-identity-reference")
    identity = attach_identity_candidate(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="event-identity.example",
        verification_status="verified",
    )

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="identity.confirmed",
        event_source="manual",
        source_ref_type="identity",
        source_ref_id=str(identity.id),
        event_title="人工核验身份",
        event_payload={"identity_id": identity.id},
        payload_schema_version="customer_event_v1",
        occurred_at=beijing_now(),
        actor_user_id=actor.id,
    )

    assert event.source_ref_id == str(identity.id)


def test_registered_research_and_annotation_events_validate_owned_references(db):
    customer = _customer(db, "event-research-annotation-reference")
    actor = _human(db, "event-research-annotation-reference")
    now = beijing_now()
    research = CustomerResearchTask(
        customer_id=customer.id,
        task_type="full_research",
        source_ref_type="manual",
        source_ref_id="review-request-1",
        task_status="completed",
        gate_status="not_required",
        result_review_status="accepted",
        selection_reason=[],
        research_policy_version="research_v1",
        task_fingerprint="c" * 64,
        input_snapshot={},
        result_schema_version="customer_research_v1",
        result_json={},
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test research",
        evidence_fact_ids=[],
        lease_generation=0,
        attempt_count=1,
        reviewed_by=actor.id,
        reviewed_at=now,
        finished_at=now,
        created_by=actor.id,
    )
    annotation = CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="note",
        content_schema_version="v1",
        content_json={"text": "Follow up after the show"},
        visibility="customer_team",
        data_classification="internal_business",
        status="active",
        authored_by=actor.id,
    )
    db.add_all([research, annotation])
    db.flush()

    research_event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="research.completed",
        event_source="agent",
        source_ref_type="research_task",
        source_ref_id=str(research.id),
        event_title="背调完成",
        event_payload={"result_status": "completed"},
        payload_schema_version="customer_event_v1",
        occurred_at=now,
    )
    annotation_event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="annotation.created",
        event_source="annotation",
        source_ref_type="annotation",
        source_ref_id=str(annotation.id),
        event_title="新增人工备注",
        event_payload={"annotation_type": "note"},
        payload_schema_version="customer_event_v1",
        occurred_at=now,
        actor_user_id=actor.id,
    )

    assert research_event.source_ref_id == str(research.id)
    assert annotation_event.source_ref_id == str(annotation.id)


def test_private_annotation_cannot_be_promoted_to_shared_event(db):
    customer = _customer(db, "event-private-annotation")
    actor = _human(db, "event-private-annotation")
    annotation = CustomerAnnotation(
        customer_id=customer.id,
        annotation_type="note",
        content_schema_version="v1",
        content_json={"text": "Private note"},
        visibility="private",
        data_classification="restricted_internal",
        status="active",
        authored_by=actor.id,
    )
    db.add(annotation)
    db.flush()

    with pytest.raises(CustomerDomainError) as private:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="annotation.created",
            event_source="annotation",
            source_ref_type="annotation",
            source_ref_id=str(annotation.id),
            event_title="私密备注",
            event_payload={"annotation_type": "note"},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            actor_user_id=actor.id,
        )

    assert private.value.error_code == "PRIVATE_VISIBILITY_NOT_SHAREABLE"


def test_registered_reference_events_reject_unfinished_research_and_candidate_identity(db):
    customer = _customer(db, "event-reference-state")
    actor = _human(db, "event-reference-state")
    identity = attach_identity_candidate(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="candidate-event-identity.example",
    )
    research = CustomerResearchTask(
        customer_id=customer.id,
        task_type="full_research",
        source_ref_type="manual",
        source_ref_id="review-request-pending",
        task_status="pending",
        gate_status="pending",
        result_review_status="pending",
        selection_reason=[],
        research_policy_version="research_v1",
        task_fingerprint="d" * 64,
        input_snapshot={},
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test research",
        evidence_fact_ids=[],
        lease_generation=0,
        attempt_count=0,
        created_by=actor.id,
    )
    db.add(research)
    db.flush()

    with pytest.raises(CustomerDomainError) as unfinished:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="research.completed",
            event_source="agent",
            source_ref_type="research_task",
            source_ref_id=str(research.id),
            event_title="伪造背调完成",
            event_payload={"result_status": "completed"},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
        )
    assert unfinished.value.error_code == "EVENT_REFERENCE_INVALID"

    with pytest.raises(CustomerDomainError) as candidate:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="identity.confirmed",
            event_source="manual",
            source_ref_type="identity",
            source_ref_id=str(identity.id),
            event_title="伪造身份确认",
            event_payload={"identity_id": identity.id},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            actor_user_id=actor.id,
        )
    assert candidate.value.error_code == "EVENT_REFERENCE_INVALID"


def test_identity_conflict_event_validates_disputed_owned_identity_ids(db):
    left = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="event-identity-conflict",
        source_entity_type="inquiry",
        external_context_id="event-identity-conflict-left",
    )
    right = resolve_business_context(
        db,
        source_system="alibaba",
        source_account_key="event-identity-conflict",
        source_entity_type="inquiry",
        external_context_id="event-identity-conflict-right",
    )
    left_identity = attach_identity_candidate(
        db,
        customer_id=left.customer.id,
        source_system="okki",
        source_account_key="event-identity-conflict",
        identifier_type="company_id",
        raw_value="EVENT-IDENTITY-CONFLICT",
    )
    right_identity = attach_identity_candidate(
        db,
        customer_id=right.customer.id,
        source_system="okki",
        source_account_key="event-identity-conflict",
        identifier_type="company_id",
        raw_value="EVENT-IDENTITY-CONFLICT",
    )
    confirm_identity(db, left_identity.id)
    confirm_identity(db, right_identity.id)
    before_event = left.customer.profile_input_seq

    event = append_customer_event(
        db,
        customer_id=left.customer.id,
        event_type="identity.conflict",
        event_source="identity",
        event_title="身份冲突待复核",
        event_payload={"identity_ids": [left_identity.id]},
        payload_schema_version="customer_event_v1",
        occurred_at=beijing_now(),
    )

    assert event.event_payload == {"identity_ids": [left_identity.id]}
    assert left.customer.profile_input_seq == before_event + 1

    with pytest.raises(CustomerDomainError) as cross_customer:
        append_customer_event(
            db,
            customer_id=left.customer.id,
            event_type="identity.conflict",
            event_source="identity",
            event_title="跨客户身份冲突",
            event_payload={"identity_ids": [right_identity.id]},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
        )
    assert cross_customer.value.error_code == "CUSTOMER_REFERENCE_INVALID"


def test_identity_conflict_event_rejects_unknown_or_non_disputed_identity(db):
    customer = _customer(db, "event-forged-identity-conflict")
    identity = attach_identity_candidate(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        identifier_type="website_domain",
        raw_value="not-disputed.example",
    )
    before_event = customer.profile_input_seq

    for identity_ids in ([999999], [identity.id], [], [identity.id, "forged"]):
        with pytest.raises(CustomerDomainError) as invalid:
            append_customer_event(
                db,
                customer_id=customer.id,
                event_type="identity.conflict",
                event_source="identity",
                event_title="伪造身份冲突",
                event_payload={"identity_ids": identity_ids},
                payload_schema_version="customer_event_v1",
                occurred_at=beijing_now(),
            )
        assert invalid.value.error_code in {
            "CUSTOMER_REFERENCE_INVALID",
            "EVENT_REFERENCE_INVALID",
        }
    assert customer.profile_input_seq == before_event


def test_manual_event_rejects_inactive_actor(db):
    customer = _customer(db, "event-inactive-actor")
    actor = _human(db, "event-inactive-actor")
    actor.is_active = False
    db.flush()

    with pytest.raises(CustomerDomainError) as unauthorized:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="relationship.stage_changed",
            event_source="manual",
            source_ref_type="customer",
            source_ref_id=str(customer.id),
            event_title="无权限人工事件",
            event_payload={},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            actor_user_id=actor.id,
        )

    assert unauthorized.value.error_code == "EVENT_ACTOR_UNAUTHORIZED"


def test_event_classification_inherits_message_source(db):
    customer = _customer(db, "event-message-classification")
    source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        source_entity_type="message",
        external_record_id="event-message-source",
        payload_schema_version="alibaba_message_v1",
        payload_json={"text": "hello"},
    )
    conversation = CustomerConversation(
        customer_id=customer.id,
        source_system="alibaba",
        source_account_key="shop-a",
        external_conversation_id="event-message-conversation",
        channel="alibaba",
        conversation_status="active",
        latest_source_record_id=source.id,
    )
    db.add(conversation)
    db.flush()
    message = CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="event-message-1",
        direction="in",
        sender_type="customer_contact",
        content_type="text",
        content_text="hello",
        attachment_meta_json=[],
        source_record_id=source.id,
        content_hash="b" * 64,
        sent_at=beijing_now(),
        captured_at=beijing_now(),
    )
    db.add(message)
    db.flush()

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="message.received",
        event_source="alibaba",
        source_ref_type="message",
        source_ref_id=str(message.id),
        event_title="收到消息",
        event_payload={"direction": "in"},
        payload_schema_version="customer_event_v1",
        occurred_at=message.sent_at,
        data_classification="public_business",
        evidence_refs=[EventEvidenceRef("message", message.id)],
    )

    assert event.data_classification == "restricted_internal"


def test_event_visibility_inherits_management_evidence_fact(db):
    customer = _customer(db, "event-management-visibility")
    management_source = append_source_record(
        db,
        customer_id=customer.id,
        source_system="public_web",
        source_account_key="global",
        source_entity_type="company_page",
        external_record_id="event-management-fact",
        payload_schema_version="public_company_page_v1",
        payload_json={"industry": "Hair"},
        visibility_scope="management",
        occurred_at=beijing_now(),
    )
    management_fact = _industry_fact(db, customer, management_source)
    order = _order(db, customer, external_id="ORDER-EVENT-MANAGEMENT", valid=True)
    occurred = db.get(CustomerSourceRecord, order.source_record_id).occurred_at

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="order.placed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="管理层证据订单",
        event_payload={"is_valid_business_order": True},
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        visibility_scope="all_authorized",
        evidence_fact_ids=[management_fact.id],
    )

    assert event.visibility_scope == "management"


def test_approved_qualification_review_advances_discovered_customer(db):
    customer = _customer(db, "relationship-qualified")
    actor = _human(db, "relationship-qualified")
    reviewed_at = beijing_now()
    review = CustomerQualificationReview(
        customer_id=customer.id,
        review_version=1,
        review_source="manual",
        decision="approved",
        reason_code="qualified",
        scope_type="global",
        is_current=True,
        policy_version="qualification_v1",
        review_snapshot={"identity_status": customer.identity_status},
        decision_request_key="a" * 64,
        reviewed_by=actor.id,
        reviewed_at=reviewed_at,
    )
    db.add(review)
    db.flush()

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="relationship.stage_changed",
        event_source="qualification",
        source_ref_type="qualification_review",
        source_ref_id=str(review.id),
        event_title="资格审核通过",
        event_payload={"reason_code": "qualification_approved"},
        payload_schema_version="customer_event_v1",
        occurred_at=reviewed_at,
        actor_user_id=actor.id,
        target_relationship_stage="qualified",
        transition_trigger="qualification_approved",
    )

    assert event.source_ref_type == "qualification_review"
    assert customer.relationship_stage == "qualified"
    assert customer.relationship_stage_reason == "qualification_approved"


def test_valid_order_relationship_event_advances_active_customer(db):
    customer = _customer(db, "relationship-active-order")
    order = _order(db, customer, external_id="ORDER-STAGE-ACTIVE", valid=True)
    occurred = db.get(CustomerSourceRecord, order.source_record_id).occurred_at

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="relationship.stage_changed",
        event_source="okki",
        source_ref_type="order",
        source_ref_id=str(order.id),
        event_title="有效订单推进成交客户",
        event_payload={
            "reason_code": "valid_order",
            "is_valid_business_order": True,
        },
        payload_schema_version="customer_event_v1",
        occurred_at=occurred,
        target_relationship_stage="active_customer",
        transition_trigger="valid_order",
    )

    assert event.source_ref_type == "order"
    assert customer.relationship_stage == "active_customer"


def test_relationship_stage_event_rejects_source_reference_mismatch(db):
    customer = _customer(db, "relationship-reference-mismatch")
    actor = _human(db, "relationship-reference-mismatch")

    with pytest.raises(CustomerDomainError) as invalid:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="relationship.stage_changed",
            event_source="qualification",
            source_ref_type="customer",
            source_ref_id=str(customer.id),
            event_title="伪造资格推进",
            event_payload={"reason_code": "qualification_approved"},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            actor_user_id=actor.id,
            target_relationship_stage="qualified",
            transition_trigger="qualification_approved",
        )

    assert invalid.value.error_code == "EVENT_REFERENCE_INVALID"


def test_invalid_relationship_transition_rejects_entire_event_mutation(db):
    customer = _customer(db, "event-invalid")
    actor = _human(db, "event-invalid")
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
            event_payload={"reason_code": "sales_development_ready"},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            target_relationship_stage="developing",
            transition_trigger="sales_development_ready",
            transition_condition_met=True,
            has_primary_assignment=False,
            has_open_opportunity=True,
            actor_user_id=actor.id,
        )
    assert invalid.value.error_code == "RELATIONSHIP_TRANSITION_INVALID"
    assert db.query(CustomerEvent).filter_by(customer_id=customer.id).count() == 0
    assert customer.profile_input_seq == before_seq


def test_relationship_stage_event_requires_and_applies_authoritative_transition(db):
    customer = _customer(db, "event-stage-authority")
    actor = _human(db, "event-stage-authority")
    before_event = customer.profile_input_seq

    with pytest.raises(CustomerDomainError) as missing_transition:
        append_customer_event(
            db,
            customer_id=customer.id,
            event_type="relationship.stage_changed",
            event_source="manual",
            source_ref_type="customer",
            source_ref_id=str(customer.id),
            event_title="伪造阶段已变更",
            event_payload={"reason_code": "manual_inactivation"},
            payload_schema_version="customer_event_v1",
            occurred_at=beijing_now(),
            actor_user_id=actor.id,
        )
    assert missing_transition.value.error_code == "RELATIONSHIP_TRANSITION_INVALID"
    assert customer.profile_input_seq == before_event

    event = append_customer_event(
        db,
        customer_id=customer.id,
        event_type="relationship.stage_changed",
        event_source="manual",
        source_ref_type="customer",
        source_ref_id=str(customer.id),
        event_title="人工转为不活跃",
        event_payload={"reason_code": "manual_inactivation"},
        payload_schema_version="customer_event_v1",
        occurred_at=beijing_now(),
        actor_user_id=actor.id,
        target_relationship_stage="inactive",
        transition_trigger="manual_inactivation",
    )

    assert event.id is not None
    assert customer.relationship_stage == "inactive"
    assert customer.relationship_stage_reason == "manual_inactivation"
