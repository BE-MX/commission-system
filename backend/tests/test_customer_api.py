"""Human Customer Hub API contract."""

from app.auth.service import _DATA_KIND_CODES
from app.customer import router as customer_router
from app.routers import register_routers


def test_customer_http_envelope_pagination_beijing_time_and_uniform_404(db):
    from datetime import datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkPermission, ArkRole, ArkUser
    from app.core.database import get_db
    from app.customer.models import CustomerAccount, CustomerAssignment

    now = datetime(2026, 8, 30, 9, 0)
    db.add_all([
        ArkUser(id=1, username="hub-http-1", password_hash="x", real_name="Reader", is_active=True),
        ArkUser(id=2, username="hub-http-2", password_hash="x", real_name="Other", is_active=True),
    ])
    customer = CustomerAccount(
        customer_code="C-HTTP", display_name="HTTP Co", entity_type="registered_company",
        identity_status="verified", relationship_stage="qualified",
        relationship_stage_changed_at=now, relationship_stage_reason="test",
        record_status="active", identity_confidence=1, profile_completeness=80,
        profile_input_seq=0, updated_at=now,
    )
    db.add(customer)
    db.flush()
    db.add(CustomerAssignment(
        customer_id=customer.id, user_id=2, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=now,
    ))
    db.flush()
    identity = {"sub": "1", "roles": [], "permissions": ["customer:read"]}
    app = FastAPI()
    app.include_router(customer_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity

    with TestClient(app) as client:
        listed = client.get("/api/customer-hub/customers?page=1&page_size=20")
        assert listed.status_code == 200
        assert listed.json() == {
            "code": 200, "message": "ok",
            "data": {"items": [], "total": 0, "page": 1, "page_size": 20},
        }
        assert client.get("/api/customer-hub/customers?page_size=101").status_code == 422
        forbidden = client.get(f"/api/customer-hub/customers/{customer.id}")
        missing = client.get("/api/customer-hub/customers/999999")
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json() == missing.json()

        identity["permissions"] = ["customer:read", "customer:read_all"]
        listed = client.get("/api/customer-hub/customers")
        assert listed.json()["data"]["items"][0]["updated_at"].endswith("+08:00")


def test_proposal_hash_is_canonical_and_unsupported_actions_never_enter_approval(db, monkeypatch):
    from datetime import datetime, timedelta

    import pytest

    from app.auth.models import ArkPermission, ArkRole, ArkUser
    from app.customer.models import CustomerAccount, CustomerAssignment, CustomerChangeProposal, CustomerFact, CustomerProfileVersion
    from app.customer.proposal_service import (
        ProposalConflict,
        approve_proposal,
        canonical_action_hash,
        create_proposal,
        execute_proposal,
        submit_proposal,
    )

    now = datetime(2026, 8, 30, 9, 0)
    permission = ArkPermission(code="customer:write", module="customer", action="write", label="Write customer")
    role = ArkRole(name="proposal-writer", label="Proposal writer")
    role.permissions.append(permission)
    proposer = ArkUser(id=1, username="proposal-1", password_hash="x", real_name="Proposer", is_active=True)
    approver = ArkUser(id=2, username="proposal-2", password_hash="x", real_name="Approver", is_active=True)
    owner = ArkUser(id=3, username="proposal-3", password_hash="x", real_name="Owner", is_active=True)
    approver.roles.append(role)
    db.add_all([proposer, approver, owner])
    customer = CustomerAccount(
        customer_code="C-PROPOSAL", display_name="Proposal Co",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="qualified", relationship_stage_changed_at=now,
        relationship_stage_reason="test", record_status="active",
        identity_confidence=1, profile_completeness=80, profile_input_seq=0,
    )
    db.add(customer)
    db.flush()
    profile = CustomerProfileVersion(
        customer_id=customer.id, version_no=1,
        profile_schema_version="customer_profile_v1", canonicalization_version="jcs_v1",
        input_seq=0, profile_json={}, section_hashes={}, section_data_as_of={},
        evidence_fact_ids=[], change_summary={}, compiler_version="test",
        profile_fingerprint="1" * 64, compiled_at=now,
    )
    fact = CustomerFact(
        customer_id=customer.id, subject_type="customer", fact_key="business.industry",
        value_type="string", value_json={"value": "hair"}, fact_layer="confirmed",
        verification_status="verified", confidence=1, confidence_method_version="test",
        confidence_components_json={}, data_classification="internal_business",
        visibility_scope="customer_team", classification_reason="test", evidence_json={},
        fact_fingerprint="2" * 64, observed_at=now,
    )
    db.add_all([profile, fact])
    db.flush()
    customer.current_profile_version_id = profile.id
    payload_a = {"new_customer_ids": [customer.id], "proposal_redirects": [], "reason": "test"}
    payload_b = {"reason": "test", "proposal_redirects": [], "new_customer_ids": [customer.id]}
    assert canonical_action_hash(
        action_type="split", customer_id=customer.id, target_customer_id=None,
        payload_json=payload_a, profile_version_id=profile.id, evidence_fact_ids=[fact.id],
    ) == canonical_action_hash(
        action_type="split", customer_id=customer.id, target_customer_id=None,
        payload_json=payload_b, profile_version_id=profile.id, evidence_fact_ids=[fact.id],
    )

    for action_type in ("merge", "split", "set_dnc", "remove_dnc", "confirm_material_risk"):
        with pytest.raises(ProposalConflict, match="PROPOSAL_EXECUTOR_NOT_IMPLEMENTED"):
            create_proposal(
                db, customer_id=customer.id, target_customer_id=None,
                action_type=action_type, payload_schema_version=f"customer_{action_type}_v1",
                payload_json=payload_a, profile_version_id=profile.id,
                evidence_fact_ids=[fact.id], risk_level="critical",
                expires_at=now + timedelta(days=1), proposed_by=1,
            )

    assignment = create_proposal(
        db, customer_id=customer.id, target_customer_id=None, action_type="assign_primary",
        payload_schema_version="customer_assign_primary_v1",
        payload_json={"user_id": 3, "reason": "approved ownership"},
        profile_version_id=profile.id, evidence_fact_ids=[fact.id], risk_level="high",
        expires_at=now + timedelta(days=1), proposed_by=1,
    )
    submit_proposal(db, proposal_id=assignment.id, actor_user_id=1)
    approve_proposal(db, proposal_id=assignment.id, actor_user_id=2)
    executed = execute_proposal(
        db, proposal_id=assignment.id, actor_user_id=2,
        idempotency_key="execute-assignment-0001",
    )
    assert executed.status == "executed"
    assert execute_proposal(
        db, proposal_id=assignment.id, actor_user_id=2,
        idempotency_key="execute-assignment-0001",
    ).id == executed.id
    assert db.query(CustomerAssignment).filter_by(
        customer_id=customer.id, user_id=3, assignment_status="active",
    ).one().assignment_role == "primary"

    from app.core.time import beijing_now

    expires_on_approval = create_proposal(
        db, customer_id=customer.id, target_customer_id=None,
        action_type="assign_primary", payload_schema_version="customer_assign_primary_v1",
        payload_json={"user_id": 3, "reason": "expire before approval"},
        profile_version_id=profile.id, evidence_fact_ids=[fact.id], risk_level="high",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=1,
    )
    submit_proposal(db, proposal_id=expires_on_approval.id, actor_user_id=1)
    expires_on_approval.expires_at = beijing_now() - timedelta(seconds=1)
    db.flush()
    assert approve_proposal(
        db, proposal_id=expires_on_approval.id, actor_user_id=2,
    ).status == "expired"

    expires_on_execution = create_proposal(
        db, customer_id=customer.id, target_customer_id=None,
        action_type="assign_primary", payload_schema_version="customer_assign_primary_v1",
        payload_json={"user_id": 3, "reason": "expire before execution"},
        profile_version_id=profile.id, evidence_fact_ids=[fact.id], risk_level="high",
        expires_at=beijing_now() + timedelta(days=1), proposed_by=1,
    )
    submit_proposal(db, proposal_id=expires_on_execution.id, actor_user_id=1)
    approve_proposal(db, proposal_id=expires_on_execution.id, actor_user_id=2)
    expires_on_execution.expires_at = beijing_now() - timedelta(seconds=1)
    db.flush()
    assert execute_proposal(
        db, proposal_id=expires_on_execution.id, actor_user_id=2,
        idempotency_key="execute-expired-0001",
    ).status == "expired"

    db.commit()
    db.add(ArkUser(id=4, username="race-pending", password_hash="x", real_name="Pending", is_active=True))
    original_query = db.query
    forced_miss = {"pending": True}

    class MissingProposal:
        def filter(self, *_args, **_kwargs):
            return self

        def one_or_none(self):
            return None

    def query_with_stale_snapshot(*entities, **kwargs):
        if (
            len(entities) == 1 and entities[0] is CustomerChangeProposal
            and forced_miss["pending"]
        ):
            forced_miss["pending"] = False
            return MissingProposal()
        return original_query(*entities, **kwargs)

    monkeypatch.setattr(db, "query", query_with_stale_snapshot)
    with pytest.raises(ProposalConflict, match="PROPOSAL_CREATE_RETRY_NEW_TRANSACTION"):
        create_proposal(
            db, customer_id=customer.id, target_customer_id=None,
            action_type="assign_primary", payload_schema_version="customer_assign_primary_v1",
            payload_json={"user_id": 3, "reason": "approved ownership"},
            profile_version_id=profile.id, evidence_fact_ids=[fact.id], risk_level="high",
            expires_at=now + timedelta(days=1), proposed_by=1,
        )
    assert db.get(ArkUser, 4) is None
    assert db.get(CustomerChangeProposal, assignment.id) is not None


def test_customer_permissions_are_seeded_with_read_all_as_data_kind():
    from app.auth.service import seed_role_permissions

    assert "customer:read_all" in _DATA_KIND_CODES
    source = seed_role_permissions.__code__.co_consts
    assert any("customer:admin" in str(value) for value in source)


def test_proposal_create_recognizes_only_action_hash_unique_race():
    import inspect

    from sqlalchemy.exc import IntegrityError

    from app.customer import proposal_service

    action_hash_race = IntegrityError(
        "insert", {}, Exception(
            "UNIQUE constraint failed: ark_customer_change_proposals.action_hash"
        ),
    )
    unrelated_unique = IntegrityError(
        "insert", {}, Exception(
            "UNIQUE constraint failed: ark_customer_change_proposals.execution_idempotency_key"
        ),
    )
    assert proposal_service._is_action_hash_unique_conflict(action_hash_race) is True
    assert proposal_service._is_action_hash_unique_conflict(unrelated_unique) is False
    source = inspect.getsource(proposal_service.create_proposal)
    assert "begin_nested" in source
    assert "db.rollback()" in source
    assert "PROPOSAL_CREATE_RETRY_NEW_TRANSACTION" in source


def test_customer_hub_router_has_unified_human_endpoints_and_no_legacy_aliases():
    paths = {route.path for route in customer_router.router.routes}
    assert "/customers" in paths
    assert "/customers/{customer_id}" in paths
    assert "/customers/{customer_id}/timeline" in paths
    assert "/research-tasks" in paths
    assert "/acquisition-profile" in paths
    assert "/search-jobs" in paths
    assert "/public-pool/batches" in paths
    assert "/qualification-queue" in paths
    assert "/opportunities" in paths
    assert "/actions" in paths
    assert "/change-proposals" in paths
    assert "/change-proposals/{proposal_id}/submit" in paths
    assert "/change-proposals/{proposal_id}/approve" in paths
    assert "/change-proposals/{proposal_id}/reject" in paths
    assert "/change-proposals/{proposal_id}/execute" in paths


def test_customer_hub_router_is_registered_once_and_legacy_human_paths_removed():
    import inspect
    from app.insight import router as insight_router
    from app.sales_automation import router as sales_router

    source = inspect.getsource(register_routers)
    assert 'prefix="/api/customer-hub"' in source
    insight_paths = {route.path for route in insight_router.router.routes}
    sales_paths = {route.path for route in sales_router.router.routes}
    assert not any(path.startswith("/customer-opportunities") for path in insight_paths)
    assert not any(path.startswith("/customer-radar") for path in insight_paths)
    assert "/research-tasks" not in sales_paths
    assert "/public-pool/batches" not in sales_paths


def test_hub_read_endpoints_require_their_distinct_read_code(db):
    from datetime import datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkUser
    from app.core.database import get_db
    from app.customer.models import CustomerAccount, CustomerAssignment

    now = datetime(2026, 8, 30, 9, 0)
    db.add(ArkUser(id=81, username="distinct-reader", password_hash="x", real_name="Reader", is_active=True))
    customer = CustomerAccount(
        customer_code="C-DISTINCT", display_name="Distinct Co",
        entity_type="registered_company", identity_status="verified",
        relationship_stage="qualified", relationship_stage_changed_at=now,
        relationship_stage_reason="test", record_status="active",
        identity_confidence=1, profile_completeness=80, profile_input_seq=0,
    )
    db.add(customer)
    db.flush()
    db.add(CustomerAssignment(
        customer_id=customer.id, user_id=81, assignment_role="primary",
        assignment_status="active", assignment_source="manual", effective_from=now,
    ))
    db.flush()
    identity = {"sub": "81", "roles": [], "permissions": ["customer:read"]}
    app = FastAPI()
    app.include_router(customer_router.router, prefix="/api/customer-hub")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity

    with TestClient(app) as client:
        assert client.get("/api/customer-hub/customers").status_code == 200
        assert client.get("/api/customer-hub/research-tasks").status_code == 403
        assert client.get("/api/customer-hub/opportunities").status_code == 403
        assert client.get("/api/customer-hub/actions").status_code == 403

        for permission in (
            "sales_automation:read", "customer_opportunity:read", "customer_radar:read",
        ):
            identity["permissions"] = [permission]
            assert client.get("/api/customer-hub/customers").status_code == 403

        identity["permissions"] = ["customer:read_all"]
        for path in ("customers", "research-tasks", "opportunities", "actions"):
            assert client.get(f"/api/customer-hub/{path}").status_code == 200


def test_public_pool_research_returns_only_safe_summary(db):
    from datetime import datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkUser
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
        return CustomerChangeProposal(
            customer_id=source.id, target_customer_id=target.id,
            action_type="assign_primary", payload_schema_version="customer_assign_primary_v1",
            payload_json={"user_id": 102, "reason": f"secret-{token}"},
            profile_version_id=profile.id, evidence_fact_ids=[fact.id], risk_level="high",
            data_classification="restricted_internal", visibility_scope="management",
            action_hash=token * 64, expires_at=now + timedelta(days=1),
            status="draft", proposed_by=101,
        )

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
