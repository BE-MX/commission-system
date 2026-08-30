from datetime import timedelta

from app.core.time import beijing_now
from app.customer import workflow_service as workflow
from app.customer.models import (
    CustomerChangeProposal,
    CustomerAction,
    CustomerObjectOwnership,
    CustomerOpportunity,
)
from tests.test_customer_governance_policy import _digest
from tests.test_customer_workflow import (
    _account, _grant_permission, _projection, _review, _user,
)


def test_assign_customer_updates_only_logically_owned_open_opportunities(db):
    operator = _user(db, 1951)
    owner = _user(db, 1952)
    replacement = _user(db, 1956)
    _grant_permission(db, operator.id, "customer:write")
    storage, storage_profile = _account(db, code="LOGICAL-ASSIGNMENT-STORAGE")
    target, _ = _account(db, code="LOGICAL-ASSIGNMENT-TARGET")
    other, _ = _account(db, code="LOGICAL-ASSIGNMENT-OTHER")
    moved = CustomerOpportunity(
        id=1960, customer_id=storage.id, opportunity_type="manual", source="manual",
        source_system="manual", source_account_key="global", source_key="moved",
        priority_level="A", confidence_score=80, urgency="high", title="Moved",
        product_requirement_json={}, competitor_json={}, evidence_fact_ids=[],
        status="pending", stage_entered_at=beijing_now(),
    )
    foreign = CustomerOpportunity(
        id=1961, customer_id=storage.id, opportunity_type="manual", source="manual",
        source_system="manual", source_account_key="global", source_key="foreign",
        priority_level="A", confidence_score=80, urgency="high", title="Foreign",
        product_requirement_json={}, competitor_json={}, evidence_fact_ids=[],
        status="pending", stage_entered_at=beijing_now(),
    )
    moved_action = CustomerAction(
        id=1962, customer_id=storage.id, owner_user_id=None, opportunity_id=moved.id,
        action_type="email", thread_group="new_inquiry", priority="high",
        reason="reply", next_action="send", action_date=beijing_now().date(),
        status="pending", feedback_json={}, source_event_ids=[], evidence_fact_ids=[],
        profile_version_id=storage_profile.id,
        source_type="manual", policy_version="test", action_fingerprint="7" * 64,
        evidence_status="valid", generated_at=beijing_now(),
    )
    proposal = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=storage_profile.id,
        evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash=_digest("logical-assignment"),
        status="executed", expires_at=beijing_now() + timedelta(days=1),
    )
    db.add_all([moved, foreign, moved_action, proposal])
    db.flush()
    for object_type, row, current in (
        ("opportunity", moved, target), ("opportunity", foreign, other),
        ("action", moved_action, target),
    ):
        db.add(CustomerObjectOwnership(
            object_type=object_type, object_id=row.id,
            storage_customer_id=storage.id, current_customer_id=current.id,
            ownership_version=1, last_change_proposal_id=proposal.id,
            last_action_type="split",
        ))
    db.flush()

    workflow.assign_customer(
        db, customer_id=target.id, user_id=owner.id,
        assignment_role="primary", assignment_source="manual",
        operated_by=operator.id,
    )

    assert moved.owner_user_id == owner.id
    assert moved_action.owner_user_id == owner.id
    assert foreign.owner_user_id is None

    workflow.transfer_primary_owner(
        db, customer_id=target.id, new_user_id=replacement.id,
        operated_by=operator.id, change_reason="handoff",
    )
    assert moved.owner_user_id == replacement.id
    assert moved_action.owner_user_id == replacement.id
    assert foreign.owner_user_id is None


def test_claim_public_pool_updates_moved_opportunity_and_action(db):
    claimant = _user(db, 1971)
    _grant_permission(db, claimant.id, "customer:write")
    storage, storage_profile = _account(db, code="LOGICAL-CLAIM-STORAGE")
    target, target_profile = _account(db, code="LOGICAL-CLAIM-TARGET")
    _projection(db, target, target_profile)
    _review(
        db, target, review_source="manual", source_ref_id="logical-claim",
        reviewer_id=claimant.id, review_id=1972,
    )
    opportunity = CustomerOpportunity(
        id=1973, customer_id=storage.id, opportunity_type="manual", source="manual",
        source_system="manual", source_account_key="global", source_key="claim",
        priority_level="A", confidence_score=80, urgency="high", title="Claim",
        product_requirement_json={}, competitor_json={}, evidence_fact_ids=[],
        status="pending", stage_entered_at=beijing_now(),
    )
    action = CustomerAction(
        id=1974, customer_id=storage.id, owner_user_id=None,
        opportunity_id=opportunity.id, action_type="email", thread_group="public_pool",
        priority="high", reason="claim", next_action="send",
        action_date=beijing_now().date(), status="pending", feedback_json={},
        source_event_ids=[], evidence_fact_ids=[], profile_version_id=storage_profile.id,
        source_type="manual", policy_version="test", action_fingerprint="8" * 64,
        evidence_status="valid", generated_at=beijing_now(),
    )
    proposal = CustomerChangeProposal(
        customer_id=storage.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=storage_profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash=_digest("logical-claim"),
        status="executed", expires_at=beijing_now() + timedelta(days=1),
    )
    db.add_all([opportunity, action, proposal])
    db.flush()
    for object_type, row in (("opportunity", opportunity), ("action", action)):
        db.add(CustomerObjectOwnership(
            object_type=object_type, object_id=row.id,
            storage_customer_id=storage.id, current_customer_id=target.id,
            ownership_version=1, last_change_proposal_id=proposal.id,
            last_action_type="split",
        ))
    db.flush()

    workflow.claim_public_pool_customer(
        db, customer_id=target.id, claimant_user_id=claimant.id,
        operated_by=claimant.id, scope_type="global", scope_ref_id=None,
        allowed_user_ids={claimant.id}, per_user_quota=10,
    )

    assert opportunity.owner_user_id == claimant.id
    assert action.owner_user_id == claimant.id
