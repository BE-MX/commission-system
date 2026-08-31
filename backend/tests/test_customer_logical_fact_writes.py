from datetime import timedelta

import pytest

from app.core.time import beijing_now
from app.customer.identity_service import CustomerDomainError
from app.customer.models import (
    CustomerChangeProposal,
    CustomerConversation,
    CustomerObjectOwnership,
    CustomerOpportunity,
    CustomerOrder,
)
from tests.test_customer_facts import _customer, _industry_fact, _source
from tests.test_customer_governance_policy import _digest, _profile


def _move(db, *, object_type, row, storage, target, proposal):
    db.add(CustomerObjectOwnership(
        object_type=object_type, object_id=row.id,
        storage_customer_id=storage.id, current_customer_id=target.id,
        ownership_version=1, last_change_proposal_id=proposal.id,
        last_action_type="split",
    ))
    db.flush()


def test_append_fact_accepts_logical_source_and_superseded_fact(db):
    storage = _customer(db, "logical-fact-storage")
    target = _customer(db, "logical-fact-target")
    other = _customer(db, "logical-fact-other")
    source = _source(db, storage, external_id="logical-fact-source")
    profile = _profile(db, storage)
    proposal = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash=_digest("logical-fact-move"),
        status="executed", expires_at=beijing_now() + timedelta(days=1),
    )
    db.add(proposal)
    db.flush()
    _move(
        db, object_type="source_record", row=source,
        storage=storage, target=target, proposal=proposal,
    )

    first = _industry_fact(db, target, source)
    assert first.customer_id == target.id
    with pytest.raises(CustomerDomainError, match="Customer domain operation rejected"):
        _industry_fact(db, other, source, value="cross-owner")

    _move(
        db, object_type="fact", row=first,
        storage=target, target=storage, proposal=proposal,
    )
    db.query(CustomerObjectOwnership).filter_by(
        object_type="source_record", object_id=source.id,
    ).one().current_customer_id = storage.id
    db.flush()
    replacement = _industry_fact(
        db, storage, source, value="replacement", supersedes_fact_id=first.id,
    )
    assert replacement.customer_id == storage.id
    with pytest.raises(CustomerDomainError):
        _industry_fact(
            db, other, source, value="bad replacement",
            supersedes_fact_id=first.id,
        )


def test_fact_subject_roots_follow_effective_owner(db):
    storage = _customer(db, "logical-subject-storage")
    target = _customer(db, "logical-subject-target")
    profile = _profile(db, storage)
    proposal = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash=_digest("logical-subject-move"),
        status="executed", expires_at=beijing_now() + timedelta(days=1),
    )
    conversation = CustomerConversation(
        customer_id=storage.id, source_system="manual", source_account_key="global",
        external_conversation_id="logical-subject", channel="email",
        conversation_status="active",
    )
    order_source = _source(db, storage, external_id="logical-subject-order")
    order = CustomerOrder(
        customer_id=storage.id, source_system="manual", source_account_key="global",
        external_order_id="logical-subject", order_status="confirmed",
        amount_usd=1, is_valid_business_order=True,
        source_record_id=order_source.id, source_hash="a" * 64,
        synced_at=beijing_now(),
    )
    opportunity = CustomerOpportunity(
        customer_id=storage.id, opportunity_type="manual", source="manual",
        source_system="manual", source_account_key="global",
        source_key="logical-subject", priority_level="A", confidence_score=80,
        urgency="high", title="Logical subject", product_requirement_json={},
        competitor_json={}, evidence_fact_ids=[], status="pending",
        stage_entered_at=beijing_now(),
    )
    db.add_all([proposal, conversation, order, opportunity])
    db.flush()
    _move(
        db, object_type="source_record", row=order_source,
        storage=storage, target=target, proposal=proposal,
    )
    for object_type, row in (
        ("conversation", conversation), ("order", order),
        ("opportunity", opportunity),
    ):
        _move(
            db, object_type=object_type, row=row,
            storage=storage, target=target, proposal=proposal,
        )
        fact = _industry_fact(
            db, target, order_source, value=f"logical-{object_type}",
            subject_type=object_type, subject_id=row.id,
        )
        assert fact.customer_id == target.id
        assert fact.subject_id == row.id
        with pytest.raises(CustomerDomainError):
            _industry_fact(
                db, storage, order_source, value=f"cross-{object_type}",
                subject_type=object_type, subject_id=row.id,
            )
