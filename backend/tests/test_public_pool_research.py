"""Public-pool research, evidence, and knowledge-security contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Query

from app.agent_runtime.models import AgentEvent, AgentRun
from app.auth.models import ArkUser
from app.customer.models import (
    CustomerAccount,
    CustomerAssignment,
    CustomerContact,
    CustomerContactPoint,
    CustomerContactRelationship,
    CustomerFact,
    CustomerProfileVersion,
    CustomerResearchTask,
    CustomerSourceRecord,
    PublicPoolBatch,
)
from app.customer import outreach_service
from app.customer.access_service import CustomerAccess
from app.core.database import get_db
from app.knowledge import service as knowledge_service
from app.knowledge.models import KnowledgeLibrary
from app.sales_automation import (
    agent_router,
    enrichment_service,
    public_pool_service,
    router as sales_router,
    service,
)
from app.sales_automation.schemas import (
    AgentFailure,
    CustomerResearchResult,
    PublicPoolResearchSubmit,
    ResearchFactInput,
)
from app.sales_automation.dependencies import require_sales_agent


def _seed_user(db, user_id: int = 1) -> ArkUser:
    user = ArkUser(
        id=user_id,
        username=f"research-{user_id}",
        password_hash="test-only",
        real_name=f"Researcher {user_id}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _account(db, code: str = "CUS-RESEARCH") -> CustomerAccount:
    row = CustomerAccount(
        customer_code=code,
        display_name=code,
        canonical_company_name="Research Hair LLC",
        entity_type="registered_company",
        identity_status="verified",
        relationship_stage="discovered",
        relationship_stage_changed_at=datetime(2026, 8, 30, 8, 0),
        relationship_stage_reason="created",
        record_status="active",
        identity_confidence=1,
        profile_completeness=20,
        profile_input_seq=0,
    )
    db.add(row)
    db.flush()
    return row


def _task(
    db,
    *,
    policy: str = "research-v1",
    customer_code: str = "CUS-RESEARCH",
) -> CustomerResearchTask:
    if db.get(ArkUser, 1) is None:
        _seed_user(db)
    account = _account(db, customer_code)
    task, created = public_pool_service.ensure_research_task(
        db,
        customer_id=account.id,
        task_type="public_pool",
        source_ref_type="public_pool_batch",
        source_ref_id="1",
        research_policy_version=policy,
        input_snapshot={"schema_version": "research_input_v1", "customer_id": account.id},
        selection_reason=[{"reason": "unassigned_public_pool", "tier": "T3"}],
        tier="T3",
        created_by=1,
    )
    assert created
    db.commit()
    return task


def _governed_run(db, task: CustomerResearchTask, *, run_id: int | None = None) -> AgentRun:
    input_hash = public_pool_service.research_input_hash(task)
    row = AgentRun(
        id=run_id or 50_000 + task.id,
        session_id=60_000 + task.id,
        profile_id=70_000 + task.id,
        owner_user_id=1,
        idempotency_key=f"research-run-{task.id}-{run_id or task.id}",
        trigger_type="research_task",
        source_runtime="native",
        mode="scheduled",
        business_ref_type="research_task",
        business_ref_id=str(task.id),
        input_json={
            "research_task_id": task.id,
            "customer_id": task.customer_id,
            "input_hash": input_hash,
        },
        context_snapshot={"customer_id": task.customer_id, "input_hash": input_hash},
        status="running",
    )
    db.add(row)
    db.flush()
    return row


def _research_fact(db, task: CustomerResearchTask, run: AgentRun, *, suffix: str = "one"):
    _sources, facts = enrichment_service.append_research_facts(db, task.id, [{
        "fact_key": "business.industry",
        "value_type": "string",
        "value": "hair business",
        "fact_layer": "source",
        "confidence": "0.9000",
        "source_system": "public_web",
        "source_entity_type": "company_page",
        "external_record_id": f"research-evidence-{suffix}",
        "source_url": f"https://{suffix}.example/about",
        "observed_at": datetime(2026, 8, 30, 9, 0),
    }], agent_run_id=run.id)
    return facts[0]


def _record_fact_tool_output(
    db,
    task: CustomerResearchTask,
    run: AgentRun,
    fact: CustomerFact,
    *,
    call_id: str = "research-tool-1",
) -> None:
    input_hash = public_pool_service.research_input_hash(task)
    db.add_all([
        AgentEvent(
            run_id=run.id,
            session_id=run.session_id,
            sequence_no=1,
            event_id=f"{call_id}-requested",
            event_type="tool.requested",
            schema_version=1,
            actor_type="tool",
            visibility="user",
            payload_json={"call_id": call_id, "tool_name": "get_customer_facts"},
            source_event_ids=[],
            payload_sha256="1" * 64,
        ),
        AgentEvent(
            run_id=run.id,
            session_id=run.session_id,
            sequence_no=2,
            event_id=f"{call_id}-succeeded",
            event_type="tool.succeeded",
            schema_version=1,
            actor_type="tool",
            visibility="user",
            payload_json={
                "call_id": call_id,
                "output": {"evidence_refs": [{
                    "customer_id": task.customer_id,
                    "evidence_ref": f"fact:{fact.id}",
                    "evidence_content_hash": fact.fact_fingerprint,
                    "input_hash": input_hash,
                }]},
            },
            source_event_ids=[],
            payload_sha256="2" * 64,
        ),
    ])
    db.flush()


def _research_result(task: CustomerResearchTask, fact: CustomerFact) -> dict:
    return {
        "schema_version": "customer_research_v1",
        "input_hash": public_pool_service.research_input_hash(task),
        "claims": [{
            "claim_id": "claim_01",
            "section": "business_quality",
            "statement": "公开业务证据显示该客户经营发制品业务",
            "citation_ids": ["citation_01"],
        }],
        "citations": [{
            "citation_id": "citation_01",
            "claim_id": "claim_01",
            "tool_call_id": "research-tool-1",
            "evidence_ref": f"fact:{fact.id}",
            "evidence_content_hash": fact.fact_fingerprint,
        }],
        "knowledge_references": [],
    }


def test_public_pool_batch_is_idempotent_for_same_frozen_input(db):
    _seed_user(db)
    account = _account(db)
    payload = {
        "batch_date": date(2026, 8, 30),
        "policy_version": "pool-v1",
        "quotas_json": {
            "schema_version": "public_pool_quotas_v1",
            "tiers": {"T1": 0, "T2": 0, "T3": 1},
            "team_scope": "all",
            "total_limit": 1,
        },
        "profile_conditions": public_pool_service.default_profile_conditions(),
    }

    first = public_pool_service.generate_batch(db, payload, actor_id=1)
    replay = public_pool_service.generate_batch(db, payload, actor_id=1)

    assert replay.id == first.id
    assert db.query(PublicPoolBatch).count() == 1
    assert first.selection_snapshot["selected_customer_ids"] == [account.id]
    assert len(first.selection_snapshot["research_task_ids"]) == 1


def test_public_pool_batch_executes_only_the_frozen_customer_watermark(db):
    _seed_user(db)
    frozen = _account(db, "CUS-FROZEN")
    payload = {
        "batch_date": date(2026, 8, 30),
        "policy_version": "pool-watermark-v1",
        "quotas_json": {
            "schema_version": "public_pool_quotas_v1",
            "tiers": {"T1": 0, "T2": 0, "T3": 2},
            "team_scope": "all",
            "total_limit": 2,
        },
        "profile_conditions": public_pool_service.default_profile_conditions(),
    }
    batch, created = public_pool_service.prepare_batch(db, payload, actor_id=1)
    assert created
    late = _account(db, "CUS-AFTER-WATERMARK")
    db.commit()

    completed = public_pool_service.execute_batch(db, batch.id)

    assert completed.selection_snapshot["input_watermark"] == frozen.id
    assert completed.selection_snapshot["selected_customer_ids"] == [frozen.id]
    assert late.id not in completed.selection_snapshot["selected_customer_ids"]


def test_research_task_lease_fences_other_agents_and_gate_precedes_completion(db):
    task = _task(db)
    running, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")

    with pytest.raises(service.ConflictError, match="租约不属于"):
        public_pool_service.heartbeat_task(db, task.id, 1, "other-agent", token)
    with pytest.raises(service.ConflictError, match="门控未通过"):
        public_pool_service.complete_task_research(
            db,
            running.id,
            1,
            "research-agent",
            token,
            {},
            agent_run_id=1,
        )
    passed = public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", token, "core", "Relevant business verified",
    )
    assert passed.gate_status == "passed"
    run = _governed_run(db, task)
    fact = _research_fact(db, task, run)
    _record_fact_tool_output(db, task, run, fact)
    completed = public_pool_service.complete_task_research(
        db,
        task.id,
        1,
        "research-agent",
        token,
        _research_result(task, fact),
        agent_run_id=run.id,
    )
    assert completed.task_status == "completed"
    assert completed.result_review_status == "pending"
    assert completed.research_summary == "公开业务证据显示该客户经营发制品业务"
    round_trip = CustomerResearchResult.model_validate(completed.result_json)
    assert round_trip.evidence_fact_ids == [fact.id]


def test_revision_requested_requeues_same_task_with_new_fencing_generation(db):
    task = _task(db)
    running, first_token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", first_token, "core", "Relevant business verified",
    )
    run = _governed_run(db, task)
    fact = _research_fact(db, task, run, suffix="revision")
    _record_fact_tool_output(db, task, run, fact)
    first_result = _research_result(task, fact)
    public_pool_service.complete_task_research(
        db,
        task.id,
        1,
        "research-agent",
        first_token,
        first_result,
        agent_run_id=run.id,
    )
    revision = public_pool_service.review_research_result(
        db, task.id, "revision_requested", reviewer_id=1,
    )
    reused, created = public_pool_service.ensure_research_task(
        db,
        customer_id=task.customer_id,
        task_type="public_pool",
        source_ref_type="public_pool_batch",
        source_ref_id="later-batch",
        research_policy_version="research-v1",
        input_snapshot={"schema_version": "research_input_v1", "customer_id": task.customer_id},
        selection_reason=[{"reason": "later-batch"}],
        tier="T3",
        created_by=1,
    )
    assert reused.id == revision.id
    assert created is False
    claimable, _total = public_pool_service.list_claimable_tasks(db, 1, 20)
    assert [row.id for row in claimable] == [task.id]

    rerun, second_token = public_pool_service.claim_task(db, task.id, 1, "research-agent")

    assert rerun.id == revision.id == running.id
    assert rerun.lease_generation == 2
    assert second_token != first_token
    assert rerun.result_review_status == "pending"
    with pytest.raises(service.ConflictError, match="input_hash|Run"):
        public_pool_service.complete_task_research(
            db,
            task.id,
            1,
            "research-agent",
            second_token,
            first_result,
            agent_run_id=run.id,
        )
    with pytest.raises(service.ConflictError, match="租约"):
        public_pool_service.heartbeat_task(
            db, task.id, 1, "research-agent", first_token,
        )


def test_gate_stopped_task_cannot_enter_or_pass_qualification(db):
    task = _task(db)
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", token, "irrelevant", "Consumer-only account",
    )

    assert public_pool_service.list_pending_qualification(db) == []
    with pytest.raises(service.ConflictError, match="质量审核|研究成果"):
        public_pool_service.submit_qualification_review(
            db,
            customer_id=task.customer_id,
            review_source="public_pool_research",
            source_ref_id=str(task.id),
            decision="approved",
            reason_code="qualified",
            scope_type="global",
            scope_ref_id=None,
            policy_version="research-v1",
            review_snapshot={},
            decision_request_key="stopped-cannot-qualify",
            reviewed_by=1,
            expected_current_review_id=None,
        )


def test_research_task_lease_uses_beijing_business_clock(db, monkeypatch):
    task = _task(db)
    now = datetime(2026, 8, 30, 15, 0)
    monkeypatch.setattr(public_pool_service, "beijing_now", lambda: now)

    running, _token = public_pool_service.claim_task(db, task.id, 1, "research-agent")

    assert running.started_at == now
    assert running.lease_expires_at == now + timedelta(
        minutes=public_pool_service.LEASE_MINUTES,
    )


def test_research_fact_ingestion_keeps_registered_source_classification(db):
    task = _task(db)
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", token, "core", "Relevant business verified",
    )
    sources, facts = enrichment_service.append_research_facts(db, task.id, [{
        "fact_key": "business.industry",
        "value_type": "string",
        "value": "hair salon",
        "fact_layer": "source",
        "confidence": "0.9000",
        "source_system": "public_web",
        "source_entity_type": "company_page",
        "source_account_key": "global",
        "external_record_id": "example-about-v1",
        "source_url": "https://example.com/about",
        "source_payload": {"industry": "hair salon"},
        "observed_at": datetime(2026, 8, 30, 9, 0),
    }])

    assert len(sources) == len(facts) == 1
    assert sources[0].data_classification == "public_business"
    assert facts[0].data_classification == "public_business"
    assert facts[0].customer_id == task.customer_id
    assert db.query(CustomerSourceRecord).count() == 1
    assert db.query(CustomerFact).count() == 1


def test_research_completion_rejects_cross_customer_evidence_and_cannot_downgrade(db):
    task_a = _task(db, policy="research-a-v1", customer_code="CUS-RESEARCH-A")
    task_b = _task(db, policy="research-b-v1", customer_code="CUS-RESEARCH-B")
    running_b, _token_b = public_pool_service.claim_task(db, task_b.id, 1, "research-b")
    run_b = _governed_run(db, task_b)
    _sources_b, facts_b = enrichment_service.append_research_facts(db, running_b.id, [{
        "fact_key": "business.industry",
        "value_type": "string",
        "value": "unrelated customer fact",
        "fact_layer": "source",
        "confidence": "0.9000",
        "source_system": "public_web",
        "source_entity_type": "company_page",
        "external_record_id": "other-customer-fact",
        "source_url": "https://other.example/about",
        "observed_at": datetime(2026, 8, 30, 9, 0),
    }], agent_run_id=run_b.id)
    running_a, token_a = public_pool_service.claim_task(db, task_a.id, 1, "research-a")
    run_a = _governed_run(db, task_a)
    public_pool_service.submit_industry_gate(
        db, task_a.id, 1, "research-a", token_a, "core", "Relevant business verified",
    )

    with pytest.raises(service.ConflictError, match="证据事实.*客户"):
        public_pool_service.complete_task_research(
            db,
            task_a.id,
            1,
            "research-a",
            token_a,
            _research_result(task_a, facts_b[0]),
            agent_run_id=run_a.id,
            data_classification="public_business",
            visibility_scope="all_authorized",
        )

    _sources_a, facts_a = enrichment_service.append_research_facts(db, running_a.id, [{
        "fact_key": "business.industry",
        "value_type": "string",
        "value": "restricted strategy",
        "fact_layer": "source",
        "confidence": "0.9000",
        "source_system": "public_web",
        "source_entity_type": "company_page",
        "external_record_id": "same-customer-fact",
        "source_url": "https://same.example/about",
        "observed_at": datetime(2026, 8, 30, 9, 0),
    }], agent_run_id=run_a.id)
    facts_a[0].data_classification = "restricted_internal"
    facts_a[0].visibility_scope = "management"
    _record_fact_tool_output(db, task_a, run_a, facts_a[0])
    db.flush()
    completed = public_pool_service.complete_task_research(
        db,
        task_a.id,
        1,
        "research-a",
        token_a,
        _research_result(task_a, facts_a[0]),
        agent_run_id=run_a.id,
        data_classification="public_business",
        visibility_scope="all_authorized",
    )

    assert completed.data_classification == "restricted_internal"
    assert completed.visibility_scope == "management"


def test_same_run_fact_must_be_in_successful_tool_evidence_refs(db):
    task = _task(db, policy="research-tool-proof-v1", customer_code="CUS-TOOL-PROOF")
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", token, "core", "Relevant business verified",
    )
    run = _governed_run(db, task)
    fact = _research_fact(db, task, run, suffix="tool-proof")
    _record_fact_tool_output(db, task, run, fact)
    succeeded = db.query(AgentEvent).filter(
        AgentEvent.run_id == run.id,
        AgentEvent.event_type == "tool.succeeded",
    ).one()
    succeeded.payload_json = {
        "call_id": "research-tool-1", "output": {"evidence_refs": []},
    }
    db.flush()

    with pytest.raises(service.ConflictError, match="实际返回"):
        public_pool_service.complete_task_research(
            db,
            task.id,
            1,
            "research-agent",
            token,
            _research_result(task, fact),
            agent_run_id=run.id,
        )


def test_research_completion_requires_structured_claims_current_run_and_fresh_evidence(db):
    task = _task(db, policy="research-contract-v1", customer_code="CUS-CONTRACT")
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", token, "core", "Relevant business verified",
    )
    run = _governed_run(db, task)
    fact = _research_fact(db, task, run, suffix="contract")
    _record_fact_tool_output(db, task, run, fact)

    with pytest.raises(service.ConflictError, match="customer_research_v1"):
        public_pool_service.complete_task_research(
            db,
            task.id,
            1,
            "research-agent",
            token,
            {"identity": {"status": "verified"}, "risks": ["arbitrary"]},
            agent_run_id=run.id,
        )

    stale = _research_result(task, fact)
    stale["input_hash"] = "0" * 64
    with pytest.raises(service.ConflictError, match="input_hash"):
        public_pool_service.complete_task_research(
            db, task.id, 1, "research-agent", token, stale, agent_run_id=run.id,
        )

    fact.expires_at = datetime(2026, 8, 29, 9, 0)
    with pytest.raises(service.ConflictError, match="过期"):
        public_pool_service.complete_task_research(
            db,
            task.id,
            1,
            "research-agent",
            token,
            _research_result(task, fact),
            agent_run_id=run.id,
        )


def test_research_submit_schema_rejects_free_text_result_and_private_failure_message():
    with pytest.raises(ValidationError):
        PublicPoolResearchSubmit.model_validate({
            "agent_id": "research-agent",
            "lease_token": "x" * 32,
            "agent_run_id": 1,
            "result_json": {"risks": ["unsupported"]},
        })
    with pytest.raises(ValidationError):
        AgentFailure.model_validate({
            "agent_id": "research-agent",
            "lease_token": "x" * 32,
            "error_code": "provider_unavailable",
            "error_message": "restricted customer content",
        })


def test_agent_failure_stores_only_safe_code_and_generic_message(db):
    task = _task(db, policy="failure-v1", customer_code="CUS-FAILURE")
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")

    failed = public_pool_service.fail_task(
        db,
        task.id,
        error_code="provider_unavailable",
        actor_id=1,
        agent_id="research-agent",
        lease_token=token,
    )

    assert failed.error_code == "provider_unavailable"
    assert failed.error_message == "外部服务暂时不可用，请稍后重试"
    envelope = sales_router._research_task(failed)
    assert envelope["error_message"] == "外部服务暂时不可用，请稍后重试"
    assert "restricted" not in str(envelope)

    failed.error_code = "legacy_agent_error"
    failed.error_message = "restricted customer content"
    legacy_envelope = sales_router._research_task(failed)
    assert legacy_envelope["error_message"] == "任务执行失败，请联系管理员查看安全日志"
    assert "restricted customer content" not in str(legacy_envelope)


def test_human_research_detail_redacts_restricted_content_without_management(db):
    task = _task(db)
    task.task_status = "completed"
    task.gate_status = "passed"
    task.result_review_status = "pending"
    task.result_schema_version = "customer_research_v1"
    task.result_json = {"secret": "management-only"}
    task.research_summary = "management-only"
    task.evidence_fact_ids = [999]
    task.data_classification = "restricted_internal"
    task.visibility_scope = "management"
    db.commit()

    ordinary = sales_router.get_research_task(
        task.id,
        db,
        {"sub": "1", "roles": [], "permissions": ["sales_automation:read"]},
    )["data"]
    manager = sales_router.get_research_task(
        task.id,
        db,
        {"sub": "1", "roles": [], "permissions": ["sales_automation:admin"]},
    )["data"]

    assert ordinary["content_redacted"] is True
    assert "result_json" not in ordinary
    assert "research_summary" not in ordinary
    assert "evidence_fact_ids" not in ordinary
    assert manager["content_redacted"] is False
    assert manager["result_json"] == {"secret": "management-only"}


def test_qualification_review_after_is_beijing_naive_and_must_be_future(db, monkeypatch):
    task = _task(db)
    now = datetime(2026, 8, 30, 8, 0)
    monkeypatch.setattr(public_pool_service, "beijing_now", lambda: now)

    review = public_pool_service.submit_qualification_review(
        db,
        customer_id=task.customer_id,
        review_source="manual",
        source_ref_id=None,
        decision="deferred",
        reason_code="not_now",
        scope_type="global",
        scope_ref_id=None,
        policy_version="manual-v1",
        review_snapshot={},
        decision_request_key="future-review",
        reviewed_by=1,
        expected_current_review_id=None,
        review_after=datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc),
    )
    assert review.review_after == datetime(2026, 8, 30, 9, 0)

    with pytest.raises(service.SalesAutomationError, match="未来"):
        public_pool_service.submit_qualification_review(
            db,
            customer_id=task.customer_id,
            review_source="manual",
            source_ref_id=None,
            decision="deferred",
            reason_code="not_now",
            scope_type="target_profile",
            scope_ref_id="1",
            policy_version="manual-v1",
            review_snapshot={},
            decision_request_key="past-review",
            reviewed_by=1,
            expected_current_review_id=None,
            review_after=datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
        )


def test_research_fact_schema_rejects_unregistered_or_untraceable_inference():
    with pytest.raises(ValueError, match="source事实"):
        ResearchFactInput.model_validate({
            "fact_key": "business.industry",
            "value_type": "string",
            "value": "salon",
            "fact_layer": "source",
            "confidence": 0.9,
            "source_system": "agent",
            "source_entity_type": "research_report",
            "external_record_id": "report-1",
            "observed_at": "2026-08-30T09:00:00+08:00",
        })
    with pytest.raises(ValueError, match="支撑事实"):
        ResearchFactInput.model_validate({
            "fact_key": "behavior.inferred.buying_stage",
            "value_type": "string",
            "value": "evaluation",
            "fact_layer": "inferred",
            "confidence": 0.7,
            "source_system": "agent",
            "source_entity_type": "research_report",
            "external_record_id": "report-2",
            "observed_at": "2026-08-30T09:00:00+08:00",
        })


def test_agent_knowledge_search_and_read_delegate_to_published_acl_service(db, monkeypatch):
    identity = {"sub": "1", "permissions": ["sales_automation:invoke", "knowledge:read"]}
    calls = []

    def fake_search(session, agent, query, *, limit, audit_action):
        calls.append((session, agent, query, limit, audit_action))
        return [{"document_id": 7, "revision_id": 9, "version_no": 3}]

    def fake_get(session, agent, document_id, *, audit_action):
        calls.append((session, agent, document_id, audit_action))
        return {"document_id": document_id, "revision_id": 9, "version_no": 3}

    monkeypatch.setattr(knowledge_service, "search_published", fake_search)
    monkeypatch.setattr(knowledge_service, "get_published_document", fake_get)

    searched = agent_router.search_agent_knowledge("policy", 5, db, identity)
    read = agent_router.get_agent_knowledge_document(7, db, identity)

    assert searched["data"][0]["document_id"] == 7
    assert read["data"]["revision_id"] == 9
    assert calls[0][-1] == "sales_agent_knowledge_search"
    assert calls[1][-1] == "sales_agent_knowledge_read"


def test_research_knowledge_references_are_exact_version_and_acl_checked(db, monkeypatch):
    identity = {"sub": "1", "permissions": ["sales_automation:invoke", "knowledge:read"]}
    library = KnowledgeLibrary(
        id=77,
        name="Company knowledge",
        category="company",
        status="active",
        created_by=1,
    )
    db.add(library)
    db.flush()
    monkeypatch.setattr(
        knowledge_service,
        "get_published_document",
        lambda *_args, **_kwargs: {
            "document_id": 7,
            "revision_id": 9,
            "version_no": 3,
            "library_id": library.id,
        },
    )
    agent_router._validate_knowledge_references(db, identity, [{
        "document_id": 7, "revision_id": 9, "version_no": 3,
    }])
    with pytest.raises(HTTPException) as stale:
        agent_router._validate_knowledge_references(db, identity, [{
            "document_id": 7, "revision_id": 8, "version_no": 2,
    }])
    assert stale.value.status_code == 409

    library.category = "personal"
    db.flush()
    with pytest.raises(HTTPException) as private_library:
        agent_router._validate_knowledge_references(db, identity, [{
            "document_id": 7, "revision_id": 9, "version_no": 3,
        }])
    assert private_library.value.status_code == 409

    monkeypatch.setattr(
        knowledge_service,
        "get_published_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            knowledge_service.ForbiddenError("not authorized")
        ),
    )
    with pytest.raises(HTTPException) as forbidden:
        agent_router._validate_knowledge_references(db, identity, [{
            "document_id": 7, "revision_id": 9, "version_no": 3,
        }])
    assert forbidden.value.status_code == 403


def test_agent_research_context_is_customer_scoped_and_contains_no_credentials(db):
    task = _task(db)
    context = agent_router._research_context(db, task.id)

    assert context["research_task_id"] == task.id
    assert context["customer_id"] == task.customer_id
    assert context["customer"]["customer_id"] == task.customer_id
    assert context["research_rules"]["forbidden"] == [
        "猜测邮箱", "个人社会关系调查", "无来源事实", "跨客户读取", "直接触达",
    ]
    serialized = str(context).lower()
    assert "password" not in serialized
    assert "lease_token" not in serialized
    assert "api_key" not in serialized


def test_agent_appends_task_scoped_research_facts_with_canonical_evidence(db):
    task = _task(db)
    claimed, lease_token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    run = _governed_run(db, claimed)
    db.commit()
    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_sales_agent] = lambda: {
        "sub": "1",
        "permissions": ["sales_automation:invoke"],
    }

    with TestClient(app) as client:
        response = client.post(
            f"/api/sales-automation/agent/research-tasks/{task.id}/facts",
            json={
                "agent_id": "research-agent",
                "lease_token": lease_token,
                "agent_run_id": run.id,
                "facts": [{
                    "fact_key": "business.industry",
                    "value_type": "string",
                    "value": "hair extensions",
                    "fact_layer": "source",
                    "confidence": "0.9000",
                    "source_system": "public_web",
                    "source_entity_type": "company_page",
                    "external_record_id": "official-about",
                    "source_url": "https://example.test/about",
                    "observed_at": "2026-08-30T09:00:00+08:00",
                }],
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["research_task_id"] == task.id
    assert data["customer_id"] == task.customer_id
    assert data["input_hash"] == public_pool_service.research_input_hash(task)
    assert len(data["evidence_refs"]) == 1
    evidence = data["evidence_refs"][0]
    assert evidence["customer_id"] == task.customer_id
    assert evidence["evidence_ref"].startswith("fact:")
    assert len(evidence["evidence_content_hash"]) == 64
    assert evidence["input_hash"] == data["input_hash"]


def test_outreach_context_binds_current_customer_profile_contact_and_evidence(db):
    task = _task(db)
    claimed, _lease_token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    run = _governed_run(db, claimed)
    fact = _research_fact(db, claimed, run, suffix="outreach")
    profile = CustomerProfileVersion(
        customer_id=task.customer_id,
        version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1",
        input_seq=0,
        profile_json={},
        section_hashes={},
        section_data_as_of={},
        evidence_fact_ids=[fact.id],
        change_summary={"changes": []},
        compiler_version="test-v1",
        profile_fingerprint="f" * 64,
        compiled_at=datetime(2026, 8, 30, 10, 0),
    )
    contact = CustomerContact(
        display_name="Buyer",
        canonical_name="Buyer",
        normalized_name="buyer",
        identity_status="verified",
        confidence=1,
        confidence_method_version="test-v1",
        confidence_components_json={},
        record_status="active",
    )
    db.add_all([profile, contact])
    db.flush()
    account = db.get(CustomerAccount, task.customer_id)
    account.current_profile_version_id = profile.id
    db.add(CustomerContactRelationship(
        customer_id=account.id,
        contact_id=contact.id,
        relationship_type="buyer",
        buying_role="buyer",
        verification_status="verified",
        confidence=1,
        confidence_method_version="test-v1",
        confidence_components_json={},
        relationship_fingerprint="r" * 64,
    ))
    db.add(CustomerContactPoint(
        contact_id=contact.id,
        point_type="email",
        raw_value="Buyer@Example.test",
        normalized_value="buyer@example.test",
        email_domain_type="corporate",
        verification_status="valid",
        contactability_status="allowed",
        contactability_reason_code="verified",
        is_primary=True,
        data_classification="public_business",
        source_record_id=fact.source_record_id,
        point_fingerprint="p" * 64,
        first_seen_at=datetime(2026, 8, 30, 9, 0),
        last_seen_at=datetime(2026, 8, 30, 9, 0),
        verified_at=datetime(2026, 8, 30, 9, 0),
    ))
    db.flush()

    access = CustomerAccess(
        customer_id=account.id,
        actor_user_id=1,
        can_manage=False,
        max_data_classification="personal_contact",
        max_visibility_scope="customer_team",
        run_id=None,
    )
    context = outreach_service.get_outreach_context(db, access)

    assert context["customer_id"] == account.id
    assert context["current_profile_version_id"] == profile.id
    assert context["suppressed"] is False
    assert context["contacts"][0]["email"] == "buyer@example.test"
    assert context["evidence"] == [{
        "fact_id": fact.id,
        "fact_fingerprint": fact.fact_fingerprint,
        "source_record_id": fact.source_record_id,
        "source_url": "https://outreach.example/about",
    }]


def test_outreach_context_route_requires_live_customer_access(db):
    task = _task(db)
    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api/sales-automation")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_sales_agent] = lambda: {
        "sub": "1",
        "roles": [],
        "permissions": ["sales_automation:invoke", "customer:read"],
    }

    with TestClient(app) as client:
        denied = client.get(
            f"/api/sales-automation/agent/customers/{task.customer_id}/outreach-context",
        )
        db.add(CustomerAssignment(
            customer_id=task.customer_id,
            user_id=1,
            assignment_role="primary",
            assignment_status="active",
            assignment_source="manual",
            effective_from=datetime(2026, 8, 30, 8, 0),
        ))
        db.commit()
        allowed = client.get(
            f"/api/sales-automation/agent/customers/{task.customer_id}/outreach-context",
        )
        app.dependency_overrides[require_sales_agent] = lambda: {
            "sub": "1",
            "roles": [],
            "permissions": ["sales_automation:invoke"],
        }
        agent_only = client.get(
            f"/api/sales-automation/agent/customers/{task.customer_id}/outreach-context",
        )

    assert denied.status_code == 404
    assert denied.json()["detail"] == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"
    assert allowed.status_code == 200
    assert allowed.json()["data"]["customer_id"] == task.customer_id
    assert agent_only.status_code == 404
    assert agent_only.json()["detail"] == "CUSTOMER_NOT_FOUND_OR_FORBIDDEN"


def test_outreach_context_filters_management_evidence(db):
    task = _task(db)
    claimed, _lease_token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    run = _governed_run(db, claimed)
    visible = _research_fact(db, claimed, run, suffix="visible-outreach")
    hidden = _research_fact(db, claimed, run, suffix="hidden-outreach")
    hidden.data_classification = "restricted_internal"
    hidden.visibility_scope = "management"
    hidden_source = db.get(CustomerSourceRecord, hidden.source_record_id)
    hidden_source.data_classification = "restricted_internal"
    hidden_source.visibility_scope = "management"
    profile = CustomerProfileVersion(
        customer_id=task.customer_id,
        version_no=1,
        profile_schema_version="customer_profile_v1",
        canonicalization_version="jcs_v1",
        input_seq=0,
        profile_json={},
        section_hashes={},
        section_data_as_of={},
        evidence_fact_ids=[visible.id, hidden.id],
        change_summary={"changes": []},
        compiler_version="test-v1",
        profile_fingerprint="e" * 64,
        compiled_at=datetime(2026, 8, 30, 10, 0),
    )
    db.add(profile)
    db.flush()
    db.get(CustomerAccount, task.customer_id).current_profile_version_id = profile.id
    access = CustomerAccess(
        customer_id=task.customer_id,
        actor_user_id=1,
        can_manage=False,
        max_data_classification="restricted_internal",
        max_visibility_scope="customer_team",
        run_id=None,
    )

    context = outreach_service.get_outreach_context(db, access)

    assert [row["fact_id"] for row in context["evidence"]] == [visible.id]
