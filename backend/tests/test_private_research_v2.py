"""Private research v2 queue, lease and report validation regressions."""

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent_runtime.seed import seed_default_profiles
from app.core.database import get_db
from app.customer.models import CustomerContactPoint, CustomerResearchTask
from app.sales_automation import agent_router, private_research_service as private, public_pool_service as public
from app.sales_automation.dependencies import require_sales_agent
from app.sales_automation.private_research_policy import PRIVATE_RESEARCH_POLICY, PRIVATE_RESEARCH_RESULT
from app.sales_automation.service import ConflictError
from tests.test_private_research_service import _account, _assign, _create, _order, _sales
from tests.test_research_run_bridge import FACT, post, result_from


def test_priority_supersession_cooldown_and_order_filter(db, monkeypatch):
    _sales(db, 1, "research-owner")
    old = _account(db, "old")
    waiting = _account(db, "waiting")
    no_orders = _account(db, "no-order")
    for account in (old, waiting, no_orders):
        _assign(db, account.id, 1)
    for account in (old, waiting):
        _order(db, account, external_id=f"order-{account.id}", amount="100")
    batch = _create(db, [1], private_v2=True, with_orders=True, unresearched=True)
    assert batch["policy_version"] == PRIVATE_RESEARCH_POLICY
    assert {row["customer_id"] for row in batch["tasks"]} == {old.id, waiting.id}
    prior = db.query(CustomerResearchTask).filter_by(customer_id=old.id).one()
    prior.task_status = "completed"
    prior.gate_status = "passed"
    prior.result_review_status = "revision_requested"
    prior.result_schema_version = PRIVATE_RESEARCH_RESULT
    db.commit()
    second_batch = _create(db, [1], private_v2=True, with_orders=True, unresearched=True, run_tag="later")
    assert {row["customer_id"] for row in second_batch["tasks"]} == {waiting.id}

    status = private.rerun_private_research(db, customer_id=old.id, owner_user_id=1)
    assert status["status"] == "pending"
    assert not status["can_rerun"]
    assert prior.task_status == prior.result_review_status == "superseded"
    with pytest.raises(ConflictError, match="冷却"):
        private.rerun_private_research(db, customer_id=old.id, owner_user_id=1)
    db.rollback()
    assert public.list_claimable_tasks(db, 1, 10)[0] == []
    claimable = public.list_claimable_tasks(db, 1, 10, include_private_v2=True)[0]
    assert [task.customer_id for task in claimable] == [old.id, waiting.id]
    # A naive date from the Beijing clock crosses day 30 at midnight, independent of the host.
    claimable[0].created_at = datetime(2026, 11, 16, 0, 0, 0)
    db.flush()
    cooldown = datetime(2026, 12, 16, 0, 0, 0)
    monkeypatch.setattr(private, "beijing_now", lambda: cooldown - timedelta(seconds=1))
    assert private.private_research_status(db, customer_id=old.id)["cooldown_remaining_seconds"] == 1
    monkeypatch.setattr(private, "beijing_now", lambda: cooldown)
    assert private.private_research_status(db, customer_id=old.id)["can_rerun"]


@pytest.fixture
def private_task(db):
    _sales(db, 1, "research-owner")
    account = _account(db, "private-customer")
    account.canonical_company_name = None
    _assign(db, account.id, 1)
    db.add(CustomerContactPoint(
        customer_id=account.id, point_type="email", raw_value="jane@example.test",
        normalized_value="jane@example.test", email_domain_type="free",
        verification_status="unknown", contactability_status="unknown",
        is_primary=False, data_classification="personal_contact",
        point_fingerprint="f" * 64, first_seen_at=datetime(2026, 11, 16), last_seen_at=datetime(2026, 11, 16),
    ))
    db.flush()
    batch = _create(db, [1], private_v2=True)
    task_id = batch["tasks"][0]["task_id"]
    seed_default_profiles(db)

    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api/sales-automation")

    def test_db():
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[require_sales_agent] = lambda: {"sub": "1"}
    with TestClient(app) as client:
        yield task_id, client


def test_leased_personal_seed_and_marked_report(db, private_task):
    task_id, client = private_task
    context_url = f"/api/sales-automation/agent/research-tasks/{task_id}/context"
    context = client.get(context_url).json()["data"]
    assert context["requires_lease_for_context"] is True
    assert "input_snapshot" not in context
    assert "jane@example.test" not in str(context)
    assert post(client, task_id, "claim").status_code == 409
    claimed = post(client, task_id, "claim", supports_private_v2=True).json()["data"]
    lease = claimed["lease_token"]
    assert post(client, task_id, "context", lease_token="x" * 32).status_code == 409
    context = post(client, task_id, "context", lease_token=lease).json()["data"]
    assert context["input_snapshot"]["lead_track"] == "weak"
    assert context["input_snapshot"]["existing_information"]["business_contacts"][0]["value"] == "jane@example.test"
    assert "social_profile" in {source["source_entity_type"] for source in context["fact_contract"]["sources"]}
    assert post(client, task_id, "industry-gate", lease_token=lease, industry_relevance="uncertain",
                reason="Public evidence only verifies that the business offers hair extensions.").status_code == 200

    auth = {"lease_token": lease, "agent_run_id": claimed["agent_run_id"]}
    fact = dict(FACT, value="该公司提供接发服务", source_url="https://verified.example/services")
    receipt = post(client, task_id, "facts", **auth, facts=[fact]).json()["data"]
    assert receipt["evidence_refs"][0]["data_classification"] == "personal_contact"
    result = result_from(claimed, receipt)
    result.update(schema_version=PRIVATE_RESEARCH_RESULT, report_markdown=(
        "1. 该公司提供接发服务\n"
        "2. [Jane Doe](https://verified.example/services)\n"
        "[资料](https://unverified.example/here)\n"
        "邮箱 jane@example.test，电话 +1 (646) 555-0123，粉丝 20万。"
    ), missing_information=["主体仍需核实"], names=["Jane Doe"])
    result["claims"][0]["statement"] = "该公司提供接发服务"
    response = post(client, task_id, "complete", **auth, result_json=result)
    assert response.status_code == 200, response.text
    task = db.get(CustomerResearchTask, task_id)
    assert task.data_classification == "personal_contact"
    assert task.result_review_status == "pending"
    markdown = task.result_json["report_markdown"]
    assert "1. 该公司" in markdown and "2. [Jane Doe〔待核实〕]" in markdown
    assert "verified.example/services)〔待核实〕" not in markdown
    assert "unverified.example/here)〔待核实〕" in markdown
    assert "jane@example.test〔待核实〕" in markdown
    assert "555-0123〔待核实〕" in markdown
    assert "20万〔待核实〕" in markdown
    assert task.result_json["verified_claims"] == ["该公司提供接发服务"]
    assert post(client, task_id, "context", lease_token=lease).status_code == 409


def test_gap_with_existing_facts_still_completes(private_task):
    task_id, client = private_task
    claimed = post(client, task_id, "claim", supports_private_v2=True).json()["data"]
    auth = {"lease_token": claimed["lease_token"], "agent_run_id": claimed["agent_run_id"]}
    assert post(client, task_id, "industry-gate", lease_token=auth["lease_token"],
                industry_relevance="uncertain", reason="身份资料不足").status_code == 200
    assert post(client, task_id, "facts", **auth, facts=[FACT]).status_code == 200
    response = post(client, task_id, "complete", **auth, result_json={
        "schema_version": PRIVATE_RESEARCH_RESULT, "input_hash": claimed["input_hash"],
        "report_markdown": "已有线索不足以确认主体。", "claims": [], "citations": [],
        "missing_information": ["未能核实公司主体"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["result_review_status"] == "pending"


def test_async_scan_receipt_is_citable_through_http(private_task, engine, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.orm import sessionmaker

    from app.sales_automation import research_tools_providers, research_tools_service, research_tools_worker
    from app.sales_automation.research_tools_models import ResearchToolCall

    ResearchToolCall.__table__.create(engine, checkfirst=True)
    settings = SimpleNamespace(
        PRIVATE_RESEARCH_TOOLS_WORKER_ENABLED=True,
        PRIVATE_RESEARCH_MAIGRET_ENABLED=True,
        PRIVATE_RESEARCH_MAIGRET_TOKEN="x" * 24,
        PRIVATE_RESEARCH_MONID_ENABLED=False,
        PRIVATE_RESEARCH_MONID_API_KEY="",
        PRIVATE_RESEARCH_EGRESS_PROXY="",
    )
    monkeypatch.setattr(research_tools_service, "get_settings", lambda: settings)
    monkeypatch.setattr(research_tools_providers, "scan", lambda *_: {
        "checked": 10, "connection_failures": 0, "unknown": 0,
        "hits": [{"site": "Instagram", "url": "https://www.instagram.com/jane.example"}],
    })
    task_id, client = private_task
    claim = post(client, task_id, "claim", supports_private_v2=True).json()["data"]
    auth = {"lease_token": claim["lease_token"], "agent_run_id": claim["agent_run_id"]}
    assert post(client, task_id, "industry-gate", lease_token=auth["lease_token"],
                industry_relevance="uncertain", reason="Weak lead").status_code == 200
    submit = post(client, task_id, "tools/username_scan/submit", **auth,
                  operation="username_scan", target="jane.example", idempotency_key="test-scan",
                  free_search={"queries": ["jane.example hair"], "outcome": "insufficient"})
    assert submit.status_code == 200, submit.text
    queued = submit.json()["data"]
    assert queued["status"] == "queued"
    research_tools_worker.process_once(settings, sessionmaker(bind=engine, autoflush=False))
    call = {"call_id": queued["call_id"]}
    status = post(client, task_id, "tools/username_scan/status", **auth, **call).json()["data"]
    assert status["result"]["candidates"][0]["fact_type"] == "social_profile_candidate"
    bind = post(client, task_id, "tools/username_scan/bind", **auth, **call, candidate_ids=[1])
    assert bind.status_code == 200, bind.text
    result = result_from(claim, bind.json()["data"])
    result.update(schema_version=PRIVATE_RESEARCH_RESULT,
                  report_markdown="候选主页 https://www.instagram.com/jane.example",
                  missing_information=["需要独立证据核实账号归属"])
    completed = post(client, task_id, "complete", **auth, result_json=result)
    assert completed.status_code == 200, completed.text
