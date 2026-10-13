"""A research gap closes the leased Run without weakening fact-backed results."""
from datetime import timedelta

import pytest

from app.agent_runtime.models import AgentRun
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerFact, CustomerResearchTask
from app.sales_automation import public_pool_service as service
from tests.test_research_run_bridge import bridge, claim, post, FACT


def prepare(db, task_id, client, industry_relevance="uncertain"):
    task = db.get(CustomerResearchTask, task_id)
    task.task_type = "full_research"
    task.research_policy_version = "private-enrichment-v1"
    db.commit()
    claimed = claim(client, task_id)
    auth = {"lease_token": claimed["lease_token"], "agent_run_id": claimed["agent_run_id"]}
    response = post(client, task_id, "industry-gate", lease_token=auth["lease_token"],
                    industry_relevance=industry_relevance, reason="Only a name is available; no business identity can be verified.")
    assert response.status_code == 200, response.text
    gap = {"schema_version": "research_gap_v1", "input_hash": claimed["input_hash"],
           "gap_reason": "只有姓名，未找到可确认属于该客户的公开商业主体。",
           "missing_information": ["公司名称、城市或官网中任意一项"]}
    return task, claimed, auth, gap


def test_gap_finishes_same_run_and_preserves_customer(bridge):
    db, task_id, client = bridge
    task, claimed, auth, gap = prepare(db, task_id, client)
    account = db.get(CustomerAccount, task.customer_id)
    original = {column.name: getattr(account, column.name) for column in account.__table__.columns}
    response = post(client, task_id, "complete", **auth, result_json=gap)
    assert response.status_code == 200, response.text
    db.refresh(task)
    db.refresh(account)
    assert task.task_status == "completed"
    assert task.result_review_status == "not_required"
    assert task.result_schema_version == "research_gap_v1"
    assert task.result_json["industry_gate"]["industry_relevance"] == "uncertain"
    assert task.result_json["missing_information"] == gap["missing_information"]
    assert task.evidence_fact_ids == []
    assert task.finished_at is not None
    assert task.claimed_by is task.lease_token_hash is task.lease_expires_at is None
    assert db.get(AgentRun, claimed["agent_run_id"]).status == "completed"
    assert db.query(CustomerFact).count() == 0
    assert {column.name: getattr(account, column.name) for column in account.__table__.columns} == original
    assert post(client, task_id, "complete", **auth, result_json=gap).status_code == 409


@pytest.mark.parametrize("boundary", ["policy", "type", "gate", "hash", "run", "lease", "expiry", "facts"])
def test_gap_cannot_bypass_task_or_evidence_boundaries(bridge, boundary):
    db, task_id, client = bridge
    task, claimed, auth, gap = prepare(db, task_id, client, "core" if boundary == "gate" else "uncertain")
    if boundary == "policy":
        task.research_policy_version = "research-v1"
    elif boundary == "type":
        task.task_type = "public_pool"
    elif boundary == "hash":
        gap["input_hash"] = "b" * 64
    elif boundary == "run":
        auth["agent_run_id"] += 1
    elif boundary == "lease":
        auth["lease_token"] = "wrong-lease-token" * 4
    elif boundary == "expiry":
        task.lease_expires_at = beijing_now() - timedelta(seconds=1)
    elif boundary == "facts":
        response = post(client, task_id, "facts", **auth, facts=[FACT])
        assert response.status_code == 200, response.text
    db.commit()
    response = post(client, task_id, "complete", **auth, result_json=gap)
    assert response.status_code == 409, response.text
    assert db.get(CustomerResearchTask, task_id).task_status == "running"
    assert db.get(AgentRun, claimed["agent_run_id"]).status == "running"


@pytest.mark.parametrize("extra", [{"claims": []}, {"citations": []}, {"identity_status": "verified"}])
def test_gap_rejects_positive_result_fields(bridge, extra):
    db, task_id, client = bridge
    _task, _claimed, auth, gap = prepare(db, task_id, client)
    assert post(client, task_id, "complete", **auth, result_json={**gap, **extra}).status_code == 422


def test_empty_fact_backed_result_is_still_invalid(bridge):
    db, task_id, client = bridge
    _task, claimed, auth, _gap = prepare(db, task_id, client)
    result = {"schema_version": "customer_research_v1", "input_hash": claimed["input_hash"],
              "claims": [], "citations": []}
    assert post(client, task_id, "complete", **auth, result_json=result).status_code == 422


def test_gap_inherits_stricter_visibility_and_cannot_be_reviewed(bridge):
    db, task_id, client = bridge
    task, _claimed, auth, gap = prepare(db, task_id, client)
    response = post(client, task_id, "complete", **auth, result_json=gap,
                    data_classification="restricted_internal", visibility_scope="management")
    assert response.status_code == 200, response.text
    db.refresh(task)
    assert (task.data_classification, task.visibility_scope) == ("restricted_internal", "management")
    for status in ("accepted", "revision_requested", "rejected"):
        with pytest.raises(service.service.ConflictError):
            service.review_research_result(db, task_id, status, reviewer_id=1)
        db.rollback()
    assert db.get(CustomerResearchTask, task_id).result_review_status == "not_required"


def test_gap_does_not_block_a_new_request_and_cannot_qualify_even_with_corrupt_review_status(bridge):
    from app.sales_automation.private_enrichment_service import ensure_enrichment_task
    db, task_id, client = bridge
    task, _claimed, auth, gap = prepare(db, task_id, client)
    assert post(client, task_id, "complete", **auth, result_json=gap).status_code == 200
    new_task, created = ensure_enrichment_task(db, customer_id=task.customer_id, operator_id=1,
        run_tag="new-clues", input_snapshot={"schema_version":"research_input_v1"}, tier="T3")
    assert created and new_task.id != task_id
    task.result_review_status = "accepted"
    db.commit()
    assert all(row.id != task_id for row in service.list_pending_qualification(db))
    from app.customer.qualification_service import _ranked_research
    from app.customer.workflow_service import _qualification_source_key, CustomerWorkflowConflict
    from types import SimpleNamespace
    ranked = _ranked_research(db, {"sub":"1", "roles":["super_admin"], "permissions":[]})
    assert db.query(ranked).filter(ranked.c.task_id == task_id).first() is None
    with pytest.raises(CustomerWorkflowConflict, match="QUALIFICATION_SOURCE_INVALID"):
        _qualification_source_key(db, SimpleNamespace(review_source="public_pool_research",
            source_ref_id=str(task_id), customer_id=task.customer_id))
    with pytest.raises(service.service.ConflictError):
        service.submit_qualification_review(db, customer_id=task.customer_id,
            review_source="public_pool_research", source_ref_id=str(task_id), decision="approved",
            reason_code="qualified", reason_text="Should be rejected", reviewed_by=1,
            scope_type="global", scope_ref_id=None, policy_version="test-v1", review_snapshot={},
            decision_request_key="gap-must-not-qualify", expected_current_review_id=None)
