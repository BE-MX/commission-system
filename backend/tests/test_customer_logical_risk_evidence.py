from datetime import timedelta

import pytest

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.customer.governance_policy_contract import canonical_value_hash
from app.customer.models import (
    CustomerChangeProposal,
    CustomerEvent,
    CustomerFactEvidenceLink,
    CustomerObjectOwnership,
)
from app.customer.proposal_service import (
    ProposalConflict,
    approve_proposal,
    create_proposal,
    execute_proposal,
    submit_proposal,
)
from tests.test_customer_governance_policy import (
    _customer,
    _digest,
    _fact,
    _human,
    _profile,
)


def test_material_risk_lifecycle_links_logically_owned_storage_fact(db):
    proposer = _human(db, "logical-risk")
    approver = ArkUser(
        username="logical-risk-approver", password_hash="test-only",
        real_name="Logical Risk Approver", is_active=True,
    )
    storage = _customer(db, "logical-risk-storage")
    target = _customer(db, "logical-risk-target")
    other = _customer(db, "logical-risk-other")
    source = _fact(db, storage, "logical-risk-source", risk_type="fraud")
    storage_profile = _profile(db, storage)
    target_profile = _profile(db, target)
    historical = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=storage_profile.id,
        evidence_fact_ids=[source.id], risk_level="critical",
        data_classification="restricted_internal", visibility_scope="management",
        action_hash=_digest("logical-risk-history"), status="executed",
        expires_at=beijing_now() + timedelta(days=1),
    )
    db.add_all([approver, historical])
    db.flush()
    ownership = CustomerObjectOwnership(
        object_type="fact", object_id=source.id,
        storage_customer_id=storage.id, current_customer_id=target.id,
        ownership_version=1, last_change_proposal_id=historical.id,
        last_action_type="split",
    )
    db.add(ownership)
    db.flush()
    payload = {
        "customer_id": target.id,
        "profile_version_id": target_profile.id,
        "expected_profile_input_seq": target.profile_input_seq,
        "risk_type": "fraud",
        "source_fact_id": source.id,
        "source_fact_fingerprint": source.fact_fingerprint,
        "source_value_hash": canonical_value_hash(source.value_json),
        "confirmation_reason": "Two-person logical-owner review",
        "evidence_fact_ids": [source.id],
    }
    proposal = create_proposal(
        db, customer_id=target.id, target_customer_id=None,
        action_type="confirm_material_risk",
        payload_schema_version="customer_confirm_material_risk_v1",
        payload_json=payload, profile_version_id=target_profile.id,
        evidence_fact_ids=[source.id], risk_level="critical",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=proposer.id,
    )
    submit_proposal(db, proposal_id=proposal.id, actor_user_id=proposer.id)
    approve_proposal(db, proposal_id=proposal.id, actor_user_id=approver.id)

    ownership.current_customer_id = other.id
    db.flush()
    with pytest.raises(ProposalConflict, match="PROPOSAL_EVIDENCE_INVALID"):
        execute_proposal(
            db, proposal_id=proposal.id, actor_user_id=proposer.id,
            idempotency_key="logical-risk-cross-owner",
        )
    ownership.current_customer_id = target.id
    db.flush()
    execute_proposal(
        db, proposal_id=proposal.id, actor_user_id=proposer.id,
        idempotency_key="logical-risk-execution",
    )

    link = db.query(CustomerFactEvidenceLink).filter_by(
        supporting_fact_id=source.id,
        relation_type="supports",
    ).one()
    assert link.customer_id == target.id
    event = db.query(CustomerEvent).filter_by(
        customer_id=target.id, event_type="risk.material_confirmed",
    ).one()
    assert event.evidence_fact_ids == [source.id]
    assert event.event_payload["source_fact_id"] == source.id
    assert event.event_payload["confirmed_fact_id"] == link.fact_id
    assert source.customer_id == storage.id
