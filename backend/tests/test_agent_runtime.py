"""Governed Agent Runtime contracts: ownership, leases, events and artifacts."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_runtime import artifact_service, models, router, seed, service, worker_service
from app.agent_runtime.dependencies import require_agent_worker, verify_worker_token
from app.agent_runtime.errors import ConflictError, LeaseError, NotFoundError
from app.agent_runtime.schemas import ArtifactInput, WorkerEventInput
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import Base, get_db
from app.insight import customer_radar_service
from app.insight.models import CustomerAction, CustomerOpportunity, CustomerProfile


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        ArkUser.__table__,
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
        AGENT_RUNTIME_WORKER_LEASE_SECONDS=180,
        AGENT_RUNTIME_MAX_ACTIVE_PER_USER=2,
        AGENT_RUNTIME_MAX_STEPS_PER_RUN=12,
        AGENT_RUNTIME_RUN_TIMEOUT_SECONDS=300,
        AGENT_RUNTIME_RUN_TOKEN_SECRET="test-run-secret-at-least-32-characters",
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
