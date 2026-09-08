"""External claim → real fact receipt → governed completion regression."""
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent_runtime.models import AgentRun, AgentEvent, AgentSession
from app.agent_runtime.seed import seed_default_profiles
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer.models import CustomerFact, CustomerAgentRunScope, CustomerResearchTask
from app.sales_automation import agent_router, public_pool_service as service, research_run_service
from app.sales_automation.dependencies import require_sales_agent
from tests.test_public_pool_research import _task, _governed_run

FACT = {"fact_key": "business.industry", "value_type": "string", "value": "hair extensions",
    "fact_layer": "source", "confidence": 0.9, "source_system": "public_web",
    "source_entity_type": "company_page", "external_record_id": "official-about",
    "source_url": "https://example.test/about", "observed_at": "2026-09-08T10:00:00+08:00"}


@pytest.fixture
def bridge(engine):
    with Session(engine, autoflush=False) as db:
        task = _task(db)
        seed_default_profiles(db)
        app = FastAPI()
        app.include_router(agent_router.router, prefix="/api/sales-automation")
        def get_test_db():
            try:
                yield db
            finally:
                db.rollback()
        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_sales_agent] = lambda: {
            "sub": "1", "permissions": ["sales_automation:invoke"]}
        with TestClient(app) as client:
            yield db, task.id, client


def post(client, task_id, action, **body):
    return client.post(f"/api/sales-automation/agent/research-tasks/{task_id}/{action}",
                       json={"agent_id": "research-agent", **body})


def claim(client, task_id):
    response = post(client, task_id, "claim")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def result_from(claimed, receipt):
    ref = receipt["evidence_refs"][0]
    return {"schema_version": "customer_research_v1", "input_hash": claimed["input_hash"],
        "claims": [{"claim_id": "claim_1", "section": "business_quality",
            "statement": "The official page describes hair extensions.", "citation_ids": ["citation_1"]}],
        "citations": [{"citation_id": "citation_1", "claim_id": "claim_1",
            "tool_call_id": receipt["tool_call_id"], "evidence_ref": ref["evidence_ref"],
            "evidence_content_hash": ref["evidence_content_hash"]}], "knowledge_references": []}


def test_complete_and_lost_fact_response_retry(bridge):
    db, task_id, client = bridge
    claimed = claim(client, task_id)
    auth = {"lease_token": claimed["lease_token"], "agent_run_id": claimed["agent_run_id"]}
    run = db.get(AgentRun, claimed["agent_run_id"])
    assert run.status == "running"
    assert db.query(CustomerAgentRunScope).filter_by(run_id=run.id).one().customer_id == claimed["customer_id"]
    assert post(client, task_id, "industry-gate", lease_token=auth["lease_token"],
                industry_relevance="core", reason="Official company page describes hair products.").status_code == 200
    receipts = []
    for _ in range(2):
        response = post(client, task_id, "facts", **auth, facts=[FACT])
        assert response.status_code == 200, response.text
        receipts.append(response.json()["data"])
    assert receipts[0]["evidence_refs"] == receipts[1]["evidence_refs"]
    assert db.query(CustomerFact).count() == 1
    result = result_from(claimed, receipts[-1])
    wrong = result_from(claimed, receipts[-1])
    wrong["citations"][0]["tool_call_id"] = "invented"
    assert post(client, task_id, "complete", **auth, result_json=wrong).status_code == 409
    response = post(client, task_id, "complete", **auth, result_json=result)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["task_status"] == "completed"
    db.refresh(run)
    assert run.status == "completed"


def test_claim_and_fact_error_are_atomic(bridge, monkeypatch):
    db, task_id, client = bridge
    original = research_run_service.start_run
    def fail(db, *args):
        original(db, *args)
        raise service.service.ConflictError("injected failure")
    monkeypatch.setattr(research_run_service, "start_run", fail)
    assert post(client, task_id, "claim").status_code == 409
    assert db.get(CustomerResearchTask, task_id).task_status == "pending"
    assert db.query(AgentRun).count() == db.query(AgentSession).count() == 0
    monkeypatch.setattr(research_run_service, "start_run", original)
    claimed = claim(client, task_id)
    response = post(client, task_id, "facts", lease_token=claimed["lease_token"],
        agent_run_id=claimed["agent_run_id"], facts=[FACT, dict(FACT, fact_key="not_registered")])
    assert response.status_code >= 400
    assert db.query(CustomerFact).count() == 0
    assert db.query(AgentEvent).filter_by(event_type="tool.requested").count() == 0


def test_reclaim_fences_old_and_alternative_runs(bridge):
    db, task_id, client = bridge
    first = claim(client, task_id)
    task = db.get(CustomerResearchTask, task_id)
    task.lease_expires_at = beijing_now() - timedelta(seconds=1)
    db.commit()
    second = claim(client, task_id)
    assert first["agent_run_id"] != second["agent_run_id"]
    assert db.get(AgentRun, first["agent_run_id"]).status == "cancelled"
    auth = {"lease_token": second["lease_token"]}
    assert post(client, task_id, "facts", **auth, agent_run_id=first["agent_run_id"], facts=[FACT]).status_code == 409
    alternate = _governed_run(db, db.get(CustomerResearchTask, task_id))
    db.commit()
    assert post(client, task_id, "facts", **auth, agent_run_id=alternate.id, facts=[FACT]).status_code == 409
    assert post(client, task_id, "facts", lease_token=first["lease_token"],
                agent_run_id=second["agent_run_id"], facts=[FACT]).status_code == 409


@pytest.mark.parametrize('terminal', ['fail', 'irrelevant'])
def test_terminal_task_closes_external_run(bridge, terminal):
    db, task_id, client = bridge
    claimed = claim(client, task_id)
    if terminal == 'fail':
        response = post(client, task_id, 'fail', lease_token=claimed['lease_token'], error_code='agent_execution_failed')
    else:
        response = post(client, task_id, 'industry-gate', lease_token=claimed['lease_token'],
                        industry_relevance='irrelevant', reason='Official source shows unrelated business.')
    assert response.status_code == 200, response.text
    assert db.get(AgentRun, claimed['agent_run_id']).status == ('failed' if terminal == 'fail' else 'completed')


def test_explicit_retry_preserves_fencing_and_rejects_stale_requests(bridge):
    db, task_id, client = bridge
    first = claim(client, task_id)
    post(client, task_id, 'fail', lease_token=first['lease_token'], error_code='agent_execution_failed')
    with pytest.raises(service.service.ConflictError):
        research_run_service.requeue_failed_task(db, task_id, 1, 7)
    db.rollback()
    research_run_service.requeue_failed_task(db, task_id, 1, 1)
    with pytest.raises(service.service.ConflictError):
        research_run_service.requeue_failed_task(db, task_id, 1, 1)
    db.rollback()
    second = claim(client, task_id)
    assert second['lease_generation'] == first['lease_generation'] + 1
    assert second['agent_run_id'] != first['agent_run_id']
    assert post(client, task_id, 'facts', lease_token=second['lease_token'],
        agent_run_id=first['agent_run_id'], facts=[FACT]).status_code == 409


def test_retry_endpoint_requires_admin_and_customer_scope(bridge):
    from app.auth.dependencies import get_current_user
    from app.customer.router import router
    db, task_id, client = bridge
    claimed = claim(client, task_id)
    post(client, task_id, 'fail', lease_token=claimed['lease_token'], error_code='agent_execution_failed')
    identity = {'sub':'1','roles':[], 'permissions':['sales_automation:read']}
    app = FastAPI()
    app.include_router(router, prefix='/api/customer-hub')
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: identity
    url = f'/api/customer-hub/research-tasks/{task_id}/retry?expected_attempt_count=1'
    with TestClient(app) as human:
        assert human.post(url).status_code == 403
        identity['permissions'].append('sales_automation:admin')
        assert human.post(url).status_code == 404
        assert db.get(CustomerResearchTask, task_id).task_status == 'failed'
        identity['permissions'].append('customer:read_all')
        response = human.post(url)
        assert response.status_code == 200, response.text
        assert response.json()['data']['task_status'] == 'pending'


def test_published_fact_contract_and_company_evidence_complete(bridge):
    from app.customer.contracts import PUBLIC_RESEARCH_FACT_DESCRIPTIONS, FACT_REGISTRY
    db, task_id, client = bridge
    context = client.get(f'/api/sales-automation/agent/research-tasks/{task_id}/context').json()['data']
    contract = context['fact_contract']
    source = next(s for s in contract['sources'] if s['source_system'] == 'public_web')
    keys = {f['fact_key'] for f in source['facts']}
    assert keys == {'business.industry', *PUBLIC_RESEARCH_FACT_DESCRIPTIONS}
    claimed = claim(client, task_id)
    auth = {'lease_token': claimed['lease_token'], 'agent_run_id': claimed['agent_run_id']}
    assert post(client, task_id, 'industry-gate', lease_token=auth['lease_token'],
                industry_relevance='core', reason='Official hair extension catalog').status_code == 200
    facts = [dict(FACT, fact_key=key, value='Official page statement '+key,
                  external_record_id='official-'+key) for key in PUBLIC_RESEARCH_FACT_DESCRIPTIONS]
    response = post(client, task_id, 'facts', **auth, facts=facts)
    assert response.status_code == 200, response.text
    receipt = response.json()['data']
    assert len(receipt['evidence_refs']) == 4
    assert all(f.verification_status == 'candidate' for f in db.query(CustomerFact).all())
    for key in PUBLIC_RESEARCH_FACT_DESCRIPTIONS:
        assert FACT_REGISTRY[key].allowed_purposes == frozenset({'research'})
        assert not FACT_REGISTRY[key].supports_high_impact
    result = result_from(claimed, receipt)
    result['claims'][0]['section'] = 'identity'
    result['claims'][0]['statement'] = facts[0]['value']
    response = post(client, task_id, 'complete', **auth, result_json=result)
    assert response.status_code == 200, response.text
    assert response.json()['data']['task_status'] == 'completed'


@pytest.mark.parametrize('change,code', [
    ({'fact_key':'company.name'}, 'FACT_NOT_REGISTERED'),
    ({'fact_key':'commercial.has_valid_order', 'value_type':'boolean', 'value':True}, 'FACT_SOURCE_NOT_ALLOWED'),
    ({'fact_key':'research.source.company_identity', 'value_type':'object', 'value':{}}, 'FACT_VALUE_INVALID'),
])
def test_fact_contract_rejections_are_actionable_and_atomic(bridge, change, code):
    db, task_id, client = bridge
    claimed = claim(client, task_id)
    response = post(client, task_id, 'facts', lease_token=claimed['lease_token'],
                    agent_run_id=claimed['agent_run_id'], facts=[FACT, dict(FACT, **change)])
    assert response.status_code == 400
    assert code in response.json()['detail']
    assert db.query(CustomerFact).count() == 0
    assert db.query(AgentEvent).filter_by(event_type='tool.succeeded').count() == 0
