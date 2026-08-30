"""Unified acquisition workflow contract tests.

These tests intentionally exercise the customer-id workflow directly.  The
retired lead/company/subject tables are not part of the fixture or assertions.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date, datetime
import json

import pytest
from sqlalchemy.orm import Query

from app.agent_runtime.models import AgentEvent, AgentRun
from app.auth.models import ArkUser
from app.customer.models import (
    CustomerAccount,
    CustomerAnnotation,
    CustomerAssignment,
    CustomerExternalIdentity,
    CustomerQualificationReview,
    CustomerResearchTask,
    CustomerSourceRecord,
    PublicPoolBatch,
    SearchJob,
    SearchResult,
    SearchResultSource,
)
from app.sales_automation import enrichment_service, public_pool_service, service
from app.sales_automation import router as sales_router
from app.mcp import agent_tools
from app.sales_automation.models import AcquisitionProfile


POLICY = {
    "schema_version": "target_profile_policy_v1",
    "thresholds": {
        "research_threshold": 70,
        "qualification_threshold": 80,
        "tier_1_min_score": 90,
        "tier_2_min_score": 75,
        "tier_3_min_score": 60,
    },
    "weights": {"provider_score": 1},
    "research_rules": {
        "minimum_independent_sources": 2,
        "evidence_freshness_days": 90,
        "auto_research_enabled": True,
        "gate_required": True,
    },
    "claim_rules": {
        "cooldown_days": 30,
        "requires_qualification": True,
        "per_user_quota": 20,
        "per_team_quota": 100,
        "block_identity_conflict": True,
        "block_do_not_contact": True,
    },
}


def _seed_user(db, user_id: int = 1) -> ArkUser:
    row = ArkUser(
        id=user_id,
        username=f"acquisition-{user_id}",
        password_hash="test",
        real_name=f"Reviewer {user_id}",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _profile_payload() -> dict:
    return {
        "company_name": "Ark Hair",
        "products": ["hair extensions"],
        "advantages": ["quality"],
        "target_countries": ["US"],
        "target_industries": ["salon"],
        "target_roles": ["buyer"],
        "exclusions": [],
        "default_language": "en",
        "policy_version": "acquisition-v1",
        "policy_json": POLICY,
    }


def _candidate(*, external_record_id: str, source_url: str, score: int) -> dict:
    return {
        "source_system": "public_web",
        "source_account_key": "global",
        "source_entity_type": "company_page",
        "external_record_id": external_record_id,
        "external_context_id": "example.com",
        "source_provider": "google" if "google" in source_url else "linkedin",
        "source_url": source_url,
        "captured_at": datetime(2026, 8, 30, 9, 0),
        "company_name": "Example Hair LLC",
        "website": "https://example.com",
        "country": "US",
        "score": score,
        "score_reasons": [{"dimension": "fit", "score": score, "reason": "public evidence"}],
    }


def _system_candidate(
    *, source_system: str, external_record_id: str, company_id: str, score: int = 85,
) -> dict:
    return {
        "source_system": source_system,
        "source_account_key": "ark-okki" if source_system == "okki" else "us-registry",
        "source_entity_type": "customer",
        "external_record_id": external_record_id,
        "external_context_id": company_id,
        "source_provider": source_system,
        "captured_at": datetime(2026, 8, 30, 9, 0),
        "company_name": "Structured Hair LLC",
        "score": score,
        "score_reasons": [{"dimension": "fit", "score": score}],
    }


def _running_search_job(db) -> tuple[SearchJob, str]:
    _seed_user(db)
    service.upsert_profile(db, _profile_payload(), actor_id=1)
    job = service.create_search_job(
        db,
        {
            "name": "US salons",
            "target_count": 20,
            "adapter": "agent",
            "criteria_json": {"countries": ["US"]},
            "idempotency_key": "1" * 64,
        },
        actor_id=1,
    )
    job, token = service.claim_search_job(db, job.id, 1, "search-agent")
    return job, token


def _account(db, code: str, *, identity_status: str = "verified") -> CustomerAccount:
    row = CustomerAccount(
        customer_code=code,
        display_name=code,
        canonical_company_name=None,
        entity_type="unknown",
        identity_status=identity_status,
        relationship_stage="discovered",
        relationship_stage_changed_at=datetime(2026, 8, 30, 8, 0),
        relationship_stage_reason="created",
        record_status="active",
        identity_confidence=1 if identity_status == "verified" else 0,
        profile_completeness=0,
        profile_input_seq=0,
    )
    db.add(row)
    db.flush()
    return row


def _search_research_task(db) -> CustomerResearchTask:
    job, token = _running_search_job(db)
    service.ingest_candidates(
        db,
        job.id,
        [_candidate(external_record_id="page-1", source_url="https://google.example/result", score=90)],
        request_key="batch-1",
        actor_id=1,
        agent_id="search-agent",
        lease_token=token,
    )
    return db.query(CustomerResearchTask).one()


def _completed_research_material(db, task: CustomerResearchTask) -> tuple[AgentRun, dict]:
    input_hash = public_pool_service.research_input_hash(task)
    run = AgentRun(
        id=80_000 + task.id,
        session_id=81_000 + task.id,
        profile_id=82_000 + task.id,
        owner_user_id=1,
        idempotency_key=f"acquisition-research-{task.id}",
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
    db.add(run)
    db.flush()
    _sources, facts = enrichment_service.append_research_facts(db, task.id, [{
        "fact_key": "business.industry",
        "value_type": "string",
        "value": "hair business",
        "fact_layer": "source",
        "confidence": "0.9000",
        "source_system": "public_web",
        "source_entity_type": "company_page",
        "external_record_id": f"acquisition-research-{task.id}",
        "source_url": "https://research.example/about",
        "observed_at": datetime(2026, 8, 30, 9, 0),
    }], agent_run_id=run.id)
    fact = facts[0]
    call_id = "research-tool-1"
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
                "evidence_refs": [{
                    "customer_id": task.customer_id,
                    "evidence_ref": f"fact:{fact.id}",
                    "evidence_content_hash": fact.fact_fingerprint,
                    "input_hash": input_hash,
                }],
            },
            source_event_ids=[],
            payload_sha256="2" * 64,
        ),
    ])
    result = {
        "schema_version": "customer_research_v1",
        "input_hash": input_hash,
        "claims": [{
            "claim_id": "claim_01",
            "section": "business_quality",
            "statement": "公开业务证据显示该客户经营发制品业务",
            "citation_ids": ["citation_01"],
        }],
        "citations": [{
            "citation_id": "citation_01",
            "claim_id": "claim_01",
            "tool_call_id": call_id,
            "evidence_ref": f"fact:{fact.id}",
            "evidence_content_hash": fact.fact_fingerprint,
        }],
        "knowledge_references": [],
    }
    return run, result


def test_workflow_models_are_registered_once_and_legacy_models_are_absent():
    from app.sales_automation import models

    assert models.SearchJob is SearchJob
    assert models.SearchResult is SearchResult
    assert models.SearchResultSource is SearchResultSource
    assert models.PublicPoolBatch is PublicPoolBatch
    for retired in (
        "LeadCompany",
        "LeadContact",
        "ResearchSubject",
        "PublicPoolTask",
        "DealAssessment",
        "ResearchRun",
        "ResearchFact",
    ):
        assert not hasattr(models, retired)


def test_mcp_search_context_uses_customer_id_source_first_contract(db, monkeypatch):
    job, _token = _running_search_job(db)

    class CaptureMcp:
        def __init__(self):
            self.tools = {}

        def tool(self, *, name, annotations):
            del annotations

            def register(function):
                self.tools[name] = function
                return function

            return register

    capture = CaptureMcp()
    agent_tools.register_agent_tools(capture)

    @contextmanager
    def test_session():
        yield db

    monkeypatch.setattr(agent_tools, "_session", test_session)
    monkeypatch.setattr(
        agent_tools,
        "_require_agent_identity",
        lambda *_args, **_kwargs: {
            "sub": "1",
            "permissions": ["sales_automation:invoke"],
            "_agent_run": {"run_id": 999999},
        },
    )
    payload = json.loads(asyncio.run(capture.tools["get_search_job_context"](
        agent_tools.SearchJobInput(job_id=job.id),
        object(),
    )))

    assert payload["ok"] is True
    assert payload["data"]["job"]["criteria_json"] == job.criteria_json
    assert "criteria" not in payload["data"]["job"]
    assert payload["data"]["output_contract"] == {
        "identifier": "customer_id",
        "source_record_first": True,
        "company_name_nullable": True,
    }


def test_duplicate_sources_share_one_customer_result_and_one_strategy_task(db):
    job, token = _running_search_job(db)
    summary = service.ingest_candidates(
        db,
        job.id,
        [
            _candidate(external_record_id="google-page", source_url="https://google.example/result", score=82),
            _candidate(external_record_id="linkedin-page", source_url="https://linkedin.example/company", score=91),
        ],
        request_key="batch-1",
        actor_id=1,
        agent_id="search-agent",
        lease_token=token,
    )

    assert summary["received"] == 2
    assert summary["unique_customers"] == 1
    assert db.query(CustomerAccount).count() == 1
    assert db.query(SearchResult).count() == 1
    assert db.query(SearchResultSource).count() == 2
    assert db.query(CustomerSourceRecord).count() == 2
    assert db.query(CustomerResearchTask).count() == 1
    result = db.query(SearchResult).one()
    assert float(result.best_score) == 91
    assert result.best_rank == 1
    assert {item["source_provider"] for item in result.aggregated_score_reasons["sources"]} == {
        "google",
        "linkedin",
    }


def test_ingestion_request_replay_is_idempotent_and_changed_payload_conflicts(db):
    job, token = _running_search_job(db)
    candidate = _candidate(external_record_id="page-1", source_url="https://google.example/result", score=90)
    first = service.ingest_candidates(
        db, job.id, [candidate], "batch-1", 1, "search-agent", token,
    )
    replay = service.ingest_candidates(
        db, job.id, [candidate], "batch-1", 1, "search-agent", token,
    )
    assert replay == first
    assert db.query(SearchResultSource).count() == 1

    changed = dict(candidate, score=89)
    with pytest.raises(service.ConflictError, match="request_key"):
        service.ingest_candidates(
            db, job.id, [changed], "batch-1", 1, "search-agent", token,
        )


def test_identity_resolution_failure_quarantines_source_without_creating_candidate(db):
    job, token = _running_search_job(db)
    invalid = _candidate(
        external_record_id="invalid-private-host",
        source_url="https://google.example/result",
        score=90,
    )
    invalid["website"] = "http://127.0.0.1/private"

    summary = service.ingest_candidates(
        db, job.id, [invalid], "batch-invalid", 1, "search-agent", token,
    )

    assert summary["quarantined_sources"] == 1
    source = db.query(CustomerSourceRecord).one()
    assert source.processing_status == "quarantined"
    assert source.processing_error_code == "invalid_external_identity"
    assert source.customer_id is None
    assert db.query(CustomerAccount).count() == 0
    assert db.query(SearchResult).count() == 0


@pytest.mark.parametrize(
    ("source_system", "identifier_type", "classification"),
    [
        ("okki", "company_id", "internal_business"),
        ("official_registry", "business_id", "public_business"),
    ],
)
def test_structured_sources_use_verified_business_identity_and_registry_classification(
    db, source_system, identifier_type, classification,
):
    job, token = _running_search_job(db)
    first = _system_candidate(
        source_system=source_system,
        external_record_id="version-1",
        company_id="COMPANY-100",
    )
    service.ingest_candidates(
        db, job.id, [first], "batch-1", 1, "search-agent", token,
    )
    second = dict(first, external_record_id="version-2", score=90)
    service.ingest_candidates(
        db, job.id, [second], "batch-2", 1, "search-agent", token,
    )

    assert db.query(CustomerAccount).count() == 1
    assert db.query(SearchResult).count() == 1
    assert db.query(SearchResultSource).count() == 2
    identity = db.query(CustomerExternalIdentity).one()
    assert identity.identifier_type == identifier_type
    assert identity.normalized_value == "COMPANY-100"
    assert identity.verification_status == "verified"
    assert {row.data_classification for row in db.query(CustomerSourceRecord)} == {
        classification
    }


def test_same_strategy_reuses_active_research_task_across_ingestion_batches(db):
    job, token = _running_search_job(db)
    first = _candidate(
        external_record_id="page-1",
        source_url="https://google.example/result",
        score=90,
    )
    service.ingest_candidates(db, job.id, [first], "batch-1", 1, "search-agent", token)
    second = dict(
        first,
        external_record_id="page-2",
        source_provider="linkedin",
        source_url="https://linkedin.example/company",
        score=92,
    )
    service.ingest_candidates(db, job.id, [second], "batch-2", 1, "search-agent", token)

    assert db.query(CustomerResearchTask).count() == 1
    assert db.query(SearchResultSource).count() == 2


def test_gate_stop_preserves_reason_without_positive_research_output(db):
    task = _search_research_task(db)
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    stopped = public_pool_service.submit_industry_gate(
        db,
        task.id,
        actor_id=1,
        agent_id="research-agent",
        lease_token=token,
        industry_relevance="irrelevant",
        reason="Consumer-only profile with no business evidence",
    )
    assert stopped.task_status == "skipped"
    assert stopped.gate_status == "stopped"
    assert stopped.result_review_status == "not_required"
    assert stopped.result_json == {
        "schema_version": "research_gate_v1",
        "industry_relevance": "irrelevant",
        "stop_reason": "Consumer-only profile with no business evidence",
    }


def test_research_quality_acceptance_creates_derived_pending_queue_not_qualification(db):
    task = _search_research_task(db)
    task, token = public_pool_service.claim_task(db, task.id, 1, "research-agent")
    public_pool_service.submit_industry_gate(
        db, task.id, 1, "research-agent", token, "core", "Business activity verified",
    )
    run, result = _completed_research_material(db, task)
    public_pool_service.complete_task_research(
        db,
        task.id,
        actor_id=1,
        agent_id="research-agent",
        lease_token=token,
        result_json=result,
        agent_run_id=run.id,
    )
    reviewed = public_pool_service.review_research_result(db, task.id, "accepted", reviewer_id=1)

    assert reviewed.result_review_status == "accepted"
    assert db.query(CustomerQualificationReview).count() == 0
    pending = public_pool_service.list_pending_qualification(db)
    assert [row.id for row in pending] == [task.id]


def test_search_failure_uses_safe_error_code_and_never_persists_agent_text(db):
    job, token = _running_search_job(db)

    failed = service.fail_search_job(
        db,
        job.id,
        error_code="provider_unavailable",
        actor_id=1,
        agent_id="search-agent",
        lease_token=token,
    )

    assert failed.error_code == "provider_unavailable"
    assert failed.error_message == "外部服务暂时不可用，请稍后重试"
    failed.error_code = "legacy_agent_error"
    failed.error_message = "restricted customer content"
    assert sales_router._job(failed)["error_message"] == "任务执行失败，请联系管理员查看安全日志"
    assert "restricted customer content" not in str(sales_router._job(failed))


def test_search_job_unique_race_rolls_back_outer_transaction_before_reading_winner(db, monkeypatch):
    _seed_user(db)
    service.upsert_profile(db, _profile_payload(), actor_id=1)
    payload = {
        "name": "RR winner",
        "target_count": 10,
        "adapter": "agent",
        "criteria_json": {"countries": ["US"]},
        "idempotency_key": "9" * 64,
    }
    winner = service.create_search_job(db, payload, actor_id=1)
    original_one_or_none = Query.one_or_none
    hidden = False

    def hide_first_search_job(query):
        nonlocal hidden
        entity = query.column_descriptions[0].get("entity") if query.column_descriptions else None
        if entity is SearchJob and not hidden:
            hidden = True
            return None
        return original_one_or_none(query)

    rollback_calls = 0
    original_rollback = db.rollback

    def record_rollback():
        nonlocal rollback_calls
        rollback_calls += 1
        return original_rollback()

    monkeypatch.setattr(Query, "one_or_none", hide_first_search_job)
    monkeypatch.setattr(db, "rollback", record_rollback)

    replay = service.create_search_job(db, payload, actor_id=1)

    assert replay.id == winner.id
    assert rollback_calls == 1


def test_search_job_unique_race_without_visible_winner_requests_new_transaction(db, monkeypatch):
    _seed_user(db)
    service.upsert_profile(db, _profile_payload(), actor_id=1)
    payload = {
        "name": "RR retry",
        "target_count": 10,
        "adapter": "agent",
        "criteria_json": {"countries": ["US"]},
        "idempotency_key": "8" * 64,
    }
    service.create_search_job(db, payload, actor_id=1)
    original_one_or_none = Query.one_or_none
    hidden_reads = 0

    def hide_search_job_reads(query):
        nonlocal hidden_reads
        entity = query.column_descriptions[0].get("entity") if query.column_descriptions else None
        if entity is SearchJob and hidden_reads < 2:
            hidden_reads += 1
            return None
        return original_one_or_none(query)

    monkeypatch.setattr(Query, "one_or_none", hide_search_job_reads)

    with pytest.raises(service.ConflictError, match="RETRY_NEW_TRANSACTION"):
        service.create_search_job(db, payload, actor_id=1)


def test_public_pool_batch_unique_race_rolls_back_before_reading_winner(db, monkeypatch):
    _seed_user(db)
    _account(db, "CUS-RR-BATCH")
    payload = {
        "batch_date": date(2026, 8, 30),
        "policy_version": "pool-rr-v1",
        "quotas_json": {
            "schema_version": "public_pool_quotas_v1",
            "tiers": {"T1": 0, "T2": 0, "T3": 1},
            "team_scope": "all",
            "total_limit": 1,
        },
        "profile_conditions": public_pool_service.default_profile_conditions(),
    }
    winner, created = public_pool_service.prepare_batch(db, payload, actor_id=1)
    assert created
    original_one_or_none = Query.one_or_none
    hidden = False

    def hide_first_batch(query):
        nonlocal hidden
        entity = query.column_descriptions[0].get("entity") if query.column_descriptions else None
        if entity is PublicPoolBatch and not hidden:
            hidden = True
            return None
        return original_one_or_none(query)

    rollback_calls = 0
    original_rollback = db.rollback

    def record_rollback():
        nonlocal rollback_calls
        rollback_calls += 1
        return original_rollback()

    monkeypatch.setattr(Query, "one_or_none", hide_first_batch)
    monkeypatch.setattr(db, "rollback", record_rollback)

    replay, was_created = public_pool_service.prepare_batch(db, payload, actor_id=1)

    assert replay.id == winner.id
    assert was_created is False
    assert rollback_calls == 1


def test_qualification_is_current_scope_cas_and_cross_customer_source_is_rejected(db):
    task = _search_research_task(db)
    first = public_pool_service.submit_qualification_review(
        db,
        customer_id=task.customer_id,
        review_source="search_result",
        source_ref_id=task.source_ref_id,
        decision="approved",
        reason_code="qualified",
        scope_type="target_profile",
        scope_ref_id="1",
        policy_version="acquisition-v1",
        review_snapshot={"score": 90},
        decision_request_key="decision-1",
        reviewed_by=1,
        expected_current_review_id=None,
    )
    job = db.get(SearchJob, db.get(SearchResult, int(task.source_ref_id)).job_id)
    assert job.qualified_count == 1
    with pytest.raises(service.ConflictError, match="已变化"):
        public_pool_service.submit_qualification_review(
            db,
            customer_id=task.customer_id,
            review_source="search_result",
            source_ref_id=task.source_ref_id,
            decision="deferred",
            reason_code="not_now",
            scope_type="target_profile",
            scope_ref_id="1",
            policy_version="acquisition-v1",
            review_snapshot={"score": 90},
            decision_request_key="decision-2",
            reviewed_by=1,
            expected_current_review_id=None,
        )
    second = public_pool_service.submit_qualification_review(
        db,
        customer_id=task.customer_id,
        review_source="search_result",
        source_ref_id=task.source_ref_id,
        decision="deferred",
        reason_code="not_now",
        scope_type="target_profile",
        scope_ref_id="1",
        policy_version="acquisition-v1",
        review_snapshot={"score": 90},
        decision_request_key="decision-3",
        reviewed_by=1,
        expected_current_review_id=first.id,
    )
    assert second.review_version == 2
    assert second.supersedes_review_id == first.id
    assert not db.get(CustomerQualificationReview, first.id).is_current
    assert job.qualified_count == 0

    other = CustomerAccount(
        customer_code="CUS-OTHER",
        display_name="Other",
        canonical_company_name=None,
        entity_type="unknown",
        identity_status="provisional",
        relationship_stage="discovered",
        relationship_stage_changed_at=datetime(2026, 8, 30, 8, 0),
        relationship_stage_reason="created",
        record_status="active",
        identity_confidence=0,
        profile_completeness=0,
        profile_input_seq=0,
    )
    db.add(other)
    db.flush()
    with pytest.raises(service.ConflictError, match="来源对象"):
        public_pool_service.submit_qualification_review(
            db,
            customer_id=other.id,
            review_source="public_pool_research",
            source_ref_id=str(task.id),
            decision="approved",
            reason_code="qualified",
            scope_type="global",
            scope_ref_id=None,
            policy_version="v1",
            review_snapshot={},
            decision_request_key="cross-customer",
            reviewed_by=1,
            expected_current_review_id=None,
        )
    with pytest.raises(service.ConflictError, match="来源对象不存在"):
        public_pool_service.submit_qualification_review(
            db,
            customer_id=other.id,
            review_source="search_result",
            source_ref_id="999999",
            decision="deferred",
            reason_code="not_now",
            scope_type="global",
            scope_ref_id=None,
            policy_version="v1",
            review_snapshot={},
            decision_request_key="missing-source",
            reviewed_by=1,
            expected_current_review_id=None,
        )


def test_dnc_is_central_deny_gate_and_blocks_approval(db):
    task = _search_research_task(db)
    public_pool_service.submit_qualification_review(
        db,
        customer_id=task.customer_id,
        review_source="manual",
        source_ref_id=None,
        decision="rejected",
        reason_code="do_not_contact",
        scope_type="global",
        scope_ref_id=None,
        policy_version="manual-v1",
        review_snapshot={"reason": "customer request"},
        decision_request_key="dnc-1",
        reviewed_by=1,
        expected_current_review_id=None,
    )
    assert db.query(CustomerAnnotation).filter_by(annotation_type="do_not_contact", status="active").count() == 1
    assert public_pool_service.is_development_denied(db, task.customer_id, "target_profile", "1")

    with pytest.raises(service.ConflictError, match="禁止开发"):
        public_pool_service.submit_qualification_review(
            db,
            customer_id=task.customer_id,
            review_source="search_result",
            source_ref_id=task.source_ref_id,
            decision="approved",
            reason_code="qualified",
            scope_type="target_profile",
            scope_ref_id="1",
            policy_version="acquisition-v1",
            review_snapshot={},
            decision_request_key="approve-after-dnc",
            reviewed_by=1,
            expected_current_review_id=None,
        )


def test_target_poor_fit_does_not_pollute_global_or_other_target(db):
    task = _search_research_task(db)
    poor_fit = public_pool_service.submit_qualification_review(
        db,
        customer_id=task.customer_id,
        review_source="search_result",
        source_ref_id=task.source_ref_id,
        decision="rejected",
        reason_code="poor_fit",
        scope_type="target_profile",
        scope_ref_id="1",
        policy_version="acquisition-v1",
        review_snapshot={"score": 30},
        decision_request_key="poor-fit-target-1",
        reviewed_by=1,
        expected_current_review_id=None,
    )
    assert public_pool_service.current_qualification(db, task.customer_id, "target_profile", "1").id == poor_fit.id
    assert public_pool_service.current_qualification(db, task.customer_id, "target_profile", "2") is None
    assert public_pool_service.current_qualification(db, task.customer_id, "global", None) is None
    assert not public_pool_service.is_development_denied(db, task.customer_id, "target_profile", "2")


def test_public_pool_batch_applies_frozen_filters_and_records_selected_customer_ids(db):
    _seed_user(db)
    eligible = _account(db, "CUS-ELIGIBLE")
    _account(db, "CUS-PROVISIONAL", identity_status="provisional")
    _account(db, "CUS-DISPUTED", identity_status="disputed")
    assigned = _account(db, "CUS-ASSIGNED")
    denied = _account(db, "CUS-DNC")
    db.add(CustomerAssignment(
        customer_id=assigned.id,
        user_id=1,
        assignment_role="primary",
        assignment_status="active",
        assignment_source="manual",
        effective_from=datetime(2026, 8, 30, 8, 0),
    ))
    db.flush()
    public_pool_service.submit_qualification_review(
        db,
        customer_id=denied.id,
        review_source="manual",
        source_ref_id=None,
        decision="rejected",
        reason_code="do_not_contact",
        scope_type="global",
        scope_ref_id=None,
        policy_version="manual-v1",
        review_snapshot={},
        decision_request_key="pool-dnc",
        reviewed_by=1,
        expected_current_review_id=None,
    )

    batch = public_pool_service.generate_batch(
        db,
        {
            "batch_date": date(2026, 8, 30),
            "policy_version": "pool-v1",
            "quotas_json": {
                "schema_version": "public_pool_quotas_v1",
                "tiers": {"T1": 10, "T2": 10, "T3": 10},
                "team_scope": "all",
                "total_limit": 30,
            },
            "profile_conditions": public_pool_service.default_profile_conditions(),
        },
        actor_id=1,
    )

    task = db.query(CustomerResearchTask).filter_by(task_type="public_pool").one()
    assert task.customer_id == eligible.id
    assert batch.result_counts["selected"] == {"T1": 0, "T2": 0, "T3": 1}
    assert batch.selection_snapshot["selected_customer_ids"] == [eligible.id]
    assert batch.selection_snapshot["research_task_ids"] == [task.id]
    assert batch.selection_snapshot["filter_counts"] == {
        "identity_status": 2,
        "assigned": 1,
        "dnc": 1,
        "quota": 0,
    }


def test_retired_http_endpoints_are_deleted():
    from app.sales_automation import agent_router, router

    paths = {route.path for route in [*router.router.routes, *agent_router.router.routes]}
    assert not any("/leads" in path or "/companies" in path or "/subjects" in path for path in paths)
    assert "/agent/search-jobs/{job_id}/candidates" in paths
    assert "/agent/research-tasks/{task_id}/complete" in paths
