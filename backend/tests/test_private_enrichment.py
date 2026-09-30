"""Private enrichment scope, deduplication and preservation (isolated SQLite)."""
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer import enrichment_service, profile_service
from app.customer.enrichment_router import router
from app.customer.pcw_errors import register_pcw_error_handler
from app.customer.models import CustomerAccount, CustomerAnnotation, CustomerResearchTask
from app.sales_automation import private_research_service, agent_router, public_pool_service
from app.sales_automation.private_enrichment_service import POLICY_VERSION
from tests.test_private_research_service import _sales, _assign
from tests.test_public_pool_research import _account, _task, _governed_run, _research_fact
from tests.test_customer_profile_compiler import _fact


def actor(user_id=1, permissions=None):
    return {"sub": str(user_id), "roles": [], "permissions": permissions if permissions is not None else ["customer:read", "customer_profile:write"]}


def seeded(db):
    _sales(db, 1, "alice")
    customer = _account(db, "PRIVATE")
    _assign(db, customer.id, 1)
    db.commit()
    return customer


def test_single_request_reuses_active_and_unreviewed_task(db):
    customer = seeded(db)
    first = enrichment_service.request_enrichment(db, customer.id, actor())
    second = enrichment_service.request_enrichment(db, customer.id, actor())
    assert first["created"] is True
    assert second["created"] is False
    assert first["task"]["research_task_id"] == second["task"]["research_task_id"]
    task = db.get(CustomerResearchTask, first["task"]["research_task_id"])
    task.task_status = "completed"
    task.gate_status = "passed"
    db.flush()
    assert enrichment_service.request_enrichment(db, customer.id, actor())["created"] is False
    task.result_review_status = "accepted"
    db.flush()
    assert enrichment_service.request_enrichment(db, customer.id, actor())["created"] is True


def test_all_private_skips_dnc_public_inactive_and_dry_run_rolls_back(db):
    first = seeded(db)
    _sales(db, 2, "bob")
    second = _account(db, "SECOND")
    blocked = _account(db, "BLOCKED")
    archived = _account(db, "ARCHIVED")
    _account(db, "PUBLIC")
    for customer in [second, blocked, archived]:
        _assign(db, customer.id, 2)
    archived.record_status = "archived"
    db.add(CustomerAnnotation(customer_id=blocked.id, annotation_type="do_not_contact",
        content_schema_version="v1", content_json={"reason": "stop"}, policy_scope_type="global",
        policy_effective_at=beijing_now()-timedelta(days=1), visibility="customer_team",
        data_classification="internal_business", status="active", authored_by=1))
    db.flush()
    summary = private_research_service.create_private_research_tasks(db, owner_ids=None,
        run_tag="all-private-test", operator_id=1, enrichment=True, commit=False)
    assert {row["customer_id"] for row in summary["tasks"]} == {first.id, second.id}
    assert summary["skipped_dnc"] == [blocked.id]
    assert summary["skipped_unresolvable"] == [archived.id]
    assert summary["policy_version"] == POLICY_VERSION
    for item in summary["tasks"]:
        context = agent_router._research_context(db, item["task_id"])
        assert len(context["research_rules"]["task_request"]["focus"]) == 4
        assert context["input_snapshot"]["existing_information"]["display_name"]
    db.rollback()
    assert db.query(CustomerResearchTask).count() == 0


def test_other_customer_denied_and_public_pool_rejected(db):
    customer = seeded(db)
    _sales(db, 2, "bob")
    app = FastAPI()
    app.include_router(router)
    register_pcw_error_handler(app)
    app.dependency_overrides[get_db] = lambda: db
    identity = actor(2)
    app.dependency_overrides[get_current_user] = lambda: identity
    with TestClient(app) as client:
        path = f"/customers/{customer.id}/enrichment"
        assert client.get(path).status_code == 404
        assert client.post(path).status_code == 404
        identity.update(actor(1, ["customer:read"]))
        assert client.post(path).status_code == 403
        identity.update(actor())
        assert client.post(path).status_code == 200
        assert client.get(path).json()["data"]["task_status"] == "pending"
        public = _account(db, "PUBLIC-ONLY")
        identity.update({"sub": "1", "roles": ["super_admin"], "permissions": []})
        response = client.post(f"/customers/{public.id}/enrichment")
        assert response.status_code == 409
        assert response.json()["data"]["error_code"] == "PRIVATE_CUSTOMER_REQUIRED"


@pytest.mark.parametrize("review_status", ["pending", "accepted"])
def test_candidate_never_replaces_existing_profile_even_after_reclaim(db, review_status):
    task = _task(db, policy=POLICY_VERSION)
    customer = db.get(CustomerAccount, task.customer_id)
    old = _fact(db, customer, key="business.industry", value="original business", layer="source", status="unverified")
    public_pool_service.claim_task(db, task.id, 1, "research-agent")
    run = _governed_run(db, task)
    task.agent_run_id = run.id
    db.flush()
    candidate = _research_fact(db, task, run)
    candidate.confidence = 1
    task.agent_run_id = None
    task.task_status = "completed"
    task.gate_status = "passed"
    task.result_review_status = review_status
    db.flush()
    snapshot = profile_service._load_snapshot(db, customer, beijing_now())
    assert old.id in {row["id"] for row in snapshot.facts}
    assert candidate.id not in {row["id"] for row in snapshot.facts}
    assert old.value_json["value"] == "original business"
    assert old.verification_status == "unverified"


def test_first_candidate_stays_out_of_profile_but_legacy_research_unchanged(db):
    for policy in [POLICY_VERSION, "full-research-v1"]:
        task = _task(db, policy=policy, customer_code=policy)
        public_pool_service.claim_task(db, task.id, 1, "research-agent")
        run = _governed_run(db, task)
        task.agent_run_id = run.id
        db.flush()
        fact = _research_fact(db, task, run, suffix=policy)
        snapshot = profile_service._load_snapshot(db, db.get(CustomerAccount, task.customer_id), beijing_now())
        assert (fact.id in {row["id"] for row in snapshot.facts}) == (policy != POLICY_VERSION)


def test_snapshot_excludes_restricted_facts(db):
    customer = seeded(db)
    public = _fact(db, customer, key="business.industry", value="hair", layer="source")
    _fact(db, customer, key="profile.private", value="private", layer="source", classification="restricted_internal", visibility="management")
    result = enrichment_service.request_enrichment(db, customer.id, actor())
    facts = result["task"]["input_snapshot"]["existing_information"]["facts"]
    assert [item["id"] for item in facts] == [public.id]


def test_snapshot_uses_latest_visible_manual_revision(db):
    customer = seeded(db)
    for value, visibility in [("old", "customer_team"), ("current", "customer_team"), ("secret", "management")]:
        db.add(CustomerAnnotation(customer_id=customer.id, annotation_type="note", content_schema_version="v2",
            content_json={"revision_kind": "profile_field_revision", "field_key": "profile.business_type",
                          "value": value, "reason": "customer confirmed", "evidence_refs": []},
            visibility=visibility, data_classification="internal_business", status="active", authored_by=1))
    db.flush()
    result = enrichment_service.request_enrichment(db, customer.id, actor())
    revisions = result["task"]["input_snapshot"]["existing_information"]["current_manual_revisions"]
    assert len(revisions) == 1
    assert revisions[0]["value"] == "current"
    assert revisions[0]["annotation_id"]


def test_transferred_task_is_not_reused_for_new_owner(db):
    from app.customer.models import CustomerObjectOwnership

    customer = seeded(db)
    old = enrichment_service.request_enrichment(db, customer.id, actor())
    target = _account(db, "TRANSFER-TARGET")
    _assign(db, target.id, 1)
    db.add(CustomerObjectOwnership(object_type="research_task", object_id=old["task"]["research_task_id"],
        storage_customer_id=customer.id, current_customer_id=target.id, ownership_version=1,
        last_action_type="split", last_change_proposal_id=1))
    db.flush()
    assert enrichment_service.latest_enrichment(db, target.id, actor()) is None
    new = enrichment_service.request_enrichment(db, target.id, actor())
    assert new["created"] is True
    assert new["task"]["research_task_id"] != old["task"]["research_task_id"]
    assert db.get(CustomerResearchTask, new["task"]["research_task_id"]).customer_id == target.id
