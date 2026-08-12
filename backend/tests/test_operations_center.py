from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils import create_access_token
from app.operations import router as operations_router_module


_DEFAULT_NEXT_RUN = object()


class _FakeJob:
    def __init__(self, job_id="staging_scan", next_run_time=_DEFAULT_NEXT_RUN):
        self.id = job_id
        self.name = job_id
        self.trigger = "interval[0:02:00]"
        self.next_run_time = (
            datetime(2026, 8, 12, tzinfo=timezone.utc)
            if next_run_time is _DEFAULT_NEXT_RUN else next_run_time
        )


class _FakeScheduler:
    def __init__(self):
        self.running = True
        self.timezone = timezone.utc
        self.job = _FakeJob()
        self.actions = []

    def get_jobs(self):
        return [self.job]

    def get_job(self, job_id):
        return self.job if job_id == self.job.id else None

    def modify_job(self, job_id, **kwargs):
        self.actions.append(("run", job_id, kwargs))

    def pause_job(self, job_id):
        self.actions.append(("pause", job_id, {}))

    def resume_job(self, job_id):
        self.actions.append(("resume", job_id, {}))


def test_scheduler_view_uses_chinese_catalog_and_runtime(monkeypatch):
    from app.operations import service

    scheduler = _FakeScheduler()
    monkeypatch.setattr(service, "get_active_scheduler", lambda: scheduler)
    monkeypatch.setattr(service, "get_job_runtime_snapshot", lambda: {
        "staging_scan": {
            "last_status": "failed",
            "last_error": "boom",
            "running_instances": 0,
        },
    })
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(
        SCHEDULER_ENABLED=True,
        SCHEDULER_TIMEZONE="Asia/Shanghai",
    ))

    view = service._scheduler_view()

    assert view.running is True
    assert view.registered_job_count == 1
    staging = next(item for item in view.jobs if item.id == "staging_scan")
    assert staging.name == "运单暂存区扫描"
    assert staging.domain == "物流跟踪"
    assert staging.last_status == "failed"
    assert staging.last_error == "boom"
    assert len(view.jobs) == view.expected_job_count


@pytest.mark.parametrize("action", ["run", "pause", "resume"])
def test_job_control_is_bounded_to_catalog(monkeypatch, action):
    from app.operations import service

    scheduler = _FakeScheduler()
    monkeypatch.setattr(service, "get_active_scheduler", lambda: scheduler)
    monkeypatch.setattr(service, "_create_control_audit", lambda **_kwargs: 1)
    monkeypatch.setattr(service, "_finish_control_audit", lambda *_args: None)
    monkeypatch.setattr(service, "_set_paused_policy", lambda *_args: None)
    monkeypatch.setattr(service, "_restore_paused_policy", lambda *_args: None)
    monkeypatch.setattr(
        service, "submit_job_now",
        lambda _scheduler, job_id: scheduler.actions.append(("run", job_id, {})),
    )

    result = service.control_job("staging_scan", action, "admin")

    assert result.accepted is True
    assert scheduler.actions[0][0] == action


def test_job_control_rejects_unknown_job(monkeypatch):
    from app.operations import service

    scheduler = _FakeScheduler()
    monkeypatch.setattr(service, "get_active_scheduler", lambda: scheduler)
    monkeypatch.setattr(service, "_create_control_audit", lambda **_kwargs: 1)
    monkeypatch.setattr(service, "_finish_control_audit", lambda *_args: None)

    with pytest.raises(ValueError, match="不存在"):
        service.control_job("not-allowed", "run", "admin")


def test_run_rejects_paused_job(monkeypatch):
    from app.operations import service

    scheduler = _FakeScheduler()
    scheduler.job = _FakeJob(next_run_time=None)
    monkeypatch.setattr(service, "get_active_scheduler", lambda: scheduler)
    monkeypatch.setattr(service, "_create_control_audit", lambda **_kwargs: 1)
    monkeypatch.setattr(service, "_finish_control_audit", lambda *_args: None)

    with pytest.raises(ValueError, match="已暂停"):
        service.control_job("staging_scan", "run", "admin")


def test_job_runtime_does_not_expose_exception_message():
    from apscheduler.events import EVENT_JOB_ERROR

    from app.schedulers import registry

    registry._job_runtime.pop("staging_scan", None)
    registry._record_job_event(SimpleNamespace(
        code=EVENT_JOB_ERROR,
        job_id="staging_scan",
        exception=RuntimeError("secret detail"),
    ))

    state = registry.get_job_runtime_snapshot()["staging_scan"]
    assert state["last_error"] == "任务执行失败（RuntimeError）"
    assert "secret" not in state["last_error"]


def test_job_runtime_missed_decrements_and_max_instances_is_visible():
    from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED, EVENT_JOB_SUBMITTED

    from app.schedulers import registry

    registry._job_runtime.pop("staging_scan", None)
    registry._record_job_event(SimpleNamespace(
        code=EVENT_JOB_SUBMITTED,
        job_id="staging_scan",
        scheduled_run_times=[1, 2],
    ))
    assert registry.get_job_runtime_snapshot()["staging_scan"]["running_instances"] == 2

    registry._record_job_event(SimpleNamespace(code=EVENT_JOB_MISSED, job_id="staging_scan"))
    assert registry.get_job_runtime_snapshot()["staging_scan"]["running_instances"] == 1

    registry._record_job_event(SimpleNamespace(code=EVENT_JOB_MAX_INSTANCES, job_id="staging_scan"))
    state = registry.get_job_runtime_snapshot()["staging_scan"]
    assert state["last_status"] == "skipped"


def test_submit_job_now_preserves_recurring_schedule():
    from app.schedulers import registry

    original_next_run = datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc)
    job = SimpleNamespace(
        id="staging_scan",
        executor="default",
        next_run_time=original_next_run,
        _jobstore_alias="default",
    )
    submitted = []
    events = []
    executor = SimpleNamespace(submit_job=lambda submitted_job, run_times: submitted.append(
        (submitted_job, run_times),
    ))
    scheduler = SimpleNamespace(
        timezone=timezone.utc,
        get_job=lambda _job_id: job,
        _lookup_executor=lambda _name: executor,
        _dispatch_event=events.append,
    )

    registry.submit_job_now(scheduler, "staging_scan")

    assert submitted[0][0] is job
    assert len(submitted[0][1]) == 1
    assert events[0].code == registry.EVENT_JOB_SUBMITTED
    assert job.next_run_time == original_next_run


def test_persisted_pause_policy_reapplied(monkeypatch):
    from app.schedulers import registry

    scheduler = _FakeScheduler()
    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def query(self, _model):
            return SimpleNamespace(filter=lambda *_args: SimpleNamespace(
                all=lambda: [SimpleNamespace(job_id="staging_scan")],
            ))

    fake_db = FakeDb()
    monkeypatch.setattr(registry, "SessionLocal", lambda: fake_db)

    registry._apply_persisted_job_policies(scheduler)

    assert scheduler.actions == [("pause", "staging_scan", {})]


def test_safe_endpoint_strips_credentials_and_query():
    from app.operations.service import _safe_endpoint

    assert _safe_endpoint("https://user:secret@example.com:8443/secret-path?token=secret") == (
        "https://example.com:8443"
    )


def test_safe_endpoint_rejects_invalid_port():
    from app.operations.service import _safe_endpoint

    assert _safe_endpoint("https://example.com:not-a-port/health") is None


@pytest.mark.asyncio
async def test_overview_marks_unmanaged_services_without_network(monkeypatch):
    from app.operations import service
    from app.operations.schemas import SchedulerView

    monkeypatch.setattr(service, "_service_catalog", lambda: [{
        "id": "openclaw-sales-agent",
        "name": "OpenClaw 销售 Agent",
        "category": "Agent 服务",
        "environment": "外部执行器",
        "owner": "销售运营",
        "management": "unmanaged",
        "detail": "需要心跳",
    }])
    monkeypatch.setattr(service, "_scheduler_view", lambda: SchedulerView(
        enabled=False,
        running=False,
        timezone="Asia/Shanghai",
        expected_job_count=18,
        registered_job_count=0,
        jobs=[],
    ))
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(
        APP_ENV="test",
        OPERATIONS_PROBE_TIMEOUT_SECONDS=0.1,
        OPERATIONS_CACHE_TTL_SECONDS=0,
    ))

    result = await service.get_overview()

    assert result.services[0].status == "unmanaged"
    assert result.summary["attention_services"] == 1


@pytest.mark.asyncio
async def test_probe_rejects_host_outside_deployment_allowlist(monkeypatch):
    from app.operations import service

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(
        OPERATIONS_ALLOWED_HEALTH_HOSTS="leshine.work",
    ))

    result = await service._probe_service({
        "id": "metadata",
        "name": "Metadata",
        "health_url": "http://169.254.169.254/latest/meta-data",
    }, 0.1)

    assert result.status == "unconfigured"
    assert "allowlist" in result.detail


@pytest.mark.parametrize("permission", ["operations:read", "operations:admin"])
def test_overview_accepts_read_or_admin_permission(monkeypatch, permission):
    async def fake_overview():
        return SimpleNamespace(model_dump=lambda: {"generated_at": "now"})

    monkeypatch.setattr(operations_router_module, "get_overview", fake_overview)
    app = FastAPI()
    app.include_router(operations_router_module.router, prefix="/api/operations")
    token = create_access_token({
        "sub": "7", "username": "operator", "roles": [], "permissions": [permission],
    })

    response = TestClient(app).get(
        "/api/operations/overview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_overview_rejects_unrelated_permission():
    app = FastAPI()
    app.include_router(operations_router_module.router, prefix="/api/operations")
    token = create_access_token({
        "sub": "7", "username": "operator", "roles": [], "permissions": ["invoice:read"],
    })

    response = TestClient(app).get(
        "/api/operations/overview",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_control_audit_and_pause_policy_are_persistent(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.operations import service
    from app.operations.db_models import OperationAudit, SchedulerJobPolicy

    engine = create_engine("sqlite:///:memory:")
    OperationAudit.__table__.create(engine)
    SchedulerJobPolicy.__table__.create(engine)
    db = sessionmaker(bind=engine)()

    class SharedSession:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(service, "SessionLocal", SharedSession)

    audit_id = service._create_control_audit(
        actor_user_id=7,
        actor_name="operator",
        source_ip="127.0.0.1",
        job_id="staging_scan",
        action="pause",
    )
    service._finish_control_audit(audit_id, "accepted", "paused")
    service._set_paused_policy("staging_scan", True, 7)

    audit = db.get(OperationAudit, audit_id)
    assert audit.result == "accepted"
    assert audit.actor_user_id == 7
    policy = db.get(SchedulerJobPolicy, (service.socket.gethostname(), "staging_scan"))
    assert policy.paused == 1
    assert policy.updated_by == 7
    db.close()
