"""Public-pool, proposal, and logical-route API contracts."""

from app.customer import router as customer_router

def test_public_pool_research_returns_only_safe_summary(db):
    from datetime import datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkPermission, ArkRole, ArkUser
    from app.core.database import get_db
    from app.customer.models import CustomerAccount, CustomerResearchTask

    now = datetime(2026, 8, 30, 9, 0)
    db.add(ArkUser(id=91, username="public-research", password_hash="x", real_name="Reader", is_active=True))
    customer = CustomerAccount(
        customer_code="C-PUBLIC-RESEARCH", display_name="Public Research Co",
        entity_type="registered_company", identity_status="candidate",
        relationship_stage="lead", relationship_stage_changed_at=now,
        relationship_stage_reason="test", record_status="active",
        identity_confidence=.5, profile_completeness=20, profile_input_seq=0,
    )
    db.add(customer)
    db.flush()

    def task(fingerprint, classification, visibility):
        return CustomerResearchTask(
            customer_id=customer.id, task_type="public_pool", source_ref_type="source_record",
            source_ref_id="secret-source-id", tier="T1", task_status="completed",
            gate_status="passed", result_review_status="accepted",
            selection_reason=[{"email": "person@example.com"}],
            research_policy_version="test-v1", task_fingerprint=fingerprint * 64,
            input_snapshot={"email": "person@example.com"},
            result_schema_version="customer_research_v1",
            result_json={"contact_email": "person@example.com"},
            data_classification=classification, visibility_scope=visibility,
            classification_reason="test", research_summary="safe business summary",
            evidence_fact_ids=[], lease_generation=0, attempt_count=1, created_by=91,
        )

    safe = task("a", "internal_business", "all_authorized")
    sensitive = task("b", "personal_contact", "customer_team")
    db.add_all([safe, sensitive])
    db.flush()
    identity = {"sub": "91", "roles": [], "permissions": ["sales_automation:read"]}
    app = FastAPI()
    app.include_router(customer_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity

    with TestClient(app) as client:
        listed = client.get("/api/customer-hub/research-tasks")
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 1
        detail = client.get(f"/api/customer-hub/research-tasks/{safe.id}")
        assert detail.status_code == 200
        data = detail.json()["data"]
        assert data["content_redacted"] is True
        assert "result_json" not in data
        assert "input_snapshot" not in data
        assert "source_ref_id" not in data
        assert client.get(f"/api/customer-hub/research-tasks/{sensitive.id}").status_code == 404


def test_proposals_require_source_and_target_scope_and_redact_above_lower_ceiling(db):
    from datetime import datetime, timedelta

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkUser
    from app.core.database import get_db
    from app.customer.models import (
        CustomerAccount, CustomerAssignment, CustomerChangeProposal,
        CustomerFact, CustomerProfileVersion,
    )
    from app.customer.proposal_service import canonical_action_hash

    now = datetime(2026, 8, 30, 9, 0)
    admin = ArkUser(id=101, username="proposal-admin", password_hash="x", real_name="Admin", is_active=True, okki_department_id=10)
    same_owner = ArkUser(id=102, username="proposal-same", password_hash="x", real_name="Same", is_active=True, okki_department_id=10)
    other_owner = ArkUser(id=103, username="proposal-other", password_hash="x", real_name="Other", is_active=True, okki_department_id=20)
    db.add_all([admin, same_owner, other_owner])

    def account(code):
        row = CustomerAccount(
            customer_code=code, display_name=code, entity_type="registered_company",
            identity_status="verified", relationship_stage="qualified",
            relationship_stage_changed_at=now, relationship_stage_reason="test",
            record_status="active", identity_confidence=1, profile_completeness=80,
            profile_input_seq=0,
        )
        db.add(row)
        db.flush()
        version = CustomerProfileVersion(
            customer_id=row.id, version_no=1, profile_schema_version="customer_profile_v1",
            canonicalization_version="jcs_v1", input_seq=0, profile_json={},
            section_hashes={}, section_data_as_of={}, evidence_fact_ids=[],
            change_summary={}, compiler_version="test", profile_fingerprint=f"{row.id:064x}",
            compiled_at=now,
        )
        db.add(version)
        db.flush()
        row.current_profile_version_id = version.id
        return row, version

    source, profile = account("C-PROPOSAL-SOURCE")
    same, _ = account("C-PROPOSAL-SAME")
    other, _ = account("C-PROPOSAL-OTHER")
    db.add_all([
        CustomerAssignment(customer_id=source.id, user_id=102, assignment_role="primary", assignment_status="active", assignment_source="manual", effective_from=now),
        CustomerAssignment(customer_id=same.id, user_id=102, assignment_role="primary", assignment_status="active", assignment_source="manual", effective_from=now),
        CustomerAssignment(customer_id=other.id, user_id=103, assignment_role="primary", assignment_status="active", assignment_source="manual", effective_from=now),
    ])
    fact = CustomerFact(
        customer_id=source.id, subject_type="customer", fact_key="business.industry",
        value_type="string", value_json={"value": "hair"}, fact_layer="confirmed",
        verification_status="verified", confidence=1,
        confidence_method_version="test", confidence_components_json={},
        data_classification="restricted_internal", visibility_scope="management",
        classification_reason="proposal evidence", evidence_json={},
        fact_fingerprint="e" * 64, observed_at=now,
    )
    db.add(fact)
    db.flush()

    def proposal(target, token):
        payload_json = {"user_id": 102, "reason": f"secret-{token}"}
        row = CustomerChangeProposal(
            customer_id=source.id, target_customer_id=target.id,
            action_type="assign_primary", payload_schema_version="customer_assign_primary_v1",
            payload_json=payload_json,
            profile_version_id=profile.id, evidence_fact_ids=[fact.id], risk_level="high",
            data_classification="restricted_internal", visibility_scope="management",
            action_hash="", expires_at=now + timedelta(days=1),
            status="draft", proposed_by=101,
        )
        row.action_hash = canonical_action_hash(
            action_type=row.action_type, customer_id=row.customer_id,
            target_customer_id=row.target_customer_id, payload_json=payload_json,
            profile_version_id=row.profile_version_id,
            evidence_fact_ids=row.evidence_fact_ids,
        )
        return row

    visible = proposal(same, "c")
    forbidden = proposal(other, "d")
    db.add_all([visible, forbidden])
    db.flush()
    identity = {"sub": "101", "roles": [], "permissions": ["customer:admin"]}
    app = FastAPI()
    app.include_router(customer_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity

    with TestClient(app) as client:
        listed = client.get("/api/customer-hub/change-proposals")
        assert listed.status_code == 200
        assert listed.json()["data"]["total"] == 1
        item = listed.json()["data"]["items"][0]
        assert item["proposal_id"] == visible.id
        assert item["payload_json"] is None
        assert item["evidence_fact_ids"] == []
        assert item["action_hash"] is None
        assert client.post(f"/api/customer-hub/change-proposals/{visible.id}/submit").status_code == 404
        assert client.post(f"/api/customer-hub/change-proposals/{forbidden.id}/submit").status_code == 404

        identity["permissions"] = ["customer:admin", "customer:read_all"]
        submitted = client.post(f"/api/customer-hub/change-proposals/{visible.id}/submit")
        assert submitted.status_code == 200
        assert submitted.json()["data"]["status"] == "pending"
        assert submitted.json()["data"]["payload_json"]["reason"] == "secret-c"


def test_qualification_write_can_review_public_pool_without_returning_pii(db):
    from datetime import datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkUser
    from app.core.database import get_db
    from app.customer.models import CustomerAccount

    now = datetime(2026, 8, 30, 9, 0)
    db.add(ArkUser(id=111, username="qualification-writer", password_hash="x", real_name="Writer", is_active=True))
    customer = CustomerAccount(
        customer_code="C-PUBLIC-QUALIFY", display_name="Public Qualify Co",
        entity_type="registered_company", identity_status="candidate",
        relationship_stage="lead", relationship_stage_changed_at=now,
        relationship_stage_reason="test", record_status="active",
        identity_confidence=.5, profile_completeness=20, profile_input_seq=0,
    )
    db.add(customer)
    db.flush()
    identity = {"sub": "111", "roles": [], "permissions": ["sales_automation:write"]}
    app = FastAPI()
    app.include_router(customer_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    payload = {
        "customer_id": customer.id, "review_source": "manual",
        "source_ref_id": None, "decision": "rejected", "reason_code": "bad_data",
        "reason_text": "person@example.com is private", "scope_type": "global",
        "scope_ref_id": None, "policy_version": "test-v1", "review_after": None,
        "review_snapshot": {"email": "person@example.com"},
        "decision_request_key": "public-review-1", "expected_current_review_id": None,
    }

    with TestClient(app) as client:
        response = client.post("/api/customer-hub/qualification-reviews", json=payload)
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["customer_id"] == customer.id
        assert data["decision"] == "rejected"
        assert "reason_text" not in data
        assert "source_ref_id" not in data
        assert "reviewed_by" not in data


def test_split_overlay_routes_use_logical_customer_for_review_and_updates(db, monkeypatch):
    from datetime import datetime, timedelta

    import pytest
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkPermission, ArkRole, ArkUser
    from app.core.database import get_db
    from app.customer.models import (
        CustomerAccount, CustomerAction, CustomerAssignment, CustomerChangeProposal,
        CustomerEvent, CustomerOpportunityEvent,
        CustomerObjectOwnership, CustomerOpportunity, CustomerProfileVersion,
        CustomerResearchTask, SearchJob, SearchResult,
    )
    from app.customer.schemas import ActionUpdate, OpportunityUpdate
    from app.sales_automation import router as sales_router
    from app.sales_automation import public_pool_service
    from app.sales_automation import service as sales_service
    from app.sales_automation.service import ConflictError
    from app.sales_automation.schemas import ResearchResultReview
    from tests.test_customer_governance_policy import _fact

    now = datetime(2026, 8, 31, 12, 0)
    user = ArkUser(
        id=1801, username="logical-route", password_hash="x",
        real_name="Logical Route", is_active=True,
    )
    old_owner = ArkUser(
        id=1812, username="logical-route-old", password_hash="x",
        real_name="Logical Route Old", is_active=True,
    )
    permission = ArkPermission(
        code="customer:write", module="customer", action="write",
        label="Customer write",
    )
    role = ArkRole(
        name="logical-route-writer", label="Logical route writer", description="test",
    )
    role.permissions.append(permission)
    user.roles.append(role)

    def account(row_id, code):
        row = CustomerAccount(
            id=row_id, customer_code=code, display_name=code,
            entity_type="registered_company", identity_status="verified",
            relationship_stage="qualified", relationship_stage_changed_at=now,
            relationship_stage_reason="test", record_status="active",
            identity_confidence=1, profile_completeness=80, profile_input_seq=1,
        )
        db.add(row)
        return row

    storage = account(1802, "STORAGE")
    logical = account(1803, "LOGICAL")
    other = account(1811, "OTHER")
    db.add_all([user, old_owner, permission, role])
    db.flush()
    profile = CustomerProfileVersion(
        id=1804, customer_id=storage.id, version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1", input_seq=1, profile_json={},
        section_hashes={}, section_data_as_of={}, evidence_fact_ids=[],
        change_summary={}, compiler_version="test", profile_fingerprint="a" * 64,
        compiled_at=now, created_at=now,
    )
    db.add(profile)
    db.flush()
    storage.current_profile_version_id = profile.id
    proposal = CustomerChangeProposal(
        id=1805, customer_id=storage.id, target_customer_id=logical.id,
        action_type="split", payload_schema_version="customer_split_v1",
        payload_json={}, profile_version_id=profile.id, evidence_fact_ids=[],
        risk_level="critical", data_classification="restricted_internal",
        visibility_scope="management", action_hash="b" * 64,
        expires_at=now + timedelta(days=1), status="executed",
    )
    task = CustomerResearchTask(
        id=1806, customer_id=storage.id, task_type="full_research",
        tier=None, task_status="completed", gate_status="passed",
        result_review_status="accepted", selection_reason=[],
        research_policy_version="test", task_fingerprint="c" * 64,
        input_snapshot={"customer_id": storage.id}, result_schema_version="customer_research_v1",
        result_json={}, data_classification="internal_business",
        visibility_scope="customer_team", classification_reason="test",
        research_summary="done", evidence_fact_ids=[], lease_generation=0,
        attempt_count=1, created_at=now, updated_at=now,
    )
    opportunity = CustomerOpportunity(
        id=1807, customer_id=storage.id, opportunity_type="manual", source="manual",
        source_system="manual", source_account_key="global", source_key="logical-route",
        owner_user_id=user.id, priority_level="A", confidence_score=80,
        urgency="high", title="Logical opportunity", product_requirement_json={},
        competitor_json={}, evidence_fact_ids=[], status="pending",
        stage_entered_at=now - timedelta(days=1), created_at=now, updated_at=now,
    )
    action = CustomerAction(
        id=1808, customer_id=storage.id, owner_user_id=user.id,
        opportunity_id=opportunity.id, action_type="email", thread_group="new_inquiry",
        priority="high", reason="reply", next_action="send", action_date=now.date(),
        status="pending", feedback_json={}, source_event_ids=[], evidence_fact_ids=[],
        profile_version_id=profile.id, source_type="manual", policy_version="test",
        action_fingerprint="d" * 64, evidence_status="valid",
        generated_at=now, created_at=now, updated_at=now,
    )
    job = SearchJob(
        id=1809, profile_id=999, name="Logical search", status="completed",
        adapter="agent", target_count=1, criteria_json={}, profile_snapshot={},
        policy_version="test", profile_snapshot_hash="e" * 64,
        idempotency_key="f" * 64, ingestion_receipts={}, result_count=1,
        created_customer_count=0, deduplicated_count=1, researched_count=1,
        qualified_count=0, provider_usage_json=[], cost_status="not_applicable",
        cost_original=0, cost_currency=None, cost_usd=0, attempt_count=1,
        created_by=user.id, created_at=now, updated_at=now,
    )
    search_result = SearchResult(
        id=1810, job_id=job.id, customer_id=storage.id, best_rank=1,
        best_score=90, aggregated_score_reasons={}, result_status="active",
        created_at=now, updated_at=now,
    )
    db.add_all([proposal, task, opportunity, action, job, search_result])
    db.flush()
    db.add(CustomerAssignment(
        customer_id=logical.id, user_id=user.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=now,
    ))
    db.add(CustomerAssignment(
        customer_id=storage.id, user_id=old_owner.id, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=now,
    ))
    for object_type, row in (
        ("research_task", task), ("opportunity", opportunity),
        ("action", action), ("search_result", search_result),
    ):
        db.add(CustomerObjectOwnership(
            object_type=object_type, object_id=row.id,
            storage_customer_id=storage.id, current_customer_id=logical.id,
            ownership_version=1, last_change_proposal_id=proposal.id,
            last_action_type="split", created_at=now, updated_at=now,
        ))
    db.flush()
    identity = {
        "sub": str(user.id), "roles": [],
        "permissions": ["sales_automation:admin", "sales_automation:read",
                        "customer_opportunity:write", "customer_radar:write"],
    }
    queue = customer_router.qualification_queue(page=1, page_size=20, db=db, user=identity)
    assert queue["data"]["items"][0]["customer_id"] == logical.id
    public_pool_service.get_task(db, task.id)
    detailed_task = sales_router._research_task(task, include_content=True)
    assert detailed_task["customer_id"] == logical.id
    assert detailed_task["input_snapshot"]["customer_id"] == logical.id
    results, total = sales_service.list_search_results(
        db, job.id, page=1, page_size=20,
    )
    assert total == 1
    assert sales_router._result(results[0])["customer_id"] == logical.id
    app = FastAPI()
    app.include_router(customer_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    with TestClient(app) as client:
        response = client.post("/api/customer-hub/qualification-reviews", json={
            "customer_id": logical.id,
            "review_source": "public_pool_research",
            "source_ref_id": str(task.id),
            "decision": "rejected",
            "reason_code": "bad_data",
            "scope_type": "global",
            "scope_ref_id": None,
            "policy_version": "test-v1",
            "review_snapshot": {},
            "decision_request_key": "logical-qualification-1",
            "expected_current_review_id": None,
        })
    assert response.status_code == 201
    assert response.json()["data"]["customer_id"] == logical.id
    reviewed = customer_router.review_research_task(
        task.id, ResearchResultReview(review_status="accepted"), db=db, user=identity,
    )
    assert reviewed["data"]["customer_id"] == logical.id

    storage_seq = storage.profile_input_seq
    target_seq = logical.profile_input_seq
    identity["sub"] = str(old_owner.id)
    with pytest.raises(HTTPException) as old_owner_error:
        customer_router.update_opportunity(
            opportunity.id, OpportunityUpdate(
                status="dismissed", reason="old owner",
                close_reason_code="no_opportunity",
            ), db=db, user=identity,
        )
    assert old_owner_error.value.status_code == 404
    identity["sub"] = str(user.id)
    cross_fact = _fact(db, other, "logical-route-cross")
    with pytest.raises(HTTPException) as cross_error:
        customer_router.update_opportunity(
            opportunity.id, OpportunityUpdate(
                status="dismissed", reason="bad evidence",
                close_reason_code="no_opportunity",
                evidence_fact_ids=[cross_fact.id],
            ), db=db, user=identity,
        )
    assert cross_error.value.status_code == 409
    updated = customer_router.update_opportunity(
        opportunity.id, OpportunityUpdate(
            status="dismissed", reason="done", close_reason_code="no_opportunity",
        ),
        db=db, user=identity,
    )
    assert updated["data"]["customer_id"] == logical.id
    assert storage.profile_input_seq == storage_seq
    assert logical.profile_input_seq == target_seq + 1
    assert db.query(CustomerOpportunityEvent).filter_by(
        opportunity_id=opportunity.id, customer_id=logical.id,
    ).count() == 1
    assert db.query(CustomerEvent).filter_by(
        event_type="opportunity.stage_changed", customer_id=logical.id,
    ).count() == 1
    monkeypatch.setattr(
        "app.insight.customer_radar_service.complete_action",
        lambda *_args, **kwargs: action if kwargs["can_manage"] else None,
    )
    completed = customer_router.update_action(
        action.id, ActionUpdate(operation="complete", outcome_code="contacted"),
        db=db, user=identity,
    )
    assert completed["data"]["customer_id"] == logical.id

    public_pool_service.review_research_result(
        db, task.id, "revision_requested", reviewer_id=user.id,
    )
    claimable, total = public_pool_service.list_claimable_tasks(db, 1, 20)
    assert total == 0
    assert claimable == []
    blocked_calls = (
        lambda: public_pool_service.claim_task(db, task.id, user.id, "agent"),
        lambda: public_pool_service.submit_industry_gate(
            db, task.id, user.id, "agent", "stale-token", "core", "retry",
        ),
        lambda: public_pool_service.complete_task_research(
            db, task.id, user.id, "agent", "stale-token", {}, agent_run_id=1,
        ),
        lambda: public_pool_service.fail_task(
            db, task.id, "provider_unavailable", user.id, "agent", "stale-token",
        ),
    )
    for call in blocked_calls:
        with pytest.raises(
            ConflictError,
            match="RESEARCH_TASK_LOGICAL_OWNER_CHANGED_RECREATE_REQUIRED",
        ):
            call()
