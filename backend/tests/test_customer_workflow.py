"""Unified customer opportunity, assignment and radar workflow contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
import inspect
import json
from threading import Barrier, Lock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.time import beijing_now

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.customer import models as customer_models
from app.insight import models as insight_models


NOW = beijing_now().replace(microsecond=0)


def _workflow():
    from app.customer import workflow_service

    return workflow_service


def _user(db, user_id: int) -> ArkUser:
    permission = db.query(ArkPermission).filter_by(code="customer:write").one_or_none()
    if permission is None:
        permission = ArkPermission(
            code="customer:write",
            module="customer",
            action="write",
            label="Edit customer ownership",
        )
        db.add(permission)
        db.flush()
    role = db.query(ArkRole).filter_by(name="workflow_customer_writer").one_or_none()
    if role is None:
        role = ArkRole(
            name="workflow_customer_writer",
            label="Workflow customer writer",
        )
        role.permissions.append(permission)
        db.add(role)
        db.flush()
    row = ArkUser(
        id=user_id,
        username=f"workflow-{user_id}",
        password_hash="test",
        real_name=f"Workflow {user_id}",
        is_active=True,
    )
    row.roles.append(role)
    db.add(row)
    db.flush()
    return row


def _grant_permission(db, user_id: int, code: str) -> None:
    permission = db.query(ArkPermission).filter_by(code=code).one_or_none()
    if permission is None:
        module, action = code.split(":", 1)
        permission = ArkPermission(
            code=code,
            module=module,
            action=action,
            label=code,
        )
        db.add(permission)
        db.flush()
    user = db.get(ArkUser, user_id)
    role = user.roles[0]
    if permission not in role.permissions:
        role.permissions.append(permission)
        db.flush()


def _source_record(db, account, *, record_id: int = 9001):
    row = customer_models.CustomerSourceRecord(
        id=record_id,
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        authority_level="transactional",
        source_entity_type="order",
        external_record_id=f"order-source-{record_id}",
        external_record_key_hash=f"{record_id:064x}",
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test transactional order source",
        payload_schema_version="okki_order_v1",
        payload_json={"record_id": record_id},
        content_hash=f"{record_id + 1:064x}",
        occurred_at=NOW,
        captured_at=NOW,
        processing_status="processed",
    )
    db.add(row)
    db.flush()
    return row


def _account(
    db,
    *,
    code: str = "C-WORKFLOW",
    identity_status: str = "verified",
    relationship_stage: str = "discovered",
    stage_changed_at: datetime = NOW - timedelta(days=30),
):
    row = customer_models.CustomerAccount(
        customer_code=code,
        display_name=code,
        canonical_company_name=f"{code} LLC",
        entity_type="registered_company",
        identity_status=identity_status,
        relationship_stage=relationship_stage,
        relationship_stage_changed_at=stage_changed_at,
        relationship_stage_reason="test_seed",
        record_status="active",
        identity_confidence=1,
        profile_completeness=80,
        profile_input_seq=0,
    )
    db.add(row)
    db.flush()
    version = customer_models.CustomerProfileVersion(
        customer_id=row.id,
        version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1",
        input_seq=0,
        profile_json={
            "identity": {"display_name": code},
            "business": {},
            "contacts": [],
            "engagement": {},
            "commercial": {},
            "preferences": {},
            "behavior": {},
            "opportunities": [],
            "risks": [],
            "quality": {},
        },
        section_hashes={},
        section_data_as_of={},
        evidence_fact_ids=[],
        change_summary={"changes": []},
        compiler_version="customer_profile_compiler_v1",
        profile_fingerprint=f"{row.id:064x}",
        data_as_of=NOW,
        compiled_at=NOW,
    )
    db.add(version)
    db.flush()
    row.current_profile_version_id = version.id
    db.flush()
    return row, version


def _projection(db, account, version, *, blocked=False, cooldown=None):
    row = customer_models.CustomerListProjection(
        customer_id=account.id,
        primary_industry="hair",
        primary_market="US",
        acquisition_source="search",
        primary_product_family="hair_extensions",
        commercial_value_score=0,
        has_valid_order=False,
        valid_order_count=0,
        valid_order_amount_usd=0,
        last_order_at=None,
        last_engagement_at=None,
        engagement_health="new",
        open_opportunity_count=0,
        highest_opportunity_priority=None,
        next_action_at=None,
        global_claim_blocked=blocked,
        global_claim_block_reason="identity_conflict" if blocked else None,
        claim_cooldown_until=cooldown,
        has_active_dnc=False,
        data_quality_score=80,
        profile_version_id=version.id,
        compiled_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _search_result(db, account, *, job_id=100, result_id=101):
    job = customer_models.SearchJob(
        id=job_id,
        profile_id=999,
        name="Qualified search",
        status="completed",
        adapter="agent",
        target_count=10,
        criteria_json={"schema_version": "search_criteria_v1"},
        profile_snapshot={"schema_version": "target_profile_snapshot_v1"},
        policy_version="workflow-v1",
        profile_snapshot_hash=f"{job_id:064x}",
        idempotency_key=f"{job_id + 1:064x}",
        ingestion_receipts={},
        result_count=1,
        created_customer_count=0,
        deduplicated_count=1,
        researched_count=1,
        qualified_count=0,
        provider_usage_json=[],
        cost_status="not_applicable",
        cost_original=0,
        cost_currency=None,
        cost_usd=0,
        attempt_count=1,
        created_by=1,
        created_at=NOW,
        updated_at=NOW,
    )
    result = customer_models.SearchResult(
        id=result_id,
        job_id=job.id,
        customer_id=account.id,
        best_rank=1,
        best_score=90,
        aggregated_score_reasons={"schema_version": "search_score_aggregate_v1", "reasons": []},
        result_status="qualified",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([job, result])
    db.flush()
    return job, result


def _research_task(db, account, *, task_id=201):
    row = customer_models.CustomerResearchTask(
        id=task_id,
        customer_id=account.id,
        task_type="public_pool",
        source_ref_type="public_pool_batch",
        source_ref_id="1",
        tier="T1",
        task_status="completed",
        gate_status="passed",
        result_review_status="accepted",
        selection_reason=[],
        research_policy_version="workflow-v1",
        task_fingerprint=f"{task_id:064x}",
        input_snapshot={"schema_version": "research_input_v1"},
        result_schema_version="customer_research_v1",
        result_json={"claims": [], "citations": []},
        data_classification="internal_business",
        visibility_scope="customer_team",
        classification_reason="test",
        research_summary="accepted",
        evidence_fact_ids=[],
        attempt_count=1,
        lease_generation=1,
        started_at=NOW,
        finished_at=NOW,
        reviewed_by=1,
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def _review(
    db,
    account,
    *,
    review_source: str,
    source_ref_id: str,
    decision: str = "approved",
    reviewer_id: int = 1,
    review_id: int = 301,
    scope_type: str = "global",
    scope_ref_id: str | None = None,
):
    row = customer_models.CustomerQualificationReview(
        id=review_id,
        customer_id=account.id,
        review_version=1,
        review_source=review_source,
        source_ref_id=source_ref_id,
        decision=decision,
        reason_code="qualified" if decision == "approved" else "not_now",
        scope_type=scope_type,
        scope_ref_id=scope_ref_id,
        is_current=True,
        policy_version="workflow-v1",
        review_after=NOW + timedelta(days=30) if decision == "deferred" else None,
        review_snapshot={
            "schema_version": "qualification_review_v1",
            "evidence_fact_ids": [],
            "priority_level": "A",
            "confidence_score": 90,
        },
        decision_request_key=f"{review_id:064x}",
        reviewed_by=reviewer_id,
        reviewed_at=NOW,
        created_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("review_source", ["search_result", "public_pool_research"])
def test_approved_qualification_creates_one_namespaced_opportunity_and_first_action(
    db, review_source,
):
    _user(db, 1)
    account, version = _account(db)
    _projection(db, account, version)
    if review_source == "search_result":
        _job, source = _search_result(db, account)
    else:
        source = _research_task(db, account)
    review = _review(
        db,
        account,
        review_source=review_source,
        source_ref_id=str(source.id),
    )

    first = _workflow().orchestrate_qualification_review(db, review.id)
    second = _workflow().orchestrate_qualification_review(db, review.id)

    opportunity_cls = customer_models.CustomerOpportunity
    action_cls = customer_models.CustomerAction
    assert first.opportunity.id == second.opportunity.id
    assert first.action.id == second.action.id
    assert db.query(opportunity_cls).count() == 1
    assert db.query(action_cls).count() == 1
    assert first.opportunity.customer_id == account.id
    assert first.opportunity.status == "pending"
    if review_source == "search_result":
        assert first.opportunity.source_system == "search"
        assert first.opportunity.source_account_key == "global"
        assert first.opportunity.source_key == f"job:100:result:{source.id}"
    else:
        assert first.opportunity.source_system == "public_pool"
        assert first.opportunity.source_account_key == "global"
        assert first.opportunity.source_key == f"research:{source.task_fingerprint}"
    assert first.opportunity.owner_user_id is None
    assert first.action.customer_id == account.id
    assert first.action.opportunity_id == first.opportunity.id
    assert first.action.owner_user_id is None
    assert first.action.profile_version_id == version.id
    assert first.action.feedback_json["queue_assignment"] == {
        "mode": "public_pool_unassigned",
        "does_not_confer_customer_ownership": True,
        "qualification_review_id": review.id,
    }
    assert db.query(customer_models.CustomerAssignment).count() == 0


@pytest.mark.parametrize("decision", ["deferred", "rejected"])
def test_nonapproved_qualification_creates_no_opportunity_or_action(db, decision):
    _user(db, 1)
    account, version = _account(db)
    _projection(db, account, version)
    _job, source = _search_result(db, account)
    review = _review(
        db,
        account,
        review_source="search_result",
        source_ref_id=str(source.id),
        decision=decision,
    )

    result = _workflow().orchestrate_qualification_review(db, review.id)

    assert result is None
    assert db.query(customer_models.CustomerOpportunity).count() == 0
    assert db.query(customer_models.CustomerAction).count() == 0


def test_qualification_replay_after_assignment_reuses_first_action(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db)
    _projection(db, account, version)
    _job, source = _search_result(db, account)
    review = _review(
        db,
        account,
        review_source="search_result",
        source_ref_id=str(source.id),
    )
    workflow = _workflow()
    first = workflow.orchestrate_qualification_review(db, review.id)
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="primary",
        assignment_source="admin_assign",
        operated_by=1,
        change_reason="assigned after qualification",
    )

    replay = workflow.orchestrate_qualification_review(db, review.id)

    assert replay.action.id == first.action.id
    assert db.query(customer_models.CustomerAction).count() == 1


def test_qualification_without_compiled_profile_creates_no_partial_workflow(db):
    _user(db, 1)
    account, version = _account(db)
    account.current_profile_version_id = None
    _job, source = _search_result(db, account)
    review = _review(
        db,
        account,
        review_source="search_result",
        source_ref_id=str(source.id),
    )

    with pytest.raises(_workflow().CustomerWorkflowConflict, match="PROFILE_NOT_READY"):
        _workflow().orchestrate_qualification_review(db, review.id)

    assert db.query(customer_models.CustomerOpportunity).count() == 0
    assert db.query(customer_models.CustomerAction).count() == 0
    assert db.query(customer_models.CustomerEvent).count() == 0


def test_public_pool_qualification_requires_passed_gate_even_when_result_is_accepted(db):
    _user(db, 1)
    account, _version = _account(db)
    task = _research_task(db, account)
    task.gate_status = "not_required"
    review = _review(
        db,
        account,
        review_source="public_pool_research",
        source_ref_id=str(task.id),
    )

    with pytest.raises(_workflow().CustomerWorkflowConflict, match="QUALIFICATION_SOURCE_INVALID"):
        _workflow().orchestrate_qualification_review(db, review.id)

    assert db.query(customer_models.CustomerOpportunity).count() == 0
    assert db.query(customer_models.CustomerAction).count() == 0


def test_submitting_approved_search_review_atomically_orchestrates_workflow(db):
    _user(db, 1)
    account, version = _account(db)
    _projection(db, account, version)
    _job, result = _search_result(db, account)

    from app.sales_automation.public_pool_service import submit_qualification_review

    review = submit_qualification_review(
        db,
        customer_id=account.id,
        review_source="search_result",
        source_ref_id=str(result.id),
        decision="approved",
        reason_code="qualified",
        scope_type="global",
        scope_ref_id=None,
        policy_version="workflow-v1",
        review_snapshot={
            "schema_version": "qualification_review_v1",
            "evidence_fact_ids": [],
            "priority_level": "A",
            "confidence_score": 90,
        },
        decision_request_key="search-review-hook-1",
        reviewed_by=1,
        expected_current_review_id=None,
    )

    opportunity = db.query(customer_models.CustomerOpportunity).one()
    action = db.query(customer_models.CustomerAction).one()
    assert opportunity.source_key == f"job:100:result:{result.id}"
    assert action.opportunity_id == opportunity.id
    assert result.qualification_review_id == review.id


def test_submitting_actionable_review_without_profile_leaves_no_partial_review(db):
    _user(db, 1)
    account, _version = _account(db)
    account.current_profile_version_id = None
    _job, result = _search_result(db, account)
    from app.sales_automation import service as sales_service
    from app.sales_automation.public_pool_service import submit_qualification_review

    with pytest.raises(sales_service.ConflictError, match="PROFILE_NOT_READY"):
        submit_qualification_review(
            db,
            customer_id=account.id,
            review_source="search_result",
            source_ref_id=str(result.id),
            decision="approved",
            reason_code="qualified",
            scope_type="global",
            scope_ref_id=None,
            policy_version="workflow-v1",
            review_snapshot={"schema_version": "qualification_review_v1"},
            decision_request_key="search-review-no-profile",
            reviewed_by=1,
            expected_current_review_id=None,
        )

    assert db.query(customer_models.CustomerQualificationReview).count() == 0
    assert db.query(customer_models.CustomerOpportunity).count() == 0
    assert result.qualification_review_id is None


def test_opportunity_upsert_uses_full_source_namespace_and_appends_one_created_event(db):
    _user(db, 1)
    account, _version = _account(db)
    service = _workflow()

    first = service.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="alibaba",
        source_account_key="store-a",
        source_key="inq-7",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title="Inquiry 7",
        actor_user_id=1,
    )
    replay = service.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="alibaba",
        source_account_key="store-a",
        source_key="inq-7",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title="Inquiry 7",
        actor_user_id=1,
    )
    other_store = service.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="alibaba",
        source_account_key="store-b",
        source_key="inq-7",
        opportunity_type="ali_inquiry",
        source="alibaba",
        title="Inquiry 7",
        actor_user_id=1,
    )

    assert replay.id == first.id
    assert other_store.id != first.id
    events = db.query(customer_models.CustomerOpportunityEvent).all()
    assert len(events) == 2
    assert {event.event_type for event in events} == {"created"}


def test_opportunity_conversation_source_requires_same_customer(db):
    _user(db, 1)
    account, _version = _account(db)
    other, _other_version = _account(db, code="C-CONVERSATION-OTHER")
    conversation = customer_models.CustomerConversation(
        customer_id=account.id,
        contact_id=None,
        source_system="email",
        source_account_key="global",
        external_conversation_id="thread-1",
        channel="email",
        owner_user_id=1,
        conversation_status="active",
        started_at=NOW,
        last_message_at=NOW,
        latest_source_record_id=None,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(conversation)
    db.flush()

    opportunity = _workflow().upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="email",
        source_account_key="global",
        source_key="thread-1",
        opportunity_type="inquiry",
        source="email",
        title="Email inquiry",
        source_ref_type="conversation",
        source_ref_id=conversation.id,
        actor_user_id=1,
    )
    assert opportunity.source_ref_type == "conversation"

    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="SOURCE_REFERENCE_CUSTOMER_MISMATCH",
    ):
        _workflow().upsert_opportunity(
            db,
            customer_id=other.id,
            source_system="email",
            source_account_key="global",
            source_key="thread-1-cross",
            opportunity_type="inquiry",
            source="email",
            title="Forged email inquiry",
            source_ref_type="conversation",
            source_ref_id=conversation.id,
            actor_user_id=1,
        )


def test_opportunity_and_action_owner_must_have_live_customer_scope(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db)
    workflow = _workflow()

    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_OWNER_SCOPE_REQUIRED",
    ):
        workflow.upsert_opportunity(
            db,
            customer_id=account.id,
            source_system="internal",
            source_account_key="global",
            source_key="owner-outside-scope",
            opportunity_type="manual",
            source="manual",
            title="Invalid owner",
            owner_user_id=1,
            actor_user_id=1,
        )

    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_OWNER_SCOPE_REQUIRED",
    ):
        workflow.create_action(
            db,
            customer_id=account.id,
            owner_user_id=1,
            profile_version_id=version.id,
            action_type="review",
            thread_group="new_inquiry",
            priority="normal",
            reason="Invalid owner",
            next_action="Review",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date(),
        )

    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="primary-owned",
        opportunity_type="manual",
        source="manual",
        title="Primary owned",
        owner_user_id=1,
        actor_user_id=1,
    )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_OPPORTUNITY_OWNER_MISMATCH",
    ):
        workflow.create_action(
            db,
            customer_id=account.id,
            owner_user_id=2,
            opportunity_id=opportunity.id,
            profile_version_id=version.id,
            action_type="review",
            thread_group="new_inquiry",
            priority="normal",
            reason="Wrong opportunity owner",
            next_action="Review",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date(),
        )


def test_admin_cannot_assign_opportunity_to_user_outside_live_customer_scope(db):
    _user(db, 1)
    _user(db, 2)
    account, _version = _account(db)
    opportunity = _workflow().upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="admin-assignment-scope",
        opportunity_type="manual",
        source="manual",
        title="Scoped admin assignment",
        actor_user_id=1,
    )

    from app.insight.customer_opportunity_service import assign_opportunity

    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="OPPORTUNITY_ASSIGNEE_SCOPE_REQUIRED",
    ):
        assign_opportunity(db, opportunity.id, 2, 1)

    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="admin_assign",
        operated_by=1,
    )
    assigned = assign_opportunity(db, opportunity.id, 2, 1)
    assert assigned.owner_user_id == 2


def test_opportunity_reassignment_moves_only_open_linked_actions(db):
    for user_id in (1, 2, 3):
        _user(db, user_id)
    account, version = _account(db)
    workflow = _workflow()
    for user_id in (2, 3):
        workflow.assign_customer(
            db,
            customer_id=account.id,
            user_id=user_id,
            assignment_role="collaborator",
            assignment_source="admin_assign",
            operated_by=1,
        )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="collaborator-transfer",
        opportunity_type="manual",
        source="manual",
        title="Collaborator transfer",
        owner_user_id=2,
        actor_user_id=1,
    )
    actions = []
    for index, status in enumerate(("pending", "snoozed", "done"), start=1):
        action = workflow.create_action(
            db,
            customer_id=account.id,
            owner_user_id=2,
            opportunity_id=opportunity.id,
            profile_version_id=version.id,
            action_type="review",
            thread_group="new_inquiry",
            priority="normal",
            reason=f"Transfer action {index}",
            next_action=f"Step {index}",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date() + timedelta(days=index),
        )
        action.status = status
        if status == "snoozed":
            action.snoozed_until = NOW + timedelta(days=7)
        actions.append(action)
    db.flush()

    from app.insight.customer_opportunity_service import assign_opportunity

    assigned = assign_opportunity(db, opportunity.id, 3, 1)
    assert assigned.owner_user_id == 3
    assert [db.get(customer_models.CustomerAction, row.id).owner_user_id for row in actions] == [
        3,
        3,
        2,
    ]


def test_public_pool_claim_is_atomic_and_revalidates_claimability(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db)
    _projection(db, account, version)
    _job, source = _search_result(db, account)
    review = _review(
        db,
        account,
        review_source="search_result",
        source_ref_id=str(source.id),
    )
    workflow = _workflow()
    created = workflow.orchestrate_qualification_review(db, review.id)

    assignment = workflow.claim_public_pool_customer(
        db,
        customer_id=account.id,
        claimant_user_id=2,
        operated_by=2,
        scope_type="global",
        scope_ref_id=None,
        allowed_user_ids={2},
        per_user_quota=5,
    )

    assert assignment.assignment_role == "primary"
    assert assignment.assignment_source == "public_pool_claim"
    assert created.opportunity.owner_user_id == 2
    assert created.action.owner_user_id == 2
    assert created.action.feedback_json["queue_assignment"]["mode"] == "claimed_primary_owner"
    assert created.action.feedback_json["queue_assignment"]["does_not_confer_customer_ownership"] is False
    assert account.relationship_stage == "developing"

    with pytest.raises(workflow.CustomerWorkflowConflict, match="ALREADY_CLAIMED"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1},
            per_user_quota=5,
        )


def test_public_pool_claim_accepts_open_opportunity_already_owned_by_claimant(db):
    _user(db, 1)
    account, version = _account(db)
    _projection(db, account, version)
    _job, source = _search_result(db, account)
    review = _review(
        db,
        account,
        review_source="search_result",
        source_ref_id=str(source.id),
    )
    workflow = _workflow()
    created = workflow.orchestrate_qualification_review(db, review.id)
    created.opportunity.owner_user_id = 1
    created.action.owner_user_id = 1
    db.flush()

    assignment = workflow.claim_public_pool_customer(
        db,
        customer_id=account.id,
        claimant_user_id=1,
        operated_by=1,
        scope_type="global",
        scope_ref_id=None,
        allowed_user_ids={1},
        per_user_quota=5,
    )

    assert assignment.user_id == 1
    assert account.relationship_stage == "developing"
    assert created.opportunity.owner_user_id == 1
    assert created.action.owner_user_id == 1


def test_public_pool_claim_idempotent_retry_rechecks_current_dnc(db):
    _user(db, 1)
    account, version = _account(db)
    _projection(db, account, version)
    _review(
        db,
        account,
        review_source="manual",
        source_ref_id="claim-retry",
    )
    workflow = _workflow()
    first = workflow.claim_public_pool_customer(
        db,
        customer_id=account.id,
        claimant_user_id=1,
        operated_by=1,
        scope_type="global",
        scope_ref_id=None,
        allowed_user_ids={1},
        per_user_quota=1,
    )
    db.add(customer_models.CustomerAnnotation(
        customer_id=account.id,
        annotation_type="do_not_contact",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"reason": "customer opted out after claim"},
        policy_scope_type="global",
        policy_scope_ref_id=None,
        policy_effective_at=NOW,
        visibility="management",
        data_classification="restricted_internal",
        status="active",
        authored_by=1,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()

    with pytest.raises(workflow.CustomerWorkflowConflict, match="DO_NOT_CONTACT"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1},
            per_user_quota=1,
        )
    assert first.assignment_status == "active"


@pytest.mark.parametrize(
    ("identity_status", "blocked", "cooldown", "allowed", "error_code"),
    [
        ("disputed", False, None, True, "IDENTITY_DISPUTED"),
        ("verified", True, None, True, "CLAIM_BLOCKED"),
        ("verified", False, NOW + timedelta(days=1), True, "CLAIM_COOLDOWN"),
        ("verified", False, None, False, "TEAM_SCOPE_DENIED"),
    ],
)
def test_public_pool_claim_rejects_request_time_gate_failures(
    db, identity_status, blocked, cooldown, allowed, error_code,
):
    _user(db, 1)
    account, version = _account(db, identity_status=identity_status)
    _projection(db, account, version, blocked=blocked, cooldown=cooldown)
    _review(
        db,
        account,
        review_source="manual",
        source_ref_id="manual-1",
    )
    workflow = _workflow()

    with pytest.raises(workflow.CustomerWorkflowConflict, match=error_code):
        workflow.claim_public_pool_customer(
            db,
            customer_id=account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1} if allowed else {99},
            per_user_quota=5,
        )

    assert db.query(customer_models.CustomerAssignment).count() == 0


def test_public_pool_claim_rejects_missing_qualification_and_target_match(db):
    _user(db, 1)
    account, version = _account(db)
    _projection(db, account, version)
    workflow = _workflow()

    with pytest.raises(workflow.CustomerWorkflowConflict, match="QUALIFICATION_REQUIRED"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1},
            per_user_quota=5,
        )

    _review(
        db,
        account,
        review_source="manual",
        source_ref_id="manual-target",
        scope_type="target_profile",
        scope_ref_id="77",
    )
    with pytest.raises(workflow.CustomerWorkflowConflict, match="TARGET_MATCH_REQUIRED"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="target_profile",
            scope_ref_id="77",
            allowed_user_ids={1},
            per_user_quota=5,
        )


def test_public_pool_claim_rejects_dnc_quota_and_conflicting_opportunity_owner(db):
    for user_id in (1, 2):
        _user(db, user_id)
    workflow = _workflow()

    dnc_account, dnc_version = _account(db, code="C-DNC")
    _projection(db, dnc_account, dnc_version)
    _review(db, dnc_account, review_source="manual", source_ref_id="dnc-review")
    db.add(customer_models.CustomerAnnotation(
        customer_id=dnc_account.id,
        annotation_type="do_not_contact",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"reason": "test"},
        policy_scope_type="global",
        policy_scope_ref_id=None,
        policy_effective_at=NOW,
        visibility="management",
        data_classification="restricted_internal",
        status="active",
        authored_by=1,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    with pytest.raises(workflow.CustomerWorkflowConflict, match="DO_NOT_CONTACT"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=dnc_account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1},
            per_user_quota=5,
        )

    quota_account, quota_version = _account(db, code="C-QUOTA")
    _projection(db, quota_account, quota_version)
    _review(db, quota_account, review_source="manual", source_ref_id="quota-review", review_id=302)
    prior_account, _ = _account(db, code="C-PRIOR")
    db.add(customer_models.CustomerAssignment(
        customer_id=prior_account.id,
        user_id=1,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="public_pool_claim",
        effective_from=NOW,
        operated_by=1,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()
    with pytest.raises(workflow.CustomerWorkflowConflict, match="CLAIM_QUOTA_EXCEEDED"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=quota_account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1},
            per_user_quota=1,
        )

    conflict_account, conflict_version = _account(db, code="C-OPP-CONFLICT")
    _projection(db, conflict_account, conflict_version)
    _review(
        db,
        conflict_account,
        review_source="manual",
        source_ref_id="conflict-review",
        review_id=303,
    )
    workflow.assign_customer(
        db,
        customer_id=conflict_account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="manual",
        operated_by=1,
    )
    workflow.upsert_opportunity(
        db,
        customer_id=conflict_account.id,
        source_system="internal",
        source_account_key="global",
        source_key="owned-by-2",
        opportunity_type="manual",
        source="manual",
        title="Owned by another user",
        owner_user_id=2,
        actor_user_id=1,
    )
    with pytest.raises(workflow.CustomerWorkflowConflict, match="OPPORTUNITY_OWNER_CONFLICT"):
        workflow.claim_public_pool_customer(
            db,
            customer_id=conflict_account.id,
            claimant_user_id=1,
            operated_by=1,
            scope_type="global",
            scope_ref_id=None,
            allowed_user_ids={1},
            per_user_quota=5,
        )


def test_claim_locks_claimant_before_customer_for_cross_customer_quota():
    workflow = _workflow()
    lock_sql = str(
        workflow._active_user_for_update_statement(7).compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    customer_lock_sql = str(
        workflow._account_for_update_statement(11).compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    source = inspect.getsource(workflow.claim_public_pool_customer)

    assert "FOR UPDATE" in lock_sql
    assert "FOR UPDATE" in customer_lock_sql
    assert source.index("_active_user_for_update") < source.index("_account_for_update")
    assert source.index("_account_for_update") < source.index("active_claim_count")


def test_concurrent_different_customer_claims_share_claimant_quota_lock(
    engine,
    tmp_path,
    monkeypatch,
):
    del engine  # Initializes the shared metadata's SQLite index de-duplication.
    workflow = _workflow()
    race_engine = create_engine(
        f"sqlite:///{tmp_path / 'customer-claim-quota.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(race_engine)
    factory = sessionmaker(bind=race_engine, expire_on_commit=False)
    with factory() as setup:
        _user(setup, 1)
        first, first_version = _account(setup, code="C-CLAIM-RACE-1")
        second, second_version = _account(setup, code="C-CLAIM-RACE-2")
        _projection(setup, first, first_version)
        _projection(setup, second, second_version)
        _review(
            setup,
            first,
            review_source="manual",
            source_ref_id="race-review-1",
            review_id=501,
        )
        _review(
            setup,
            second,
            review_source="manual",
            source_ref_id="race-review-2",
            review_id=502,
        )
        setup.commit()
        customer_ids = (first.id, second.id)

    # SQLite ignores SELECT ... FOR UPDATE. Model the MySQL claimant-row lock in
    # this two-session test; the preceding SQL assertion proves production emits it.
    claimant_lock = Lock()
    original_lock = workflow._active_user_for_update

    def acquire_claimant(session, user_id):
        claimant_lock.acquire()
        try:
            return original_lock(session, user_id)
        except Exception:
            claimant_lock.release()
            raise

    monkeypatch.setattr(workflow, "_active_user_for_update", acquire_claimant)
    start = Barrier(2)

    def claim(customer_id):
        with factory() as session:
            start.wait(timeout=10)
            try:
                assignment = workflow.claim_public_pool_customer(
                    session,
                    customer_id=customer_id,
                    claimant_user_id=1,
                    operated_by=1,
                    scope_type="global",
                    scope_ref_id=None,
                    allowed_user_ids={1},
                    per_user_quota=1,
                )
                session.commit()
                return "accepted", assignment.customer_id
            except workflow.CustomerWorkflowConflict as exc:
                session.rollback()
                return str(exc), customer_id
            finally:
                if claimant_lock.locked():
                    claimant_lock.release()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, customer_ids))

    assert sorted(status for status, _customer_id in outcomes) == [
        "CLAIM_QUOTA_EXCEEDED",
        "accepted",
    ]
    with factory() as verify:
        assert verify.query(customer_models.CustomerAssignment).filter_by(
            assignment_role="primary",
            assignment_status="active",
        ).count() == 1


def test_primary_transfer_and_collaborator_changes_preserve_assignment_history(db):
    for user_id in (1, 2, 3):
        _user(db, user_id)
    account, version = _account(db)
    workflow = _workflow()

    first = workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="admin_assign",
        operated_by=3,
        change_reason="initial owner",
    )
    collaborator = workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="manual",
        operated_by=3,
        change_reason="support",
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="transfer-opportunity",
        opportunity_type="manual",
        source="manual",
        title="Transfer opportunity",
        owner_user_id=1,
        actor_user_id=3,
    )
    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        opportunity_id=opportunity.id,
        profile_version_id=version.id,
        action_type="review",
        thread_group="new_inquiry",
        priority="normal",
        reason="Pending owner follow-up",
        next_action="Review account",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    second = workflow.transfer_primary_owner(
        db,
        customer_id=account.id,
        new_user_id=2,
        operated_by=3,
        change_reason="territory transfer",
    )

    assert first.assignment_status == "ended"
    assert first.effective_to is not None
    assert collaborator.assignment_status == "active"
    assert second.assignment_status == "active"
    assert second.user_id == 2
    assert opportunity.owner_user_id == 2
    assert action.owner_user_id == 2
    assert db.query(customer_models.CustomerAssignment).count() == 3


def test_action_completion_logs_sales_activity_without_fabricating_opportunity_stage(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="manual-1",
        opportunity_type="manual",
        source="manual",
        title="Manual follow-up",
        owner_user_id=1,
        actor_user_id=1,
    )
    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        opportunity_id=opportunity.id,
        profile_version_id=version.id,
        action_type="message",
        thread_group="new_inquiry",
        channel="email",
        priority="high",
        reason="New qualified inquiry",
        next_action="Send a human-reviewed reply",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )

    completed = workflow.complete_action(
        db,
        action_id=action.id,
        completed_by=1,
        occurred_at=NOW,
        channel="email",
        outcome_code="contacted",
        summary="Sent a short introduction",
        next_step="Wait for customer response",
    )

    assert completed.status == "done"
    assert opportunity.status == "pending"
    event = db.query(customer_models.CustomerEvent).filter_by(
        event_type="sales_activity.logged"
    ).one()
    assert event.source_ref_type == "action"
    assert event.source_ref_id == str(action.id)
    assert event.event_payload["outcome_code"] == "contacted"
    assert not db.query(customer_models.CustomerOpportunityEvent).filter(
        customer_models.CustomerOpportunityEvent.to_status.in_(["replied", "quoted"])
    ).count()


def test_verified_manager_override_keeps_real_actor_and_bypasses_owner_only_checks(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db, code="C-MANAGED-ACTION")
    workflow = _workflow()
    workflow.assign_customer(
        db, customer_id=account.id, user_id=1, assignment_role="primary",
        assignment_source="manual", operated_by=2,
    )

    def action(day_offset):
        return workflow.create_action(
            db, customer_id=account.id, owner_user_id=1,
            profile_version_id=version.id, action_type="review",
            thread_group="public_pool", priority="normal", reason=f"Managed {day_offset}",
            next_action="Handle", policy_version="workflow-v1", source_type="manual",
            source_event_ids=[], evidence_fact_ids=[],
            action_date=NOW.date() + timedelta(days=day_offset),
        )

    completed = workflow.complete_action(
        db, action_id=action(1).id, completed_by=2, occurred_at=NOW,
        channel="internal", outcome_code="other", summary="Manager completed",
        next_step="None", can_manage=True,
    )
    assert completed.completed_by == 2

    from app.insight import customer_radar_service

    dismissed = customer_radar_service.dismiss_action(
        db, action(2).id, 2, reason_code="other", note="manager decision",
        can_manage=True,
    )
    assert dismissed.status == "dismissed"
    snoozed = customer_radar_service.snooze_action(
        db, action(3).id, 2, NOW + timedelta(days=4), can_manage=True,
    )
    assert snoozed.status == "snoozed"
    feedback = customer_radar_service.submit_feedback(
        db, action(4).id, "manager feedback", None, 2, can_manage=True,
    )
    assert feedback.feedback_json["submitted_by"] == 2
    assert all(row.owner_user_id == 1 for row in (completed, dismissed, snoozed, feedback))


def test_action_generation_and_user_state_changes_advance_profile_input_once(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    initial_seq = account.profile_input_seq
    arguments = {
        "customer_id": account.id,
        "owner_user_id": 1,
        "profile_version_id": version.id,
        "action_type": "review",
        "thread_group": "public_pool",
        "priority": "normal",
        "reason": "Review evidence",
        "next_action": "Confirm next step",
        "policy_version": "workflow-v1",
        "source_type": "manual",
        "source_event_ids": [],
        "evidence_fact_ids": [],
        "action_date": NOW.date(),
    }

    action = workflow.create_action(db, **arguments)
    after_create = account.profile_input_seq
    replay = workflow.create_action(db, **arguments)
    assert replay.id == action.id
    assert after_create == initial_seq + 1
    assert account.profile_input_seq == after_create

    wording_update = workflow.create_action(
        db,
        **{
            **arguments,
            "reason": "Updated evidence wording",
            "next_action": "Updated next step wording",
            "suggested_message": "Updated safe draft",
        },
    )
    assert wording_update.id == action.id
    assert db.query(customer_models.CustomerAction).filter_by(
        customer_id=account.id,
        action_date=NOW.date(),
    ).count() == 1
    assert wording_update.reason == "Updated evidence wording"
    assert wording_update.next_action == "Updated next step wording"
    assert wording_update.suggested_message == "Updated safe draft"
    assert account.profile_input_seq == after_create + 1
    after_wording_update = account.profile_input_seq
    exact_wording_replay = workflow.create_action(
        db,
        **{
            **arguments,
            "reason": "Updated evidence wording",
            "next_action": "Updated next step wording",
            "suggested_message": "Updated safe draft",
        },
    )
    assert exact_wording_replay.id == action.id
    assert account.profile_input_seq == after_wording_update

    from app.insight import customer_radar_service

    customer_radar_service.submit_feedback(db, action.id, "useful", None, 1)
    assert account.profile_input_seq == after_wording_update + 1
    customer_radar_service.snooze_action(
        db,
        action.id,
        1,
        NOW + timedelta(days=1),
    )
    assert account.profile_input_seq == after_wording_update + 2
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_NOT_PENDING",
    ):
        customer_radar_service.dismiss_action(
            db,
            action.id,
            1,
            reason_code="other",
            note="not needed",
        )
    assert account.profile_input_seq == after_wording_update + 2


def test_customer_lock_precedes_opportunity_action_and_order_row_locks():
    workflow = _workflow()
    for function in (
        workflow.transition_opportunity,
        workflow.complete_action,
        workflow.activate_customer_from_order,
    ):
        source = inspect.getsource(function)
        assert source.index("_account_for_update") < source.index("with_for_update")


def test_action_completion_rejects_unknown_outcome_without_mutating_action(db):
    _user(db, 1)
    account, version = _account(db)
    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    action = _workflow().create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        profile_version_id=version.id,
        action_type="review",
        thread_group="public_pool",
        priority="normal",
        reason="Review evidence",
        next_action="Confirm next step",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )

    with pytest.raises(_workflow().CustomerWorkflowError, match="ACTION_OUTCOME_INVALID"):
        _workflow().complete_action(
            db,
            action_id=action.id,
            completed_by=1,
            occurred_at=NOW,
            channel="internal",
            outcome_code="fabricated_reply",
            summary="Invalid",
            next_step="None",
        )

    assert action.status == "pending"
    assert db.query(customer_models.CustomerEvent).filter_by(
        event_type="sales_activity.logged"
    ).count() == 0


def test_action_rejects_contact_without_current_relationship_to_customer(db):
    _user(db, 1)
    account, version = _account(db)
    other, _other_version = _account(db, code="C-OTHER-CONTACT")
    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    contact = customer_models.CustomerContact(
        display_name="Other Buyer",
        canonical_name="Other Buyer",
        normalized_name="other buyer",
        identity_status="verified",
        confidence=1,
        confidence_method_version="confidence_v1",
        confidence_components_json={"manual_confirmation": 1},
        record_status="active",
        created_by=1,
        updated_by=1,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(contact)
    db.flush()
    db.add(customer_models.CustomerContactRelationship(
        customer_id=other.id,
        contact_id=contact.id,
        relationship_type="buyer",
        buying_role="buyer",
        verification_status="verified",
        confidence=1,
        confidence_method_version="confidence_v1",
        confidence_components_json={"manual_confirmation": 1},
        relationship_fingerprint="7" * 64,
        created_by=1,
        updated_by=1,
        created_at=NOW,
        updated_at=NOW,
    ))
    db.flush()

    with pytest.raises(_workflow().CustomerWorkflowConflict, match="CONTACT_CUSTOMER_MISMATCH"):
        _workflow().create_action(
            db,
            customer_id=account.id,
            owner_user_id=1,
            profile_version_id=version.id,
            action_type="message",
            thread_group="new_inquiry",
            priority="normal",
            reason="Follow up",
            next_action="Contact buyer",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date(),
            contact_id=contact.id,
        )


def test_opportunity_contacted_transition_requires_and_records_real_activity_evidence(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="evidence-transition",
        opportunity_type="manual",
        source="manual",
        title="Evidence transition",
        owner_user_id=1,
        actor_user_id=1,
    )
    with pytest.raises(workflow.CustomerWorkflowConflict, match="OPPORTUNITY_EVIDENCE_REQUIRED"):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="contacted",
            actor_user_id=1,
            reason="manual",
        )
    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        opportunity_id=opportunity.id,
        profile_version_id=version.id,
        action_type="message",
        thread_group="new_inquiry",
        channel="email",
        priority="normal",
        reason="Need first contact",
        next_action="Send reviewed email",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    workflow.complete_action(
        db,
        action_id=action.id,
        completed_by=1,
        occurred_at=opportunity.stage_entered_at,
        channel="email",
        outcome_code="contacted",
        summary="Email sent",
        next_step="Wait",
    )
    activity = db.query(customer_models.CustomerEvent).filter_by(
        event_type="sales_activity.logged"
    ).one()
    changed = workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="contacted",
        actor_user_id=1,
        reason="first_contact",
        evidence_event_ids=[activity.id],
        occurred_at=activity.occurred_at,
    )
    assert changed.status == "contacted"
    stage_event = db.query(customer_models.CustomerOpportunityEvent).filter_by(
        event_type="stage_changed"
    ).one()
    assert stage_event.event_payload["evidence_event_ids"] == [activity.id]


def test_complete_action_api_records_explicit_activity_and_returns_event_id(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="complete-api-evidence",
        opportunity_type="manual",
        source="manual",
        title="Complete API evidence",
        owner_user_id=1,
        actor_user_id=1,
    )
    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        opportunity_id=opportunity.id,
        profile_version_id=version.id,
        action_type="email",
        thread_group="new_inquiry",
        channel="email",
        priority="normal",
        reason="Contact customer",
        next_action="Send reviewed email",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    from app.insight.router import radar_complete_action

    response = radar_complete_action(
        action.id,
        feedback="useful",
        note=None,
        outcome_code="contacted",
        channel="email",
        occurred_at=opportunity.stage_entered_at.isoformat(),
        summary="Sent reviewed introduction",
        next_step="Wait for reply",
        _user={"sub": 1, "permissions": ["customer_radar:write"]},
        db=db,
    )
    activity_event_id = response["data"]["activity_event_id"]
    activity = db.get(customer_models.CustomerEvent, activity_event_id)
    assert activity.event_type == "sales_activity.logged"
    assert activity.event_payload == {
        "action_id": action.id,
        "customer_id": account.id,
        "opportunity_id": opportunity.id,
        "channel": "email",
        "occurred_at": activity.occurred_at.isoformat(),
        "outcome_code": "contacted",
        "summary": "Sent reviewed introduction",
        "next_step": "Wait for reply",
    }
    assert db.get(customer_models.CustomerAction, action.id).status == "done"

    changed = workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="contacted",
        actor_user_id=1,
        reason="first_contact",
        evidence_event_ids=[activity.id],
        occurred_at=activity.occurred_at,
    )
    assert changed.status == "contacted"


def test_complete_action_rejects_unknown_outcome_and_future_activity_without_partial_write(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    from app.insight import customer_radar_service

    for index, kwargs in enumerate((
        {"outcome_code": "invented", "occurred_at": NOW},
        {"outcome_code": "contacted", "occurred_at": datetime(2999, 1, 1)},
    ), start=1):
        action = workflow.create_action(
            db,
            customer_id=account.id,
            owner_user_id=1,
            profile_version_id=version.id,
            action_type="review",
            thread_group="new_inquiry",
            priority="normal",
            reason=f"Invalid activity {index}",
            next_action="Review",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date() + timedelta(days=index),
        )
        with pytest.raises(
            workflow.CustomerWorkflowError,
            match="ACTION_(OUTCOME|OCCURRED_AT)_INVALID",
        ):
            customer_radar_service.complete_action(
                db,
                action.id,
                1,
                outcome_code=kwargs["outcome_code"],
                channel="internal",
                occurred_at=kwargs["occurred_at"],
                summary="Review completed",
                next_step="Continue",
            )
        assert db.get(customer_models.CustomerAction, action.id).status == "pending"
        assert db.query(customer_models.CustomerEvent).filter_by(
            event_type="sales_activity.logged",
            source_ref_id=str(action.id),
        ).count() == 0


def test_opportunity_close_reasons_are_status_scoped_and_reopen_clears_them(db):
    _user(db, 1)
    account, _version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="close-reason-contract",
        opportunity_type="manual",
        source="manual",
        title="Close reason contract",
        owner_user_id=1,
        actor_user_id=1,
    )
    with pytest.raises(
        workflow.CustomerWorkflowError,
        match="OPPORTUNITY_CLOSE_REASON_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="dismissed",
            actor_user_id=1,
            close_reason_code="price",
            close_reason_text="Price belongs to lost, not dismissed",
        )
    assert opportunity.status == "pending"

    explanation = "x" * 1000
    workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="dismissed",
        actor_user_id=1,
        close_reason_code="no_opportunity",
        close_reason_text=explanation,
    )
    assert opportunity.close_reason_code == "no_opportunity"
    assert opportunity.close_reason_text == explanation
    closed_event = db.query(customer_models.CustomerOpportunityEvent).filter_by(
        opportunity_id=opportunity.id,
        event_type="closed",
    ).one()
    assert closed_event.event_payload["close_reason_code"] == "no_opportunity"
    assert closed_event.event_payload["close_reason_text"] == explanation
    assert customer_models.CustomerOpportunity.__table__.c.close_reason_code.type.length == 32

    workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="pending",
        actor_user_id=1,
        reason="manual_reopen",
    )
    assert opportunity.close_reason_code is None
    assert opportunity.close_reason_text is None

    with pytest.raises(
        workflow.CustomerWorkflowError,
        match="OPPORTUNITY_CLOSE_REASON_TEXT_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="dismissed",
            actor_user_id=1,
            close_reason_code="other",
            close_reason_text="y" * 1001,
        )
    assert opportunity.status == "pending"


def test_manual_won_without_order_requires_dedicated_permission_and_reason(db):
    _user(db, 1)
    account, _version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )

    def quoted_opportunity(source_key: str):
        row = workflow.upsert_opportunity(
            db,
            customer_id=account.id,
            source_system="internal",
            source_account_key="global",
            source_key=source_key,
            opportunity_type="manual",
            source="manual",
            title="Manual won exception",
            owner_user_id=1,
            actor_user_id=1,
        )
        row.status = "quoted"
        db.flush()
        return row

    denied = quoted_opportunity("manual-won-denied")
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="MANUAL_WON_PERMISSION_REQUIRED",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=denied.id,
            new_status="won",
            actor_user_id=1,
            close_reason_code="manual_confirmed",
            close_reason_text="Confirmed by customer in an offline meeting",
        )
    assert denied.status == "quoted"

    _grant_permission(
        db,
        1,
        "customer_opportunity:confirm_without_order",
    )

    missing_reason = quoted_opportunity("manual-won-missing-reason")
    with pytest.raises(
        workflow.CustomerWorkflowError,
        match="OPPORTUNITY_CLOSE_REASON_TEXT_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=missing_reason.id,
            new_status="won",
            actor_user_id=1,
            close_reason_code="manual_confirmed",
            close_reason_text="",
        )

    manual = quoted_opportunity("manual-won-allowed")
    before_stage = account.relationship_stage
    won = workflow.transition_opportunity(
        db,
        opportunity_id=manual.id,
        new_status="won",
        actor_user_id=1,
        close_reason_code="manual_confirmed",
        close_reason_text="Confirmed by customer in an offline meeting",
    )
    assert won.status == "won"
    assert won.linked_order_id is None
    assert account.relationship_stage == before_stage
    customer_event = db.query(customer_models.CustomerEvent).filter_by(
        source_ref_type="opportunity",
        source_ref_id=str(won.id),
        event_type="opportunity.stage_changed",
    ).one()
    assert customer_event.data_classification == "restricted_internal"
    assert customer_event.visibility_scope == "management"
    assert customer_event.event_payload["manual_won_exception"] is True
    opportunity_event = db.query(customer_models.CustomerOpportunityEvent).filter_by(
        opportunity_id=won.id,
        event_type="closed",
    ).one()
    assert opportunity_event.event_payload["manual_won_exception"] is True

    order_required = quoted_opportunity("order-confirmed-needs-order")
    with pytest.raises(workflow.CustomerWorkflowConflict, match="VALID_ORDER_REQUIRED"):
        workflow.transition_opportunity(
            db,
            opportunity_id=order_required.id,
            new_status="won",
            actor_user_id=1,
            close_reason_code="order_confirmed",
            close_reason_text="Order was said to exist",
        )


@pytest.mark.parametrize("linked_order_kind", ["missing", "cross_customer"])
def test_manual_won_rejects_any_linked_order_reference_without_audit_mutation(
    db,
    linked_order_kind,
):
    _user(db, 1)
    account, _version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    _grant_permission(db, 1, "customer_opportunity:confirm_without_order")
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key=f"manual-won-linked-{linked_order_kind}",
        opportunity_type="manual",
        source="manual",
        title="Manual won must not carry an order reference",
        owner_user_id=1,
        actor_user_id=1,
    )
    opportunity.status = "quoted"
    linked_order_id = 999999
    if linked_order_kind == "cross_customer":
        other, _other_version = _account(db, code="C-OTHER")
        source = _source_record(db, other, record_id=9102)
        cross_customer_order = customer_models.CustomerOrder(
            customer_id=other.id,
            source_system="okki",
            source_account_key="tenant-a",
            external_order_id="cross-customer-order",
            order_status="confirmed",
            account_date=NOW.date(),
            amount_usd=100,
            is_valid_business_order=True,
            source_record_id=source.id,
            source_hash="9" * 64,
            synced_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        db.add(cross_customer_order)
        db.flush()
        linked_order_id = cross_customer_order.id

    opportunity_event_count = db.query(
        customer_models.CustomerOpportunityEvent
    ).filter_by(opportunity_id=opportunity.id).count()
    customer_event_count = db.query(customer_models.CustomerEvent).filter_by(
        source_ref_type="opportunity",
        source_ref_id=str(opportunity.id),
    ).count()

    with pytest.raises(
        workflow.CustomerWorkflowError,
        match="OPPORTUNITY_INPUT_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="won",
            actor_user_id=1,
            close_reason_code="manual_confirmed",
            close_reason_text="Confirmed by customer in an offline meeting",
            linked_order_id=linked_order_id,
        )

    assert opportunity.status == "quoted"
    assert opportunity.linked_order_id is None
    assert db.query(customer_models.CustomerOpportunityEvent).filter_by(
        opportunity_id=opportunity.id,
    ).count() == opportunity_event_count
    assert db.query(customer_models.CustomerEvent).filter_by(
        source_ref_type="opportunity",
        source_ref_id=str(opportunity.id),
    ).count() == customer_event_count


def test_manual_won_route_uses_only_dedicated_permission(db):
    _user(db, 1)
    account, _version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="manual-won-route",
        opportunity_type="manual",
        source="manual",
        title="Manual won route",
        owner_user_id=1,
        actor_user_id=1,
    )
    opportunity.status = "quoted"
    _grant_permission(db, 1, "customer_opportunity:manage")
    db.flush()
    from fastapi import HTTPException
    from app.insight.router import update_opp_status

    arguments = {
        "opp_id": opportunity.id,
        "status": "won",
        "note": None,
        "close_reason_code": "manual_confirmed",
        "close_reason_text": "Confirmed by a named sales manager",
        "evidence_event_ids": [],
        "evidence_fact_ids": [],
        "linked_order_id": None,
        "db": db,
    }
    with pytest.raises(HTTPException) as denied:
        update_opp_status(
            **arguments,
            _user={
                "sub": 1,
                "permissions": [
                    "customer_opportunity:write",
                    "customer_opportunity:manage",
                ],
            },
        )
    assert denied.value.status_code == 403
    assert opportunity.status == "quoted"

    _grant_permission(
        db,
        1,
        "customer_opportunity:confirm_without_order",
    )

    response = update_opp_status(
        **arguments,
        _user={
            "sub": 1,
            "permissions": [
                "customer_opportunity:write",
                "customer_opportunity:confirm_without_order",
            ],
        },
    )
    assert response["data"] == {"id": opportunity.id, "status": "won"}


def test_manual_won_permission_is_registered_but_not_auto_granted_to_admin():
    from app.auth.models import ArkRolePermission
    from app.auth.service import seed_role_permissions

    engine = create_engine("sqlite:///:memory:")
    ArkRole.__table__.create(engine)
    ArkPermission.__table__.create(engine)
    ArkRolePermission.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    admin = ArkRole(name="admin", label="System admin", is_system=True)
    session.add(admin)
    session.commit()

    seed_role_permissions(session)

    permission = session.query(ArkPermission).filter_by(
        code="customer_opportunity:confirm_without_order"
    ).one()
    assert session.query(ArkRolePermission).filter_by(
        role_id=admin.id,
        permission_id=permission.id,
    ).count() == 0
    customer_admin = session.query(ArkPermission).filter_by(code="customer:admin").one()
    customer_read_all = session.query(ArkPermission).filter_by(code="customer:read_all").one()
    assert customer_read_all.kind == "data"
    assert session.query(ArkRolePermission).filter_by(
        role_id=admin.id, permission_id=customer_admin.id,
    ).count() == 1
    assert session.query(ArkRolePermission).filter_by(
        role_id=admin.id, permission_id=customer_read_all.id,
    ).count() == 0
    session.close()
    engine.dispose()


def test_action_dismissal_uses_stable_code_and_bounded_note(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    from app.insight import customer_radar_service

    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        profile_version_id=version.id,
        action_type="review",
        thread_group="new_inquiry",
        priority="normal",
        reason="Dismiss safely",
        next_action="Review",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    note = "n" * 1000
    dismissed = customer_radar_service.dismiss_action(
        db,
        action.id,
        1,
        reason_code="user_dismissed",
        note=note,
    )
    assert dismissed.dismissal_reason == "user_dismissed"
    assert dismissed.feedback_json["user_note"] == note
    assert customer_models.CustomerAction.__table__.c.dismissal_reason.type.length == 32

    other = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        profile_version_id=version.id,
        action_type="review",
        thread_group="new_inquiry",
        priority="normal",
        reason="Reject unsafe dismissal",
        next_action="Review",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date() + timedelta(days=1),
    )
    with pytest.raises(workflow.CustomerWorkflowError, match="ACTION_DISMISSAL_INVALID"):
        customer_radar_service.dismiss_action(
            db,
            other.id,
            1,
            reason_code="invented",
            note="z" * 1001,
        )
    assert other.status == "pending"


def test_opportunity_transition_rejects_cross_owner_and_cross_opportunity_evidence(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    owned = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="owned-evidence",
        opportunity_type="manual",
        source="manual",
        title="Owned",
        owner_user_id=1,
        actor_user_id=1,
    )
    other = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="other-evidence",
        opportunity_type="manual",
        source="manual",
        title="Other",
        owner_user_id=1,
        actor_user_id=1,
    )
    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        opportunity_id=owned.id,
        profile_version_id=version.id,
        action_type="message",
        thread_group="new_inquiry",
        priority="normal",
        reason="Contact owned opportunity",
        next_action="Send message",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    workflow.complete_action(
        db,
        action_id=action.id,
        completed_by=1,
        occurred_at=NOW,
        channel="email",
        outcome_code="contacted",
        summary="Sent",
        next_step="Wait",
    )
    activity = db.query(customer_models.CustomerEvent).filter_by(
        event_type="sales_activity.logged"
    ).one()

    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_ACTOR_FORBIDDEN",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=owned.id,
            new_status="dismissed",
            actor_user_id=2,
            reason="forged",
        )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_EVIDENCE_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=other.id,
            new_status="contacted",
            actor_user_id=1,
            reason="cross opportunity",
            evidence_event_ids=[activity.id],
        )


def test_replied_and_quoted_require_directional_message_evidence_for_same_opportunity(db):
    _user(db, 1)
    account, _version = _account(db)
    source = _source_record(db, account, record_id=9201)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    conversation = customer_models.CustomerConversation(
        customer_id=account.id,
        contact_id=None,
        source_system="email",
        source_account_key="global",
        external_conversation_id="stage-thread",
        channel="email",
        owner_user_id=1,
        conversation_status="active",
        started_at=NOW,
        last_message_at=NOW,
        latest_source_record_id=source.id,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(conversation)
    db.flush()
    outbound = customer_models.CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="out-1",
        direction="out",
        sender_type="ark_user",
        sender_user_id=1,
        content_type="text",
        content_text="Hello",
        attachment_meta_json=[],
        source_record_id=source.id,
        content_hash="a" * 64,
        sent_at=NOW,
        captured_at=NOW,
        created_at=NOW,
    )
    inbound = customer_models.CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="in-1",
        direction="in",
        sender_type="customer_contact",
        content_type="text",
        content_text="Please quote",
        attachment_meta_json=[],
        source_record_id=source.id,
        content_hash="b" * 64,
        sent_at=NOW + timedelta(hours=1),
        captured_at=NOW + timedelta(hours=1),
        created_at=NOW + timedelta(hours=1),
    )
    stale_inbound = customer_models.CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="in-stale",
        direction="in",
        sender_type="customer_contact",
        content_type="text",
        content_text="Old reply before the current stage",
        attachment_meta_json=[],
        source_record_id=source.id,
        content_hash="d" * 64,
        sent_at=NOW - timedelta(hours=1),
        captured_at=NOW - timedelta(hours=1),
        created_at=NOW - timedelta(hours=1),
    )
    db.add_all([outbound, inbound, stale_inbound])
    db.flush()
    quote_message = customer_models.CustomerMessage(
        conversation_id=conversation.id,
        external_message_id="out-quote-1",
        direction="out",
        sender_type="ark_user",
        sender_user_id=1,
        content_type="document",
        content_text="Quote Q-1 attached",
        attachment_meta_json=[{"file_name": "Q-1.pdf"}],
        source_record_id=source.id,
        content_hash="c" * 64,
        sent_at=NOW + timedelta(hours=2),
        captured_at=NOW + timedelta(hours=2),
        created_at=NOW + timedelta(hours=2),
    )
    db.add(quote_message)
    db.flush()
    from app.customer.fact_service import append_customer_event

    sent = append_customer_event(
        db,
        customer_id=account.id,
        event_type="message.sent",
        event_source="email",
        event_title="Message sent",
        event_payload={"direction": "out"},
        payload_schema_version="customer_event_v1",
        occurred_at=outbound.sent_at,
        source_ref_type="message",
        source_ref_id=str(outbound.id),
    )
    received = append_customer_event(
        db,
        customer_id=account.id,
        event_type="message.received",
        event_source="email",
        event_title="Message received",
        event_payload={"direction": "in"},
        payload_schema_version="customer_event_v1",
        occurred_at=inbound.sent_at,
        source_ref_type="message",
        source_ref_id=str(inbound.id),
    )
    stale_received = append_customer_event(
        db,
        customer_id=account.id,
        event_type="message.received",
        event_source="email",
        event_title="Stale message received",
        event_payload={"direction": "in"},
        payload_schema_version="customer_event_v1",
        occurred_at=stale_inbound.sent_at,
        source_ref_type="message",
        source_ref_id=str(stale_inbound.id),
    )
    quote_sent = append_customer_event(
        db,
        customer_id=account.id,
        event_type="message.sent",
        event_source="email",
        event_title="Quote sent",
        event_payload={"direction": "out"},
        payload_schema_version="customer_event_v1",
        occurred_at=quote_message.sent_at,
        source_ref_type="message",
        source_ref_id=str(quote_message.id),
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="email",
        source_account_key="global",
        source_key="stage-thread",
        opportunity_type="inquiry",
        source="email",
        title="Directional evidence",
        source_ref_type="conversation",
        source_ref_id=conversation.id,
        owner_user_id=1,
        actor_user_id=1,
    )
    opportunity.stage_entered_at = sent.occurred_at + timedelta(minutes=1)
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_EVIDENCE_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="contacted",
            actor_user_id=1,
            reason="stale outbound",
            evidence_event_ids=[sent.id],
            occurred_at=sent.occurred_at,
        )
    opportunity.stage_entered_at = sent.occurred_at - timedelta(minutes=1)
    workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="contacted",
        actor_user_id=1,
        reason="outbound sent",
        evidence_event_ids=[sent.id],
        occurred_at=sent.occurred_at,
    )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_EVIDENCE_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="replied",
            actor_user_id=1,
            reason="stale inbound reply",
            evidence_event_ids=[stale_received.id],
            occurred_at=stale_received.occurred_at,
        )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_STAGE_TIME_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="replied",
            actor_user_id=1,
            reason="backdated stage",
            evidence_event_ids=[received.id],
            occurred_at=sent.occurred_at - timedelta(minutes=1),
        )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_EVIDENCE_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="replied",
            actor_user_id=1,
            reason="wrong direction",
            evidence_event_ids=[sent.id],
        )
    workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="replied",
        actor_user_id=1,
        reason="inbound reply",
        evidence_event_ids=[received.id],
        occurred_at=received.occurred_at,
    )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="OPPORTUNITY_EVIDENCE_INVALID",
    ):
        workflow.transition_opportunity(
            db,
            opportunity_id=opportunity.id,
            new_status="quoted",
            actor_user_id=1,
            reason="missing quote ref",
            evidence_event_ids=[sent.id],
        )
    opportunity.quote_ref = "QUOTE-1"
    workflow.transition_opportunity(
        db,
        opportunity_id=opportunity.id,
        new_status="quoted",
        actor_user_id=1,
        reason="quote sent",
        evidence_event_ids=[quote_sent.id],
        occurred_at=quote_sent.occurred_at,
    )
    assert opportunity.status == "quoted"


def test_action_completion_requires_current_customer_assignment(db):
    _user(db, 1)
    account, version = _account(db)
    assignment = _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    action = _workflow().create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        profile_version_id=version.id,
        action_type="review",
        thread_group="new_inquiry",
        priority="normal",
        reason="Review",
        next_action="Review",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    assignment.assignment_status = "ended"
    assignment.effective_to = NOW
    db.flush()

    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="ACTION_ACTOR_FORBIDDEN",
    ):
        _workflow().complete_action(
            db,
            action_id=action.id,
            completed_by=1,
            occurred_at=NOW,
            channel="internal",
            outcome_code="other",
            summary="Review complete",
            next_step="None",
        )


def test_done_action_cannot_be_overwritten_by_dismiss_or_snooze(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    actions = [
        workflow.create_action(
            db,
            customer_id=account.id,
            owner_user_id=1,
            profile_version_id=version.id,
            action_type=action_type,
            thread_group="new_inquiry",
            priority="normal",
            reason=f"Terminal action {action_type}",
            next_action="Handle",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date(),
        )
        for action_type in ("review", "call")
    ]
    for action in actions:
        workflow.complete_action(
            db,
            action_id=action.id,
            completed_by=1,
            occurred_at=NOW,
            channel="internal",
            outcome_code="other",
            summary="Done",
            next_step="None",
        )

    from app.insight import customer_radar_service

    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_NOT_PENDING",
    ):
        customer_radar_service.dismiss_action(
            db,
            actions[0].id,
            1,
            reason_code="other",
            note="overwrite",
        )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_NOT_PENDING",
    ):
        customer_radar_service.snooze_action(
            db,
            actions[1].id,
            1,
            NOW + timedelta(days=1),
        )


def test_revoked_assignment_hides_owner_snapshots_and_blocks_action_mutations(db):
    _user(db, 1)
    account, version = _account(db)
    workflow = _workflow()
    assignment = workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="revoked-owner-snapshot",
        opportunity_type="manual",
        source="manual",
        title="Revoked owner snapshot",
        owner_user_id=1,
        actor_user_id=1,
    )
    actions = [
        workflow.create_action(
            db,
            customer_id=account.id,
            owner_user_id=1,
            opportunity_id=opportunity.id,
            profile_version_id=version.id,
            action_type=action_type,
            thread_group="new_inquiry",
            priority="normal",
            reason=f"Owner action {action_type}",
            next_action="Handle",
            policy_version="workflow-v1",
            source_type="manual",
            source_event_ids=[],
            evidence_fact_ids=[],
            action_date=NOW.date(),
        )
        for action_type in ("review", "message", "call")
    ]
    assignment.assignment_status = "ended"
    assignment.effective_to = NOW
    db.flush()

    from app.insight import customer_opportunity_service, customer_radar_service

    assert customer_opportunity_service.list_my_opportunities(db, 1)["total"] == 0
    assert customer_opportunity_service.get_opportunity_stats(db, 1)["total"] == 0
    assert customer_radar_service.get_daily_focus(db, 1)["summary"]["total"] == 0
    assert sum(customer_radar_service.get_thread_counts(db, 1).values()) == 0

    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_ACTOR_FORBIDDEN",
    ):
        customer_radar_service.dismiss_action(
            db,
            actions[0].id,
            1,
            reason_code="other",
            note="stale",
        )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_ACTOR_FORBIDDEN",
    ):
        customer_radar_service.snooze_action(
            db,
            actions[1].id,
            1,
            NOW + timedelta(days=1),
        )
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_ACTOR_FORBIDDEN",
    ):
        customer_radar_service.submit_feedback(
            db,
            actions[2].id,
            "useful",
            None,
            1,
        )


def test_only_valid_order_can_activate_customer_and_historical_replay_cannot_override_inactive(db):
    _user(db, 1)
    account, _version = _account(db, relationship_stage="inactive", stage_changed_at=NOW)
    source = _source_record(db, account)
    workflow = _workflow()

    invalid = customer_models.CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        external_order_id="invalid-1",
        order_status="draft",
        account_date=(NOW + timedelta(days=1)).date(),
        amount_usd=100,
        is_valid_business_order=False,
        invalid_reason="draft",
        source_record_id=source.id,
        source_hash="1" * 64,
        synced_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    historical = customer_models.CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        external_order_id="old-1",
        order_status="confirmed",
        account_date=(NOW - timedelta(days=1)).date(),
        amount_usd=100,
        is_valid_business_order=True,
        source_record_id=source.id,
        source_hash="2" * 64,
        synced_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    current = customer_models.CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        external_order_id="new-1",
        order_status="confirmed",
        account_date=(NOW + timedelta(days=1)).date(),
        amount_usd=100,
        is_valid_business_order=True,
        source_record_id=source.id,
        source_hash="3" * 64,
        synced_at=NOW + timedelta(days=1),
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([invalid, historical, current])
    db.flush()

    assert workflow.activate_customer_from_order(db, invalid.id) is False
    assert workflow.activate_customer_from_order(db, historical.id) is False
    assert account.relationship_stage == "inactive"
    assert workflow.activate_customer_from_order(db, current.id) is True
    assert account.relationship_stage == "active_customer"


def test_invalidated_order_without_winning_audit_is_rejected_without_partial_correction(db):
    account, _version = _account(db, code="C-ORDER-AUDIT")
    source = _source_record(db, account, record_id=9101)
    order = customer_models.CustomerOrder(
        customer_id=account.id,
        source_system="okki",
        source_account_key="tenant-a",
        external_order_id="ORDER-AUDIT",
        order_status="invalid",
        account_date=NOW.date(),
        amount_usd=100,
        is_valid_business_order=False,
        invalid_reason="not_effective_business_order",
        source_record_id=source.id,
        source_hash="a" * 64,
        synced_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(order)
    db.flush()
    opportunity = _workflow().upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="manual",
        source_account_key="global",
        source_key="order-audit",
        opportunity_type="manual",
        source="manual",
        title="Missing won audit",
    )
    opportunity.status = "won"
    opportunity.close_reason_code = "order_confirmed"
    opportunity.linked_order_id = order.id
    db.flush()

    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="ORDER_INVALIDATION_AUDIT_INSUFFICIENT",
    ):
        with db.begin_nested():
            _workflow().reconcile_invalidated_order(db, order.id)

    db.refresh(opportunity)
    assert opportunity.status == "won"
    assert opportunity.linked_order_id == order.id
    assert db.query(customer_models.CustomerFact).filter_by(
        customer_id=account.id,
        fact_key="commercial.has_valid_order",
    ).count() == 0
    assert db.query(customer_models.CustomerEvent).filter_by(
        customer_id=account.id,
        event_type="order.validity_revoked",
    ).count() == 0


def test_merge_and_split_supersede_other_open_proposals_in_same_transaction(db):
    _user(db, 1)
    left, left_version = _account(db, code="C-LEFT")
    right, _right_version = _account(db, code="C-RIGHT")
    statuses = ["draft", "pending", "approved", "rejected", "executed"]
    rows = []
    for offset, status in enumerate(statuses, start=1):
        row = customer_models.CustomerChangeProposal(
            customer_id=left.id,
            target_customer_id=right.id,
            action_type="merge",
            payload_schema_version="customer_merge_v1",
            payload_json={"keep_customer_id": left.id},
            profile_version_id=left_version.id,
            evidence_fact_ids=[],
            risk_level="critical",
            data_classification="restricted_internal",
            visibility_scope="management",
            action_hash=f"{500 + offset:064x}",
            expires_at=NOW + timedelta(days=1),
            status=status,
            proposed_by=1,
            approved_action_hash=(
                f"{500 + offset:064x}" if status == "approved" else None
            ),
            decided_by=1 if status == "approved" else None,
            decided_at=NOW if status == "approved" else None,
            execution_idempotency_key=("a" * 64 if status == "approved" else None),
            created_at=NOW,
            updated_at=NOW,
        )
        rows.append(row)
    db.add_all(rows)
    db.flush()

    rows[2].status = "executed"
    superseded = _workflow().supersede_related_proposals(
        db,
        executing_proposal_id=rows[2].id,
        expected_execution_idempotency_key="a" * 64,
        declared_plan=[
            {"proposal_id": rows[0].id, "next_status": "superseded"},
            {"proposal_id": rows[1].id, "next_status": "superseded"},
        ],
    )

    assert superseded == rows[:2]
    assert rows[0].status == "superseded"
    assert rows[1].status == "superseded"
    assert rows[2].status == "executed"
    assert rows[3].status == "rejected"
    assert rows[4].status == "executed"

    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="CHANGE_PROPOSAL_PLAN_STALE",
    ):
        _workflow().supersede_related_proposals(
            db,
            executing_proposal_id=rows[2].id,
            expected_execution_idempotency_key="a" * 64,
            declared_plan=[{
                "proposal_id": rows[0].id,
                "next_status": "superseded",
            }],
        )
    assert _workflow().supersede_related_proposals(
        db,
        executing_proposal_id=rows[2].id,
        expected_execution_idempotency_key="a" * 64,
        declared_plan=[],
    ) == []
    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="CHANGE_PROPOSAL_EXECUTION_KEY_MISMATCH",
    ):
        _workflow().supersede_related_proposals(
            db,
            executing_proposal_id=rows[2].id,
            expected_execution_idempotency_key="f" * 64,
            declared_plan=[],
        )


def test_split_supersede_accepts_only_payload_declared_redirects(db):
    _user(db, 1)
    source, version = _account(db, code="C-SPLIT-SOURCE")
    target, target_version = _account(db, code="C-SPLIT-TARGET")
    redirected = customer_models.CustomerChangeProposal(
        customer_id=target.id,
        target_customer_id=None,
        action_type="correction",
        payload_schema_version="customer_correction_v1",
        payload_json={"field": "canonical_company_name"},
        profile_version_id=target_version.id,
        evidence_fact_ids=[],
        risk_level="high",
        data_classification="restricted_internal",
        visibility_scope="management",
        action_hash="7" * 64,
        expires_at=NOW + timedelta(days=1),
        status="pending",
        proposed_by=1,
        created_at=NOW,
        updated_at=NOW,
    )
    undeclared = customer_models.CustomerChangeProposal(
        customer_id=source.id,
        target_customer_id=None,
        action_type="correction",
        payload_schema_version="customer_correction_v1",
        payload_json={"field": "display_name"},
        profile_version_id=version.id,
        evidence_fact_ids=[],
        risk_level="high",
        data_classification="restricted_internal",
        visibility_scope="management",
        action_hash="6" * 64,
        expires_at=NOW + timedelta(days=1),
        status="draft",
        proposed_by=1,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([redirected, undeclared])
    db.flush()
    executing = customer_models.CustomerChangeProposal(
        customer_id=source.id,
        target_customer_id=target.id,
        action_type="split",
        payload_schema_version="customer_split_v1",
        payload_json={
            "new_customer_ids": [target.id],
            "proposal_redirects": [{
                "proposal_id": redirected.id,
                "target_customer_id": target.id,
                "target_profile_version_id": target_version.id,
            }],
        },
        profile_version_id=version.id,
        evidence_fact_ids=[],
        risk_level="critical",
        data_classification="restricted_internal",
        visibility_scope="management",
        action_hash="8" * 64,
        expires_at=NOW + timedelta(days=1),
        status="executed",
        proposed_by=1,
        approved_action_hash="8" * 64,
        decided_by=1,
        decided_at=NOW,
        execution_idempotency_key="b" * 64,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(executing)
    db.flush()

    superseded = _workflow().supersede_related_proposals(
        db,
        executing_proposal_id=executing.id,
        expected_execution_idempotency_key="b" * 64,
        declared_plan=[{
            "proposal_id": undeclared.id,
            "next_status": "superseded",
        }],
    )

    assert redirected not in superseded
    assert redirected.status == "pending"
    assert undeclared.status == "superseded"

    with pytest.raises(
        _workflow().CustomerWorkflowConflict,
        match="CHANGE_PROPOSAL_PLAN_INVALID",
    ):
        _workflow().supersede_related_proposals(
            db,
            executing_proposal_id=executing.id,
            expected_execution_idempotency_key="b" * 64,
            declared_plan=[{
                "proposal_id": redirected.id,
                "next_status": "draft",
            }],
        )

    assert redirected.status == "pending"


def test_insight_models_only_reexport_unified_workflow_models():
    assert insight_models.CustomerOpportunity is customer_models.CustomerOpportunity
    assert insight_models.CustomerOpportunityEvent is customer_models.CustomerOpportunityEvent
    assert insight_models.CustomerAction is customer_models.CustomerAction
    for retired_name in (
        "InquiryImportBatch",
        "CustomerProfile",
        "CustomerProfileEvent",
    ):
        assert not hasattr(insight_models, retired_name)


def test_unified_workflow_models_match_frozen_126_contract():
    contract_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "126_unified_customer_domain_schema.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))[
        "customer_domain_physical_contract"
    ]["tables"]
    for model in (
        customer_models.CustomerOpportunity,
        customer_models.CustomerOpportunityEvent,
        customer_models.CustomerAction,
    ):
        expected = contract[model.__tablename__]
        actual = model.__table__
        assert actual.comment == expected["table_comment"]
        assert {column.name for column in actual.columns} == {
            column["name"] for column in expected["columns"]
        }
        assert all(column.comment for column in actual.columns)
    expected_owner = next(
        column
        for column in contract["ark_customer_actions"]["columns"]
        if column["name"] == "owner_user_id"
    )
    actual_owner = customer_models.CustomerAction.__table__.c.owner_user_id
    assert expected_owner["nullable"] is True
    assert actual_owner.nullable is True
    assert actual_owner.comment == (
        "行动执行人方舟用户ID；空表示公海未分配队列，认领时赋值"
    )


def test_opportunity_list_order_is_mysql_portable_without_nulls_last_syntax(db):
    from app.insight.customer_opportunity_service import _filtered_query, _order_query

    statement = _order_query(_filtered_query(db)).statement
    sql = str(statement.compile(dialect=mysql.dialect()))

    assert "NULLS LAST" not in sql.upper()
    assert "ark_customer_opportunities.due_at IS NULL" in sql


def test_insight_routes_only_expose_customer_id_profile_and_no_retired_import_endpoints():
    from app.insight.router import router
    from app.customer.router import router as customer_hub_router

    paths = {route.path for route in router.routes}
    hub_paths = {route.path for route in customer_hub_router.routes}
    assert "/customer-radar/customers/{customer_id}" not in paths
    assert "/customer-radar/customers/{customer_id}/sources" not in paths
    assert "/customers/{customer_id}" in hub_paths
    assert "/customers/{customer_id}/timeline" in hub_paths
    assert "/customer-radar/profiles/{profile_id}" not in paths
    assert "/customer-opportunities/import/accio" not in paths


def test_opportunity_write_does_not_disclose_missing_vs_forbidden_id(db):
    _user(db, 1)
    _user(db, 2)
    account, _version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db,
        customer_id=account.id,
        source_system="internal",
        source_account_key="global",
        source_key="non-disclosing-write",
        opportunity_type="manual",
        source="manual",
        title="Non-disclosing write",
        owner_user_id=1,
        actor_user_id=1,
    )
    from fastapi import HTTPException
    from app.insight.router import update_opp_status

    details = []
    for opportunity_id in (opportunity.id, opportunity.id + 999999):
        with pytest.raises(HTTPException) as denied:
            update_opp_status(
                opportunity_id,
                status="dismissed",
                note="forbidden",
                close_reason_code="other",
                close_reason_text="forbidden",
                evidence_event_ids=[],
                evidence_fact_ids=[],
                linked_order_id=None,
                db=db,
                _user={"sub": 2, "permissions": ["customer_opportunity:write"]},
            )
        assert denied.value.status_code == 404
        details.append(denied.value.detail)
    assert details[0] == details[1]


def test_radar_action_writes_do_not_disclose_missing_vs_forbidden_id(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db)
    workflow = _workflow()
    workflow.assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    action = workflow.create_action(
        db,
        customer_id=account.id,
        owner_user_id=1,
        profile_version_id=version.id,
        action_type="review",
        thread_group="new_inquiry",
        priority="normal",
        reason="Private owner action",
        next_action="Review",
        policy_version="workflow-v1",
        source_type="manual",
        source_event_ids=[],
        evidence_fact_ids=[],
        action_date=NOW.date(),
    )
    from fastapi import HTTPException
    from app.insight.router import (
        radar_action_feedback,
        radar_complete_action,
        radar_dismiss_action,
        radar_snooze_action,
    )

    user = {"sub": 2, "permissions": ["customer_radar:write"]}
    operations = (
        lambda action_id: radar_complete_action(
            action_id,
            feedback=None,
            note=None,
            outcome_code="other",
            channel="internal",
            occurred_at=None,
            summary=None,
            next_step=None,
            _user=user,
            db=db,
        ),
        lambda action_id: radar_dismiss_action(
            action_id,
            reason_code="user_dismissed",
            note=None,
            _user=user,
            db=db,
        ),
        lambda action_id: radar_snooze_action(
            action_id,
            until=(NOW + timedelta(days=365)).isoformat(),
            _user=user,
            db=db,
        ),
        lambda action_id: radar_action_feedback(
            action_id,
            body={"feedback": "useful"},
            _user=user,
            db=db,
        ),
    )
    for operation in operations:
        details = []
        for action_id in (action.id, action.id + 999999):
            with pytest.raises(HTTPException) as denied:
                operation(action_id)
            assert denied.value.status_code == 404
            details.append(denied.value.detail)
        assert details[0] == details[1]


def test_customer_radar_scope_allows_collaborator_and_denies_unassigned_user(db):
    for user_id in (1, 2, 3):
        _user(db, user_id)
    account, _version = _account(db)
    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="manual",
        operated_by=1,
        change_reason="support",
    )
    from fastapi import HTTPException
    from app.insight.router import _require_customer_radar_scope

    collaborator = {
        "sub": "2",
        "permissions": ["customer_radar:read"],
        "roles": [],
    }
    assert _require_customer_radar_scope(db, account.id, collaborator) is None

    unassigned = {
        "sub": "3",
        "permissions": ["customer_radar:read"],
        "roles": [],
    }
    with pytest.raises(HTTPException) as denied:
        _require_customer_radar_scope(db, account.id, unassigned)
    assert denied.value.status_code == 403


def test_customer_profile_projects_agent_context_for_ordinary_team_reader(db):
    _user(db, 1)
    _user(db, 2)
    account, version = _account(db)
    version.profile_json = {
        **version.profile_json,
        "risks": [{"detail": "management-only-risk"}],
    }
    db.add(customer_models.CustomerAgentContext(
        customer_id=account.id,
        profile_version_id=version.id,
        context_schema_version="customer_context_v1",
        context_json={"identity": {"display_name": account.display_name}},
        max_data_classification="internal_business",
        context_hash="c" * 64,
        data_as_of=NOW,
        built_at=NOW,
        updated_at=NOW,
    ))
    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="manual",
        operated_by=1,
        change_reason="support",
    )

    from app.customer.access_service import CustomerAccess, require_customer_access
    from app.insight.customer_profile_service import get_profile

    team_access = require_customer_access(
        db,
        customer_id=account.id,
        user={
            "sub": "2",
            "permissions": ["customer_radar:read"],
            "roles": [],
        },
        action_permissions={"customer_radar:read"},
        manage_permissions={"customer_radar:manage"},
    )
    team_profile = get_profile(db, account.id, access=team_access)
    assert team_profile["profile_projection"] == "customer_context_v1"
    assert team_profile["profile_json"] == {
        "identity": {"display_name": account.display_name}
    }
    assert "management-only-risk" not in str(team_profile)

    manager_access = require_customer_access(
        db,
        customer_id=account.id,
        user={
            "sub": "1",
                "permissions": ["customer_radar:manage", "customer:read_all"],
            "roles": [],
        },
        action_permissions={"customer_radar:read", "customer_radar:manage"},
        manage_permissions={"customer_radar:manage"},
    )
    manager_profile = get_profile(db, account.id, access=manager_access)
    assert manager_profile["profile_projection"] == "customer_profile_v1"
    assert manager_profile["profile_json"]["risks"] == [
        {"detail": "management-only-risk"}
    ]
    default_profile = get_profile(db, account.id)
    assert default_profile["profile_projection"] == "customer_context_v1"
    assert "management-only-risk" not in str(default_profile)
    public_profile = get_profile(
        db,
        account.id,
        access=CustomerAccess(
            customer_id=account.id,
            actor_user_id=2,
            can_manage=False,
            max_data_classification="public_business",
            max_visibility_scope="customer_team",
            run_id=99,
        ),
    )
    assert public_profile["profile_projection"] == "public_business"
    assert public_profile["profile_json"] == {}
    for field in (
        "customer_code",
        "identity_status",
        "relationship_stage",
        "primary_owner_user_id",
        "commercial_value_score",
        "data_quality_score",
        "open_opportunity_count",
        "next_action_at",
    ):
        assert field not in public_profile
    manager_low_visibility_profile = get_profile(
        db,
        account.id,
        access=CustomerAccess(
            customer_id=account.id,
            actor_user_id=1,
            can_manage=True,
            max_data_classification="restricted_internal",
            max_visibility_scope="all_authorized",
            run_id=100,
        ),
    )
    assert manager_low_visibility_profile["profile_projection"] == "public_business"
    assert manager_low_visibility_profile["profile_json"] == {}
    for field in (
        "customer_code",
        "identity_status",
        "relationship_stage",
        "primary_owner_user_id",
        "commercial_value_score",
        "data_quality_score",
        "open_opportunity_count",
        "next_action_at",
    ):
        assert field not in manager_low_visibility_profile


def test_customer_source_projection_enforces_visibility_and_classification(db):
    _user(db, 1)
    _user(db, 2)
    account, _version = _account(db)
    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=2,
        assignment_role="collaborator",
        assignment_source="manual",
        operated_by=1,
        change_reason="support",
    )
    visible = _source_record(db, account, record_id=9101)
    restricted = _source_record(db, account, record_id=9102)
    restricted.data_classification = "restricted_internal"
    restricted.visibility_scope = "management"
    private_note = customer_models.CustomerAnnotation(
        customer_id=account.id,
        annotation_type="note",
        target_fact_id=None,
        content_schema_version="v1",
        content_json={"text": "private management note"},
        policy_scope_type=None,
        policy_scope_ref_id=None,
        policy_effective_at=None,
        visibility="private",
        data_classification="restricted_internal",
        status="active",
        authored_by=1,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(private_note)
    db.flush()

    from app.customer.access_service import require_customer_access
    from app.insight.customer_source_service import get_source_records

    collaborator = {
        "sub": "2",
        "permissions": ["customer_radar:read"],
        "roles": [],
    }
    access = require_customer_access(
        db,
        customer_id=account.id,
        user=collaborator,
        action_permissions={"customer_radar:read"},
        manage_permissions={"customer_radar:manage"},
    )
    records = get_source_records(db, account.id, "all", access=access)
    assert visible.id in {item.get("source_record_id") for item in records}
    assert restricted.id not in {item.get("source_record_id") for item in records}
    assert private_note.id not in {item.get("annotation_id") for item in records}

    manager = {
        "sub": "1",
        "permissions": ["customer_radar:manage", "customer:read_all"],
        "roles": [],
    }
    manager_access = require_customer_access(
        db,
        customer_id=account.id,
        user=manager,
        action_permissions={"customer_radar:read", "customer_radar:manage"},
        manage_permissions={"customer_radar:manage"},
    )
    manager_records = get_source_records(
        db,
        account.id,
        "all",
        access=manager_access,
    )
    assert restricted.id in {
        item.get("source_record_id") for item in manager_records
    }
    assert private_note.id in {
        item.get("annotation_id") for item in manager_records
    }


def test_customer_insight_and_scheduler_queries_do_not_use_non_mysql_nulls_last():
    from app.agent_runtime import orchestration
    from app.insight import customer_opportunity_service, customer_radar_service

    for module in (
        orchestration,
        customer_opportunity_service,
        customer_radar_service,
    ):
        assert ".nulls_last(" not in inspect.getsource(module)


def test_radar_uses_effective_owner_for_focus_generate_and_mutations(db):
    from app.insight import customer_radar_service

    _user(db, 1)
    _user(db, 2)
    source, source_profile = _account(db, code="RADAR-STORAGE")
    target, _target_profile = _account(db, code="RADAR-LOGICAL")
    workflow = _workflow()
    source_assignment = workflow.assign_customer(
        db, customer_id=source.id, user_id=1, assignment_role="primary",
        assignment_source="manual", operated_by=1,
    )
    workflow.assign_customer(
        db, customer_id=target.id, user_id=1, assignment_role="primary",
        assignment_source="manual", operated_by=1,
    )
    workflow.assign_customer(
        db, customer_id=source.id, user_id=2, assignment_role="collaborator",
        assignment_source="manual", operated_by=1,
    )
    opportunity = workflow.upsert_opportunity(
        db, customer_id=source.id, source_system="internal",
        source_account_key="global", source_key="logical-radar",
        opportunity_type="ali_inquiry", source="manual",
        title="Logical radar opportunity", owner_user_id=1, actor_user_id=1,
    )
    actions = [
        workflow.create_action(
            db, customer_id=source.id, owner_user_id=1,
            opportunity_id=opportunity.id, profile_version_id=source_profile.id,
            action_type=action_type, thread_group="new_inquiry",
            priority="high", reason=f"Logical {action_type}", next_action="Handle",
            policy_version="logical-radar-test", source_type="manual",
            source_event_ids=[], evidence_fact_ids=[], action_date=NOW.date(),
        )
        for action_type in ("review", "message", "call", "email")
    ]
    history = customer_models.CustomerChangeProposal(
        customer_id=source.id, target_customer_id=target.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=source_profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="8" * 64,
        status="executed", expires_at=NOW + timedelta(days=1),
    )
    db.add(history)
    db.flush()
    for object_type, row in (
        ("opportunity", opportunity),
        *(("action", action) for action in actions),
    ):
        db.add(customer_models.CustomerObjectOwnership(
            object_type=object_type, object_id=row.id,
            storage_customer_id=source.id, current_customer_id=target.id,
            ownership_version=1, last_change_proposal_id=history.id,
            last_action_type="split",
        ))
    source_assignment.assignment_status = "ended"
    source_assignment.effective_to = NOW
    db.flush()

    focus = customer_radar_service.get_daily_focus(db, 1, NOW.date())
    assert focus["summary"]["total"] == 4
    assert {
        item["customer_id"]
        for thread in focus["threads"] for item in thread["actions"]
    } == {target.id}
    generated = customer_radar_service.generate_daily_actions(db, 1, NOW.date())
    generated_action = next(
        row for row in generated if row.policy_version == "customer_radar_v1"
    )
    assert generated_action.customer_id == target.id
    assert generated_action.opportunity_id == opportunity.id

    customer_radar_service.dismiss_action(
        db, actions[0].id, 1, reason_code="other", note="not now",
    )
    customer_radar_service.snooze_action(
        db, actions[1].id, 1, NOW + timedelta(days=1),
    )
    customer_radar_service.submit_feedback(
        db, actions[2].id, "useful", "logical", 1,
    )
    completed = customer_radar_service.complete_action(
        db, actions[3].id, 1, outcome_code="contacted",
        occurred_at=NOW, summary="Contacted", next_step="Follow up",
    )
    assert completed.logical_customer_id == target.id
    event = db.query(customer_models.CustomerEvent).filter_by(
        event_type="sales_activity.logged",
    ).one()
    assert event.customer_id == target.id
    assert event.event_payload["customer_id"] == target.id
    with pytest.raises(
        workflow.CustomerWorkflowConflict,
        match="ACTION_OWNER_REQUIRED|ACTION_ACTOR_FORBIDDEN",
    ):
        customer_radar_service.dismiss_action(
            db, generated_action.id, 2, reason_code="other",
        )


def test_manual_note_appends_registered_annotation_event(db):
    _user(db, 1)
    account, _version = _account(db)
    _workflow().assign_customer(
        db,
        customer_id=account.id,
        user_id=1,
        assignment_role="primary",
        assignment_source="manual",
        operated_by=1,
    )
    from app.customer.access_service import require_customer_access
    from app.insight.customer_source_service import add_manual_note

    access = require_customer_access(
        db,
        customer_id=account.id,
        user={
            "sub": "1",
            "permissions": ["customer_radar:write"],
            "roles": [],
        },
        action_permissions={"customer_radar:write"},
        manage_permissions={"customer_radar:manage"},
    )
    annotation = add_manual_note(
        db,
        account.id,
        "Buyer prefers WhatsApp",
        1,
        access=access,
    )

    event = db.query(customer_models.CustomerEvent).filter_by(
        event_type="annotation.created"
    ).one()
    assert annotation.customer_id == account.id
    assert event.event_type == "annotation.created"
    assert event.source_ref_type == "annotation"
    assert event.source_ref_id == str(annotation.id)
