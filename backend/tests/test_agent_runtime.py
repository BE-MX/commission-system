"""Governed Agent Runtime contracts: ownership, leases, events and artifacts."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_runtime import artifact_service, maintenance, models, router, seed, service, worker_service
from app.agent_runtime import orchestration
from app.agent_runtime.dependencies import require_agent_worker, verify_worker_token
from app.agent_runtime.errors import ConflictError, ForbiddenError, LeaseError, NotFoundError
from app.agent_runtime.schemas import ArtifactInput, WorkerEventInput
from app.agent_runtime.token_service import decode_run_token
from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.ai import agent_service
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.core.database import Base, get_db
from app.insight import customer_radar_service
from app.insight.models import CustomerAction, CustomerOpportunity, CustomerProfile
from app.mcp import auth as mcp_auth
from app.mcp.models import MCPToken
from app.mcp.public_web_tools import _validate_public_url


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        ArkUser.__table__,
        ArkRole.__table__,
        ArkPermission.__table__,
        ArkUserRole.__table__,
        ArkRolePermission.__table__,
        AiProvider.__table__,
        AiPreset.__table__,
        AiCallLog.__table__,
        MCPToken.__table__,
        models.AgentProfile.__table__,
        models.AgentSession.__table__,
        models.AgentRun.__table__,
        models.AgentEvent.__table__,
        models.AgentArtifact.__table__,
        CustomerProfile.__table__,
        CustomerOpportunity.__table__,
        CustomerAction.__table__,
    ])
    session = sessionmaker(bind=engine, autoflush=False)()
    session.add_all([
        ArkUser(id=7, username="owner", password_hash="x", real_name="Owner"),
        ArkUser(id=8, username="other", password_hash="x", real_name="Other"),
    ])
    session.commit()
    role = ArkRole(id=1, name="agent_test", label="Agent Test")
    permission_codes = [
        "agent_runtime:invoke", "customer_radar:read", "order_intelligence:read",
        "sales_automation:read",
    ]
    permissions = [
        ArkPermission(id=index + 1, code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
        for index, code in enumerate(permission_codes)
    ]
    session.add(role)
    session.add_all(permissions)
    session.flush()
    session.add(ArkUserRole(user_id=7, role_id=role.id))
    session.add_all([ArkRolePermission(role_id=role.id, permission_id=item.id) for item in permissions])
    session.commit()
    session.expunge_all()
    seed.seed_default_profiles(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def runtime_settings(monkeypatch):
    settings = SimpleNamespace(
        AGENT_RUNTIME_ENABLED=True,
        AGENT_RUNTIME_DSH_ENABLED=True,
        AGENT_RUNTIME_COPILOT_ENABLED=True,
        AGENT_RUNTIME_REPURCHASE_ENABLED=True,
        AGENT_RUNTIME_SALES_SHADOW_ENABLED=True,
        AGENT_RUNTIME_REPURCHASE_BATCH_SIZE=20,
        AGENT_RUNTIME_WEB_SEARCH_ENABLED=True,
        AGENT_RUNTIME_BRAVE_SEARCH_API_KEY="test-brave-key",
        AGENT_RUNTIME_SHADOW_SAMPLE_RATE=1.0,
        AGENT_RUNTIME_WORKER_LEASE_SECONDS=180,
        AGENT_RUNTIME_MAX_ACTIVE_PER_USER=2,
        AGENT_RUNTIME_MAX_STEPS_PER_RUN=12,
        AGENT_RUNTIME_RUN_TIMEOUT_SECONDS=300,
        AGENT_RUNTIME_RUN_TOKEN_SECRET="test-run-secret-at-least-32-characters",
        AGENT_RUNTIME_DAILY_TOKEN_BUDGET=200_000,
        JWT_SECRET_KEY="test-jwt-secret-at-least-32-characters",
        JWT_ALGORITHM="HS256",
        AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON="",
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_service, "get_settings", lambda: settings)
    from app.agent_runtime import dependencies, token_service
    monkeypatch.setattr(token_service, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(router, "get_settings", lambda: settings)
    monkeypatch.setattr(agent_service, "get_settings", lambda: settings)
    monkeypatch.setattr(orchestration, "get_settings", lambda: settings)
    return settings


def _session(db, user_id=7, profile_key="customer_order_copilot"):
    return service.create_session(db, {
        "profile_key": profile_key,
        "title": "Acme 经营分析",
        "context_type": "customer",
        "context_id": "ACME-1",
    }, user_id=user_id)


def _run(db, session, key="run-key-0001"):
    return service.create_run(
        db,
        session.id,
        {
            "idempotency_key": key,
            "input": {"question": "这个客户为什么需要跟进？"},
            "trigger_type": "user",
        },
        user_id=session.owner_user_id,
        permissions=["agent_runtime:write", "order_intelligence:read"],
        roles=["sales"],
    )


def _claim(db, worker_id="dsh-worker-01"):
    return worker_service.claim_run(db, worker_id=worker_id, runtimes=["dsh"])


def _start(db, run_id, claim):
    event = WorkerEventInput(
        sequence_no=claim["next_sequence_no"],
        event_id="dsh-start-1",
        event_type="run.started",
        actor_type="runtime",
        payload={"runtime": "dsh"},
    )
    return worker_service.append_worker_events(
        db, run_id,
        worker_id="dsh-worker-01",
        lease_token=claim["lease_token"],
        events=[event],
    )


def test_profile_seed_is_immutable_and_idempotent(db):
    assert db.query(models.AgentProfile).count() == 3
    assert seed.seed_default_profiles(db) == 0
    profile = service.get_active_profile(db, "customer_order_copilot")
    assert profile.version == 1
    assert "get_customer_profile" in profile.tool_allowlist
    assert len(profile.prompt_hash) == 64


def test_create_run_is_idempotent_and_owner_scoped(db):
    session = _session(db)
    first = _run(db, session)
    second = _run(db, session)
    assert first.id == second.id
    assert first.status == "queued"
    events = service.list_events(
        db, first.id, user_id=7, can_read_all=False, include_admin=True,
    )
    assert [item.event_type for item in events] == ["run.created"]
    with pytest.raises(NotFoundError):
        service.get_run(db, first.id, user_id=8, can_read_all=False)
    assert service.get_run(db, first.id, user_id=8, can_read_all=True).id == first.id


def test_one_active_run_per_session_and_queued_cancel(db):
    session = _session(db)
    run = _run(db, session)
    with pytest.raises(ConflictError, match="同一会话"):
        service.create_run(
            db, session.id,
            {"idempotency_key": "run-key-0002", "input": {}},
            user_id=7, permissions=[], roles=[],
        )
    cancelled = service.cancel_run(db, run.id, user_id=7, can_read_all=False)
    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is not None


def test_worker_lease_event_replay_and_complete_artifact(db):
    run = _run(db, _session(db))
    claim = _claim(db)
    assert claim["run_id"] == run.id
    assert claim["next_sequence_no"] == 3
    row, next_seq = _start(db, run.id, claim)
    assert row.status == "running"
    assert next_seq == 4

    replay = WorkerEventInput(
        sequence_no=3,
        event_id="dsh-start-1",
        event_type="run.started",
        actor_type="runtime",
        payload={"runtime": "dsh"},
    )
    _, replay_next = worker_service.append_worker_events(
        db, run.id,
        worker_id="dsh-worker-01",
        lease_token=claim["lease_token"],
        events=[replay],
    )
    assert replay_next == 4
    assert db.query(models.AgentEvent).filter(models.AgentEvent.run_id == run.id).count() == 3

    artifact = ArtifactInput(
        artifact_type="copilot_answer",
        title="Acme 跟进建议",
        content={
            "summary": "客户进入复购窗口",
            "key_findings": ["距离历史周期还剩 7 天"],
            "risks": [],
            "recommended_actions": ["确认下一批采购计划"],
            "evidence": [{"tool_call_id": "tool-1"}],
            "open_questions": [],
        },
        evidence=[{"tool_call_id": "tool-1", "source": "get_customer_repurchase_analysis"}],
    )
    completed, artifacts = worker_service.complete_run(
        db, run.id,
        worker_id="dsh-worker-01",
        lease_token=claim["lease_token"],
        runtime_run_id="dsh-run-01",
        artifacts=[artifact],
        steps_used=3,
        prompt_tokens=100,
        completion_tokens=40,
        cost_usd=Decimal("0.0123"),
    )
    assert completed.status == "completed"
    assert artifacts[0].validation_status == "valid"
    assert [event.event_type for event in db.query(models.AgentEvent).filter(
        models.AgentEvent.run_id == run.id,
    ).order_by(models.AgentEvent.sequence_no)] == [
        "run.created", "run.claimed", "run.started",
        "artifact.created", "artifact.validated", "run.completed",
    ]


def test_event_id_cannot_be_reused_with_different_payload(db):
    run = _run(db, _session(db))
    claim = _claim(db)
    _start(db, run.id, claim)
    changed = WorkerEventInput(
        sequence_no=3,
        event_id="dsh-start-1",
        event_type="run.started",
        actor_type="runtime",
        payload={"runtime": "different"},
    )
    with pytest.raises(ConflictError, match="event_id"):
        worker_service.append_worker_events(
            db, run.id,
            worker_id="dsh-worker-01",
            lease_token=claim["lease_token"],
            events=[changed],
        )
    db.rollback()


def test_raw_event_retention_redacts_cipher_but_keeps_audit_event(db):
    run = _run(db, _session(db))
    events = db.query(models.AgentEvent).filter(
        models.AgentEvent.run_id == run.id,
    ).order_by(models.AgentEvent.id).all()
    events[0].raw_payload_cipher = "encrypted-old-payload"
    events[0].created_at = datetime(2026, 1, 1)
    db.commit()

    assert maintenance.redact_expired_raw_events(
        db, now=datetime(2026, 4, 2), retention_days=90,
    ) == 1
    db.refresh(events[0])
    assert events[0].raw_payload_cipher is None
    assert events[0].event_type == "run.created"
    assert events[0].payload_json["profile_key"] == "customer_order_copilot"


def test_expired_running_lease_becomes_ambiguous_and_rejects_stale_worker(db):
    run = _run(db, _session(db))
    claim = _claim(db)
    _start(db, run.id, claim)
    run.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(LeaseError, match="过期"):
        worker_service.heartbeat(
            db, run.id,
            worker_id="dsh-worker-01",
            lease_token=claim["lease_token"],
            runtime_run_id=None,
            steps_used=None,
        )
    db.rollback()
    assert worker_service.reconcile_expired_runs(db) == 1
    db.commit()
    assert db.get(models.AgentRun, run.id).status == "ambiguous"


def test_artifact_decision_is_idempotent_but_cannot_flip(db):
    run = _run(db, _session(db))
    claim = _claim(db)
    _start(db, run.id, claim)
    profile = db.get(models.AgentProfile, run.profile_id)
    artifact = artifact_service.create_artifact(
        db, run, profile,
        artifact_type="copilot_answer",
        schema_version=1,
        title=None,
        content={
            "summary": "结论", "key_findings": [], "risks": [],
            "recommended_actions": [], "evidence": [], "open_questions": [],
        },
        evidence=[{"source": "test"}],
    )
    db.commit()
    accepted = artifact_service.decide_artifact(
        db, artifact.id, user_id=7, decision="accepted", note="采用", can_read_all=False,
    )
    assert accepted.decision_status == "accepted"
    assert artifact_service.decide_artifact(
        db, artifact.id, user_id=7, decision="accepted", note="采用", can_read_all=False,
    ).decision_status == "accepted"
    with pytest.raises(ConflictError):
        artifact_service.decide_artifact(
            db, artifact.id, user_id=7, decision="rejected", note=None, can_read_all=False,
        )


def test_customer_radar_refresh_preserves_completed_action(db):
    profile = CustomerProfile(
        customer_name="Acme",
        customer_external_id="C-ACME",
        owner_user_id=7,
        owner_resolve_status="resolved",
        priority_score=50,
        first_seen_at=datetime.utcnow(),
        status="active",
    )
    db.add(profile)
    db.commit()
    first = customer_radar_service.generate_daily_actions(db, 7, date(2026, 8, 20))[0]
    first.action_status = "done"
    first.action_reason = "用户已经处理的原始理由"
    db.commit()
    refreshed = customer_radar_service.generate_daily_actions(db, 7, date(2026, 8, 20))[0]
    assert refreshed.id == first.id
    assert refreshed.action_status == "done"
    assert refreshed.action_reason == "用户已经处理的原始理由"
    assert db.query(CustomerAction).count() == 1


def test_user_router_permission_envelope(db, runtime_settings):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/agent-runtime")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["agent_runtime:read", "agent_runtime:write"],
    }
    client = TestClient(app)
    response = client.post("/api/agent-runtime/sessions", json={
        "profile_key": "customer_order_copilot",
        "title": "API 会话",
        "context_type": "customer",
        "context_id": "C-1",
    })
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert response.json()["data"]["owner_user_id"] == 7


def test_worker_token_is_instance_bound(runtime_settings):
    import hashlib
    token = "worker-secret-token-with-more-than-24-characters"
    runtime_settings.AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON = (
        '{"dsh-worker-01":["' + hashlib.sha256(token.encode()).hexdigest() + '"]}'
    )
    assert verify_worker_token("dsh-worker-01", token)
    assert not verify_worker_token("dsh-worker-02", token)
    assert not verify_worker_token("dsh-worker-01", "wrong-token-with-more-than-24-characters")


def _seed_agent_preset(db):
    provider = AiProvider(
        name="agent-test-provider",
        provider_type="direct",
        api_base="https://models.example/v1",
        api_type="openai",
        is_enabled=True,
        timeout_sec=30,
    )
    db.add(provider)
    db.flush()
    db.add(AiPreset(
        preset_name="agent_runtime_copilot",
        provider_id=provider.id,
        model="deepseek-chat",
        system_prompt="",
        parameters={"temperature": 0.1, "max_tokens": 3000},
        is_enabled=True,
    ))
    db.commit()


class _FakeModelResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        chunks = [
            {"id": "chat-1", "model": "deepseek-chat", "choices": [{
                "delta": {"tool_calls": [{"function": {
                    "name": "mcp__ark__search_knowledge", "arguments": "{}",
                }}]}, "finish_reason": None,
            }]},
            {"id": "chat-1", "model": "deepseek-chat", "choices": [{
                "delta": {"content": "有证据的结论"}, "finish_reason": "stop",
            }]},
            {"id": "chat-1", "choices": [], "usage": {
                "prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
            }},
        ]
        for chunk in chunks:
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}"
            yield ""
        yield "data: [DONE]"
        yield ""


class _FakeModelClient:
    last_body = None

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream(self, *_args, **_kwargs):
        type(self).last_body = _kwargs.get("json")
        return _FakeModelResponse()


def test_agent_model_gateway_preserves_tool_calls_and_accounts_usage(db, monkeypatch):
    _seed_agent_preset(db)
    run = _run(db, _session(db))
    claim = _claim(db)
    _start(db, run.id, claim)
    monkeypatch.setattr(agent_service.httpx, "Client", _FakeModelClient)

    claims = decode_run_token(claim["run_token"])
    stream, model = agent_service.prepare_agent_chat(
        db,
        claims=claims,
        messages=[{"role": "user", "content": "请查询知识"}],
        tools=[{"type": "function", "function": {
            "name": "mcp__ark__search_knowledge", "parameters": {"type": "object"},
        }}, {"type": "function", "function": {
            "name": "mcp__ark__record_shipment", "parameters": {"type": "object"},
        }}],
    )
    raw = b"".join(stream).decode("utf-8")
    assert model == "deepseek-chat"
    assert "mcp__ark__search_knowledge" in raw
    assert [item["function"]["name"] for item in _FakeModelClient.last_body["tools"]] == [
        "mcp__ark__search_knowledge"
    ]
    log = db.query(AiCallLog).one()
    assert log.status == "success"
    assert log.tokens_used == 17
    assert "请查询知识" not in log.prompt_snapshot
    refreshed = db.get(models.AgentRun, run.id)
    assert (refreshed.prompt_tokens, refreshed.completion_tokens) == (12, 5)


def test_agent_model_gateway_rejects_forced_tool_outside_profile(db):
    _seed_agent_preset(db)
    run = _run(db, _session(db))
    claim = _claim(db)
    _start(db, run.id, claim)
    claims = decode_run_token(claim["run_token"])
    with pytest.raises(ForbiddenError, match="record_shipment"):
        agent_service.prepare_agent_chat(
            db,
            claims=claims,
            messages=[{"role": "user", "content": "越权调用"}],
            tools=[{"type": "function", "function": {
                "name": "mcp__ark__record_shipment", "parameters": {"type": "object"},
            }}],
            tool_choice={"type": "function", "function": {"name": "mcp__ark__record_shipment"}},
        )


def test_mcp_run_token_is_bound_to_profile_tool_allowlist(db):
    run = _run(db, _session(db))
    claim = _claim(db)
    _start(db, run.id, claim)

    request = SimpleNamespace(headers={"authorization": f"Bearer {claim['run_token']}"})
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=request))
    identity = mcp_auth.require_identity(ctx, db, tool_name="search_knowledge")
    assert identity["sub"] == "7"
    assert identity["_agent_run"]["run_id"] == run.id
    with pytest.raises(mcp_auth.MCPAuthError, match="record_shipment"):
        mcp_auth.require_identity(ctx, db, tool_name="record_shipment")


def test_accepted_repurchase_artifact_projects_only_to_pending_action(db):
    profile = CustomerProfile(
        customer_name="Repeat Buyer",
        customer_external_id="C-REPEAT",
        owner_user_id=7,
        owner_resolve_status="resolved",
        priority_score=80,
        first_seen_at=datetime.utcnow(),
        status="active",
    )
    db.add(profile)
    db.flush()
    action = CustomerAction(
        profile_id=profile.id,
        owner_user_id=7,
        thread_group="reorder_window",
        thread_priority="重点",
        action_reason="规则理由",
        suggested_next_action="规则动作",
        suggested_message="rule draft",
        source_evidence={"source": "rule"},
        action_status="pending",
        action_date=date(2026, 8, 20),
        source_type="rule",
        source_fingerprint="rule-projection-test",
        evidence_status="valid",
    )
    db.add(action)
    db.commit()
    session = _session(db, profile_key="repurchase_risk_analyst")
    run = service.create_run(db, session.id, {
        "idempotency_key": "repurchase-projection-run",
        "input": {"customer_profile_id": profile.id},
        "trigger_type": "schedule",
        "business_ref_type": "customer_action",
        "business_ref_id": str(action.id),
    }, user_id=7, permissions=["agent_runtime:invoke"], roles=[])
    claim = _claim(db)
    _start(db, run.id, claim)
    artifact = ArtifactInput(
        artifact_type="repurchase_action_card",
        content={
            "action_reason": "DSH 有证据理由",
            "suggested_next_action": "确认库存和采购周期",
            "suggested_message": "Could we review your next replenishment window?",
            "evidence": [{"source": "get_customer_repurchase_analysis"}],
        },
        evidence=[{"source": "get_customer_repurchase_analysis"}],
    )
    _, artifacts = worker_service.complete_run(
        db, run.id,
        worker_id="dsh-worker-01", lease_token=claim["lease_token"],
        runtime_run_id="dsh-repurchase", artifacts=[artifact], steps_used=2,
        prompt_tokens=20, completion_tokens=10, cost_usd=Decimal("0"),
    )
    artifact_service.decide_artifact(
        db, artifacts[0].id, user_id=7, decision="accepted", note=None, can_read_all=False,
    )
    db.refresh(action)
    assert action.source_type == "dsh"
    assert action.source_run_id == run.id
    assert action.action_reason == "DSH 有证据理由"

    # A later replay/decision must never rewrite user-handled action state.
    action.action_status = "done"
    action.action_reason = "用户处理后的事实"
    db.commit()
    from app.agent_runtime.projection_service import project_accepted_artifact
    project_accepted_artifact(db, artifacts[0], run)
    db.commit()
    assert db.get(CustomerAction, action.id).action_reason == "用户处理后的事实"


def test_repurchase_scheduler_enqueues_once_from_rule_candidate(db):
    profile = CustomerProfile(
        customer_name="Scheduled Buyer", customer_external_id="C-SCHEDULED",
        owner_user_id=7, owner_resolve_status="resolved", priority_score=70,
        first_seen_at=datetime.utcnow(), status="active",
    )
    db.add(profile)
    db.flush()
    action = CustomerAction(
        profile_id=profile.id, owner_user_id=7, thread_group="reorder_window",
        thread_priority="重点", action_reason="进入规则复购窗口",
        suggested_next_action="确认需求", suggested_message="draft",
        source_evidence={"source": "rule"}, action_status="pending",
        action_date=date(2026, 8, 20), source_type="rule",
        source_fingerprint="rule-scheduled-test", evidence_status="valid",
    )
    db.add(action)
    db.commit()
    assert orchestration.enqueue_repurchase_runs(
        db, action_date=date(2026, 8, 20), limit=10,
    ) == 1
    run = db.query(models.AgentRun).filter(
        models.AgentRun.business_ref_type == "customer_action",
        models.AgentRun.business_ref_id == str(action.id),
    ).one()
    assert run.status == "queued"
    assert run.trigger_type == "schedule"
    assert orchestration.enqueue_repurchase_runs(
        db, action_date=date(2026, 8, 20), limit=10,
    ) == 0


def test_public_fetch_url_guard_rejects_private_dns(monkeypatch):
    monkeypatch.setattr("app.mcp.public_web_tools.socket.getaddrinfo", lambda *_args, **_kwargs: [
        (None, None, None, None, ("127.0.0.1", 443)),
    ])
    with pytest.raises(ValueError, match="非公开"):
        _validate_public_url("https://example.com/private")
