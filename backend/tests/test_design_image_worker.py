import base64
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock, Thread
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import sessionmaker

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.auth.models import ArkUser
from app.design_image import service, worker
from app.design_image.file_service import StoredImage
from app.design_image.models import (
    DesignImageAsset,
    DesignImageJob,
    DesignImageJobAsset,
    DesignImageMessage,
    DesignImageSession,
)
from app.design_image.schemas import RetryJobRequest, TurnCreate


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _seed_job(db, *, mode="generate", created_at=None, parameters=None, **job_values):
    preset = db.query(AiPreset).filter_by(
        preset_name="design_image_generation"
    ).one_or_none()
    if preset is None:
        provider = AiProvider(
            name="Worker provider", provider_type="direct",
            api_base="https://api.teamorouter.com", api_type="openai",
            api_key="encrypted",
            is_enabled=True, timeout_sec=30,
        )
        db.add(provider)
        db.flush()
        preset = AiPreset(
            preset_name="design_image_generation", provider_id=provider.id,
            model="gpt-image-2", parameters={"output_format": "png"},
            is_enabled=True,
        )
        db.add(preset)
        db.flush()
    owner = ArkUser(
        username=f"worker-owner-{db.query(ArkUser).count()}",
        password_hash="test", real_name="Worker Owner", is_active=True,
    )
    db.add(owner)
    db.flush()
    session = DesignImageSession(
        owner_user_id=owner.id, title="Worker test", status="active"
    )
    db.add(session)
    db.flush()
    message = DesignImageMessage(
        session_id=session.id, role="user", content="make it", status="normal"
    )
    db.add(message)
    db.flush()
    job = DesignImageJob(
        owner_user_id=owner.id,
        session_id=session.id,
        request_message_id=message.id,
        mode=mode,
        status="queued",
        prompt_snapshot="make it",
        parameters={
            "size": "1024x1024", "quality": "medium",
            "provider_id": preset.provider_id,
            **(parameters or {}),
        },
        preset_name="design_image_generation",
        model="gpt-image-2",
        idempotency_key=f"job-{owner.id}",
        created_at=created_at or _utcnow(),
        **job_values,
    )
    db.add(job)
    db.commit()
    return owner, session, message, job


def _seed_additional_job(
    db,
    owner,
    session,
    message,
    *,
    key,
    status="queued",
    created_at=None,
):
    preset = db.query(AiPreset).filter_by(
        preset_name="design_image_generation"
    ).one()
    job = DesignImageJob(
        owner_user_id=owner.id,
        session_id=session.id,
        request_message_id=message.id,
        mode="generate",
        status=status,
        prompt_snapshot="make it",
        parameters={
            "size": "1024x1024",
            "quality": "medium",
            "provider_id": preset.provider_id,
        },
        preset_name="design_image_generation",
        model="gpt-image-2",
        idempotency_key=key,
        created_at=created_at or _utcnow(),
    )
    db.add(job)
    db.commit()
    return job


def _png_bytes(color="red"):
    import io

    stream = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(stream, format="PNG")
    return stream.getvalue()


def _result(content):
    return {
        "content": content,
        "tokens_used": 12,
        "usage_detail": {
            "input_tokens": 5, "output_tokens": 7, "total_tokens": 12,
        },
        "duration_ms": 10,
        "log_id": None,
        "provider_attempt_count": 2,
        "request_id": "provider-request",
    }


def test_renew_lease_checks_time_after_lock_wait(monkeypatch):
    before_lock = datetime(2026, 8, 5, 1, 0, 0)
    after_lock = before_lock + timedelta(seconds=2)
    clock = {"now": before_lock}
    job = SimpleNamespace(lease_expires_at=before_lock + timedelta(seconds=1))

    class _Result:
        rowcount = 1

        def scalar_one_or_none(self):
            return job

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            clock["now"] = after_lock
            return _Result()

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(worker, "SessionLocal", _Session)
    monkeypatch.setattr(worker, "_utcnow", lambda: clock["now"])

    assert worker._renew_lease(7, "token", 30) is False


def test_estimated_cost_only_requires_configured_usage_classes():
    pricing = {"output_image_microusd_per_token": 31}
    usage = {
        "input_tokens_details": {"text_tokens": 3},
        "output_tokens_details": {"image_tokens": 7},
    }
    assert worker._estimated_cost(pricing, usage) == 217


@pytest.mark.parametrize("value", [None, "bad", -1, 10**100])
def test_estimated_cost_invalid_configured_usage_is_unknown(value):
    assert worker._estimated_cost(
        {"output_image_microusd_per_token": 31},
        {"output_tokens_details": {"image_tokens": value}},
    ) is None


def test_claim_is_oldest_atomic_conditional_and_returns_detached_snapshot(db):
    older = _seed_job(db, created_at=_utcnow() - timedelta(minutes=2))[3]
    newer = _seed_job(db, created_at=_utcnow() - timedelta(minutes=1))[3]
    older_id = older.id

    first = worker.claim_next_job(db, "worker-a", 120)
    second = worker.claim_next_job(db, "worker-b", 120)

    assert (first.job_id, second.job_id) == (older.id, newer.id)
    assert first.lease_token != second.lease_token
    assert first.worker_id == "worker-a"
    assert worker.claim_next_job(db, "worker-c", 120) is None
    db.close()
    assert first.job_id == older_id


def test_claim_sql_uses_skip_locked_and_status_guard():
    select_sql = str(
        worker._claim_owner_job_statement(1).compile(dialect=mysql.dialect())
    ).upper()
    update_sql = str(
        worker._claim_update_statement(1, "token", "worker", _utcnow()).compile(
            dialect=mysql.dialect()
        )
    ).upper()
    assert "FOR UPDATE SKIP LOCKED" in select_sql
    assert "STATUS = %S" in update_sql
    assert "ARK_DESIGN_IMAGE_JOBS.STATUS = %S" in update_sql


def test_candidate_owner_query_is_aggregated_capacity_filtered_and_bounded():
    sql = str(
        worker._claim_candidate_owner_statement(2).compile(
            dialect=mysql.dialect()
        )
    ).upper()

    assert "GROUP BY ARK_DESIGN_IMAGE_JOBS.OWNER_USER_ID" in sql
    assert "COUNT(" in sql
    assert "LIMIT %S" in sql
    assert "ORDER BY MIN(" in sql


def test_candidate_owner_query_returns_one_row_per_owner_despite_large_queue(
    db, monkeypatch
):
    owner, session, message, _ = _seed_job(db)
    for index in range(75):
        _seed_additional_job(
            db,
            owner,
            session,
            message,
            key=f"bounded-owner-{index}",
            created_at=_utcnow() + timedelta(milliseconds=index + 1),
        )
    _seed_job(db, created_at=_utcnow() + timedelta(minutes=1))
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2),
    )

    owner_ids = db.execute(
        worker._claim_candidate_owner_statement(2)
    ).scalars().all()

    assert len(owner_ids) == 2
    assert len(set(owner_ids)) == 2
    assert len(owner_ids) <= worker.CLAIM_OWNER_CANDIDATE_LIMIT


def test_race_saturated_owner_rolls_back_before_bounded_reselection(monkeypatch):
    events = []

    class Result:
        def __init__(self, *, values=None, scalar=None, rowcount=None):
            self.values = values
            self.scalar = scalar
            self.rowcount = rowcount

        def scalars(self):
            return self

        def all(self):
            return self.values

        def scalar_one_or_none(self):
            return self.scalar

    results = iter(
        [
            Result(values=[1, 2]),
            Result(scalar=SimpleNamespace(id=1)),
            Result(values=[11, 12]),
            Result(values=[2]),
            Result(scalar=SimpleNamespace(id=2)),
            Result(values=[]),
            Result(scalar=7),
            Result(rowcount=1),
        ]
    )

    class FakeSession:
        def execute(self, _statement):
            events.append("execute")
            return next(results)

        def rollback(self):
            events.append("rollback")

        def commit(self):
            events.append("commit")

    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2),
    )

    claim = worker.claim_next_job(FakeSession(), "bounded-reselect", 120)

    assert claim.job_id == 7
    assert events[3] == "rollback"
    assert events[-1] == "commit"


def test_locked_candidate_page_advances_so_later_owner_is_not_starved(monkeypatch):
    candidate_offsets = []
    call_index = 0

    class Result:
        def __init__(self, *, values=None, scalar=None, rowcount=None):
            self.values = values
            self.scalar = scalar
            self.rowcount = rowcount

        def scalars(self):
            return self

        def all(self):
            return self.values

        def scalar_one_or_none(self):
            return self.scalar

    class FakeSession:
        def execute(self, statement):
            nonlocal call_index
            call_index += 1
            if call_index == 1:
                offset = getattr(statement, "_offset_clause", None)
                candidate_offsets.append(0 if offset is None else offset.value)
                return Result(values=list(range(1, 17)))
            if 2 <= call_index <= 17:
                return Result(scalar=None)
            if call_index == 18:
                offset = getattr(statement, "_offset_clause", None)
                candidate_offsets.append(0 if offset is None else offset.value)
                return Result(values=[17])
            if call_index == 19:
                return Result(scalar=SimpleNamespace(id=17))
            if call_index == 20:
                return Result(values=[])
            if call_index == 21:
                return Result(scalar=99)
            return Result(rowcount=1)

        def rollback(self):
            pass

        def commit(self):
            pass

    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2),
    )

    claim = worker.claim_next_job(FakeSession(), "later-owner", 120)

    assert claim.job_id == 99
    assert candidate_offsets == [0, worker.CLAIM_OWNER_CANDIDATE_LIMIT]


def test_claim_skips_owner_at_running_cap_and_serves_next_owner(db, monkeypatch):
    first_owner, first_session, first_message, oldest = _seed_job(
        db, created_at=_utcnow() - timedelta(minutes=5)
    )
    oldest.status = "queued"
    _seed_additional_job(
        db,
        first_owner,
        first_session,
        first_message,
        key="first-running-1",
        status="running",
    )
    _seed_additional_job(
        db,
        first_owner,
        first_session,
        first_message,
        key="first-running-2",
        status="running",
    )
    second_owner, _, _, eligible = _seed_job(
        db, created_at=_utcnow() - timedelta(minutes=1)
    )
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2),
    )

    claim = worker.claim_next_job(db, "worker-cap", 120)

    assert claim.job_id == eligible.id
    db.refresh(oldest)
    assert oldest.status == "queued"
    assert second_owner.id != first_owner.id


def test_claim_never_exceeds_running_cap_for_same_owner(db, monkeypatch):
    owner, session, message, first = _seed_job(db)
    second = _seed_additional_job(
        db, owner, session, message, key="same-owner-second"
    )
    third = _seed_additional_job(
        db, owner, session, message, key="same-owner-third"
    )
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2),
    )

    claims = [
        worker.claim_next_job(db, "worker-a", 120),
        worker.claim_next_job(db, "worker-b", 120),
        worker.claim_next_job(db, "worker-c", 120),
    ]

    assert {claim.job_id for claim in claims if claim is not None} == {
        first.id,
        second.id,
    }
    assert claims[2] is None
    db.refresh(third)
    assert third.status == "queued"


def test_two_workers_concurrently_fill_exact_cap_then_serve_other_owner(
    tmp_path, monkeypatch
):
    race_engine = create_engine(
        f"sqlite:///{tmp_path / 'owner-cap-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    for table in (
        ArkUser.__table__,
        AiProvider.__table__,
        AiPreset.__table__,
        DesignImageSession.__table__,
        DesignImageMessage.__table__,
        DesignImageJob.__table__,
    ):
        table.create(race_engine)
    factory = sessionmaker(bind=race_engine, expire_on_commit=False)
    with factory() as seed:
        provider = AiProvider(
            name="Concurrent cap provider",
            provider_type="direct",
            api_base="https://example.test",
            api_type="openai",
            is_enabled=True,
            timeout_sec=30,
        )
        owners = [
            ArkUser(
                username=f"cap-owner-{index}",
                password_hash="test",
                real_name=f"Cap Owner {index}",
                is_active=True,
            )
            for index in range(2)
        ]
        seed.add_all([provider, *owners])
        seed.flush()
        seed.add(
            AiPreset(
                preset_name=service.PRESET_NAME,
                provider_id=provider.id,
                model=service.EXPECTED_MODEL,
                parameters={"output_format": "png"},
                is_enabled=True,
            )
        )
        owner_jobs = []
        for owner_index, owner in enumerate(owners):
            session = DesignImageSession(
                owner_user_id=owner.id, title=f"owner {owner_index}", status="active"
            )
            seed.add(session)
            seed.flush()
            message = DesignImageMessage(
                session_id=session.id, role="user", content="batch", status="normal"
            )
            seed.add(message)
            seed.flush()
            job_count = 3 if owner_index == 0 else 1
            for job_index in range(job_count):
                job = DesignImageJob(
                    owner_user_id=owner.id,
                    session_id=session.id,
                    request_message_id=message.id,
                    mode="generate",
                    status="queued",
                    prompt_snapshot="batch",
                    parameters={"size": "1024x1024", "quality": "medium"},
                    preset_name=service.PRESET_NAME,
                    model=service.EXPECTED_MODEL,
                    idempotency_key=f"cap-{owner_index}-{job_index}",
                    created_at=_utcnow() + timedelta(seconds=owner_index),
                )
                seed.add(job)
                owner_jobs.append(job)
        seed.commit()
        first_owner_id = owners[0].id
        other_owner_job_id = owner_jobs[-1].id

    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2),
    )
    barrier = Barrier(2)
    claims = []
    errors = []
    lock = Lock()

    def claim(worker_id):
        try:
            with factory() as race_db:
                barrier.wait()
                result = worker.claim_next_job(race_db, worker_id, 120)
            with lock:
                claims.append(result)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [Thread(target=claim, args=(name,)) for name in ("cap-a", "cap-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert errors == []
    assert len([claim for claim in claims if claim is not None]) == 2
    with factory() as verify:
        assert verify.query(DesignImageJob).filter_by(
            owner_user_id=first_owner_id, status="running"
        ).count() == 2
        other_claim = worker.claim_next_job(verify, "cap-other", 120)
        assert other_claim.job_id == other_owner_job_id


def test_claim_sql_locks_owner_before_owner_job():
    owner_sql = str(
        worker._claim_owner_statement(7).compile(dialect=mysql.dialect())
    ).upper()
    job_sql = str(
        worker._claim_owner_job_statement(7).compile(dialect=mysql.dialect())
    ).upper()

    assert "ARK_USERS.ID = %S" in owner_sql
    assert "FOR UPDATE SKIP LOCKED" in owner_sql
    assert "ARK_DESIGN_IMAGE_JOBS.OWNER_USER_ID = %S" in job_sql
    assert "FOR UPDATE SKIP LOCKED" in job_sql


def test_worker_and_http_paths_share_owner_first_lock_order():
    worker_owner_sql = str(
        worker._claim_owner_statement(7).compile(dialect=mysql.dialect())
    ).upper()
    http_owner_sql = str(
        service._owner_lock_statement(7).compile(dialect=mysql.dialect())
    ).upper()

    assert "ARK_USERS" in worker_owner_sql
    assert "ARK_USERS" in http_owner_sql
    assert "FOR UPDATE" in worker_owner_sql
    assert "FOR UPDATE" in http_owner_sql


def test_worker_and_http_concurrent_paths_finish_without_deadlock_or_excess(
    tmp_path, monkeypatch
):
    race_engine = create_engine(
        f"sqlite:///{tmp_path / 'worker-http-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    for table in (
        ArkUser.__table__,
        AiProvider.__table__,
        AiPreset.__table__,
        DesignImageSession.__table__,
        DesignImageMessage.__table__,
        DesignImageJob.__table__,
    ):
        table.create(race_engine)
    factory = sessionmaker(bind=race_engine, expire_on_commit=False)
    with factory() as seed:
        provider = AiProvider(
            name="Race provider",
            provider_type="direct",
            api_base="https://example.test",
            api_type="openai",
            is_enabled=True,
            timeout_sec=30,
        )
        owner = ArkUser(
            username="worker-http-owner",
            password_hash="test",
            real_name="Worker HTTP Owner",
            is_active=True,
        )
        seed.add_all([provider, owner])
        seed.flush()
        seed.add(
            AiPreset(
                preset_name=service.PRESET_NAME,
                provider_id=provider.id,
                model=service.EXPECTED_MODEL,
                parameters={"output_format": "png"},
                is_enabled=True,
            )
        )
        session = DesignImageSession(
            owner_user_id=owner.id, title="race", status="active"
        )
        seed.add(session)
        seed.flush()
        message = DesignImageMessage(
            session_id=session.id, role="user", content="queued", status="normal"
        )
        seed.add(message)
        seed.flush()
        seed.add(
            DesignImageJob(
                owner_user_id=owner.id,
                session_id=session.id,
                request_message_id=message.id,
                mode="generate",
                status="queued",
                prompt_snapshot="queued",
                parameters={"size": "1024x1024", "quality": "medium"},
                preset_name=service.PRESET_NAME,
                model=service.EXPECTED_MODEL,
                idempotency_key="worker-http-existing",
                created_at=_utcnow(),
            )
        )
        seed.commit()
        owner_id = owner.id
        session_id = session.id

    settings = SimpleNamespace(
        DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2,
        DESIGN_IMAGE_DAILY_LIMIT=100,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    barrier = Barrier(2)
    outcomes = []
    errors = []
    lock = Lock()

    def claim():
        try:
            with factory() as race_db:
                barrier.wait()
                outcome = worker.claim_next_job(race_db, "race-worker", 120)
            with lock:
                outcomes.append(outcome)
        except Exception as exc:
            with lock:
                errors.append(exc)

    def submit():
        try:
            with factory() as race_db:
                barrier.wait()
                service.create_turn(
                    race_db,
                    owner_id,
                    TurnCreate(
                        session_id=session_id,
                        request_id="worker-http-new",
                        prompt="分别生成2张人像图",
                    ),
                )
        except service.DesignImageActiveJobError:
            with lock:
                outcomes.append("blocked")
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [Thread(target=claim), Thread(target=submit)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert errors == []
    assert "blocked" in outcomes
    assert sum(isinstance(outcome, worker.ClaimedJob) for outcome in outcomes) == 1
    with factory() as verify:
        active_count = verify.query(DesignImageJob).filter(
            DesignImageJob.owner_user_id == owner_id,
            DesignImageJob.status.in_(("queued", "running")),
        ).count()
        assert active_count <= settings.DESIGN_IMAGE_MAX_ACTIVE_PER_USER


def test_same_request_message_jobs_finish_independently_and_retry_only_failure(
    engine, db, monkeypatch
):
    owner, session, message, first = _seed_job(db)
    second = _seed_additional_job(
        db, owner, session, message, key="batch-outcome-2"
    )
    third = _seed_additional_job(
        db, owner, session, message, key="batch-outcome-3"
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    calls = {"provider": 0, "stored": 0}

    def fake_generate(**_kwargs):
        calls["provider"] += 1
        if calls["provider"] == 3:
            raise httpx.TimeoutException("provider timeout")
        return _result(
            "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
        )

    def fake_save(image, **_kwargs):
        calls["stored"] += 1
        suffix = calls["stored"]
        return StoredImage(
            relative_path=f"1/output/result-{suffix}.png",
            thumbnail_relative_path=f"1/output/result-{suffix}_thumb.png",
            mime_type=image.mime_type,
            file_size=image.file_size,
            width=image.width,
            height=image.height,
            sha256=image.sha256,
        )

    monkeypatch.setattr(worker.ai_service, "generate_image", fake_generate)
    monkeypatch.setattr(worker.file_service, "save_private_image", fake_save)

    for worker_id in ("batch-a", "batch-b", "batch-c"):
        claim = worker.claim_next_job(db, worker_id, 120)
        assert claim is not None
        worker.execute_claimed_job(claim.job_id, claim.lease_token)

    db.expire_all()
    roots = [db.get(DesignImageJob, job.id) for job in (first, second, third)]
    succeeded = [job for job in roots if job.status == "succeeded"]
    failed = [job for job in roots if job.status == "failed"]
    assert len(succeeded) == 2
    assert len(failed) == 1
    assert len({job.response_message_id for job in succeeded}) == 2
    assert len({job.output_asset_id for job in succeeded}) == 2
    assert failed[0].response_message_id is None
    assert failed[0].output_asset_id is None

    retry = service.retry_job(
        db,
        owner.id,
        failed[0].id,
        RetryJobRequest(request_id="retry-batch-failure"),
    )
    retry_claim = worker.claim_next_job(db, "batch-retry", 120)
    worker.execute_claimed_job(retry_claim.job_id, retry_claim.lease_token)

    db.expire_all()
    retried = db.get(DesignImageJob, retry.jobs[0].id)
    assert retried.status == "succeeded"
    assert retried.retry_of_job_id == failed[0].id
    assert db.get(DesignImageJob, failed[0].id).status == "failed"
    assert retried.request_message_id == message.id


def test_generate_uses_new_session_and_publishes_only_after_storage(
    engine, db, monkeypatch
):
    owner, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    facade_sessions = []
    events = []

    def fake_generate(**kwargs):
        facade_sessions.append(kwargs.pop("db"))
        assert kwargs == {
            "preset_name": "design_image_generation",
            "prompt": "make it",
            "caller_module": "design_image",
            "caller_user_id": owner.id,
            "size": "1024x1024",
            "quality": "medium",
        }
        return _result(
            "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
        )

    def fake_save(image, **kwargs):
        events.append("stored")
        return StoredImage(
            relative_path="1/output/result.png",
            thumbnail_relative_path="1/output/result_thumb.png",
            mime_type=image.mime_type,
            file_size=image.file_size,
            width=image.width,
            height=image.height,
            sha256=image.sha256,
        )

    monkeypatch.setattr(worker.ai_service, "generate_image", fake_generate)
    monkeypatch.setattr(worker.file_service, "save_private_image", fake_save)
    worker.execute_claimed_job(job.id, claim.lease_token)

    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "succeeded"
    assert row.provider_attempt_count == 2
    assert row.claim_count == 1
    assert row.output_asset_id is not None and row.response_message_id is not None
    assert events == ["stored"]
    assert facade_sessions[0] is not db


def test_two_workers_can_call_provider_only_once_for_one_job(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    winner = worker.claim_next_job(db, "worker-a", 120)
    assert worker.claim_next_job(db, "worker-b", 120) is None
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    calls = []
    monkeypatch.setattr(
        worker.ai_service, "generate_image",
        lambda **kwargs: calls.append(kwargs) or _result(
            "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
        ),
    )
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/once.png", "1/output/once_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    worker.execute_claimed_job(job.id, winner.lease_token)
    assert len(calls) == 1


def test_two_independent_sessions_race_one_queued_job_once(tmp_path, monkeypatch):
    # SQLite ignores SKIP LOCKED, so this proves the conditional UPDATE guard under
    # a real two-thread race. MySQL 8 lock behavior remains the Phase 5 gate.
    race_engine = create_engine(
        f"sqlite:///{tmp_path / 'claim-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    ArkUser.__table__.create(race_engine)
    DesignImageJob.__table__.create(race_engine)
    factory = sessionmaker(bind=race_engine, expire_on_commit=False)
    with factory() as seed:
        seed.add(
            ArkUser(
                id=1,
                username="race-owner",
                password_hash="test",
                real_name="Race Owner",
                is_active=True,
            )
        )
        seed.add(DesignImageJob(
            owner_user_id=1, session_id=1, request_message_id=1,
            mode="generate", status="queued", prompt_snapshot="draw",
            parameters={}, preset_name="design_image_generation",
            model="gpt-image-2", idempotency_key="race", created_at=_utcnow(),
        ))
        seed.commit()

    barrier = Barrier(2)
    lock = Lock()
    claims = []
    provider_calls = []
    thread_errors = []

    monkeypatch.setattr(
        worker, "execute_claimed_job",
        lambda job_id, lease_token: provider_calls.append((job_id, lease_token)),
    )

    def compete(worker_id):
        try:
            with factory() as race_db:
                barrier.wait()
                claim = worker.claim_next_job(race_db, worker_id, 120)
            with lock:
                claims.append(claim)
                if claim is not None:
                    worker.execute_claimed_job(claim.job_id, claim.lease_token)
        except Exception as exc:
            with lock:
                thread_errors.append(exc)

    threads = [Thread(target=compete, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert thread_errors == []
    assert sum(claim is not None for claim in claims) == 1
    winner = next(claim for claim in claims if claim is not None)
    assert provider_calls == [(winner.job_id, winner.lease_token)]


def test_provider_url_uses_explicit_allowlist_and_detects_real_mime(monkeypatch):
    calls = []
    monkeypatch.setattr(
        worker.file_service, "download_provider_image",
        lambda url, *, allowed_hosts: calls.append((url, allowed_hosts)) or _png_bytes(),
    )
    normalized = worker._decode_provider_content(
        "https://cdn.example.test/result", frozenset({"cdn.example.test"})
    )
    assert normalized.mime_type == "image/png"
    assert calls == [("https://cdn.example.test/result", {"cdn.example.test"})]
    with pytest.raises(ValueError, match="not configured"):
        worker._decode_provider_content("https://cdn.example.test/result", frozenset())


def test_oversized_base64_is_rejected_before_decode(monkeypatch):
    called = []
    monkeypatch.setattr(
        worker.image_runtime.base64,
        "b64decode",
        lambda *args, **kwargs: called.append(1),
    )
    encoded = "A" * (((20 * 1024 * 1024 + 2) // 3) * 4 + 4)
    with pytest.raises(ValueError, match="too large"):
        worker._decode_provider_content(encoded, frozenset())
    assert called == []


def test_invalid_provider_payload_keeps_actual_attempt_count(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(
        worker.ai_service, "generate_image",
        lambda **kwargs: _result("not-base64"),
    )
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed"
    assert row.provider_attempt_count == 2


def test_edit_sends_base_then_references_by_position(
    engine, db, tmp_path, monkeypatch
):
    owner, session, _, job = _seed_job(db, mode="edit")
    monkeypatch.setattr(
        worker.get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path)
    )
    paths = []
    for name, payload in (("base.png", b"base"), ("ref2.png", b"ref2"), ("ref1.png", b"ref1")):
        path = tmp_path / str(owner.id) / "upload" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        asset = DesignImageAsset(
            session_id=session.id, asset_type="upload",
            storage_path=f"{owner.id}/upload/{name}", mime_type="image/png",
            file_size=len(payload), width=1, height=1, sha256=name.ljust(64, "0"),
            status="attached", created_by=owner.id,
        )
        db.add(asset)
        db.flush()
        paths.append(asset)
    job.base_asset_id = paths[0].id
    db.add_all([
        DesignImageJobAsset(job_id=job.id, asset_id=paths[1].id, role="reference", position=2),
        DesignImageJobAsset(job_id=job.id, asset_id=paths[2].id, role="reference", position=1),
    ])
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))

    def fake_edit(**kwargs):
        assert [image["content"] for image in kwargs["images"]] == [b"base", b"ref1", b"ref2"]
        return _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())

    monkeypatch.setattr(worker.ai_service, "edit_image", fake_edit)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/x.png", "1/output/x_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    worker.execute_claimed_job(job.id, claim.lease_token)


def test_generate_with_references_uses_edit_and_preserves_reference_order(
    engine, db, tmp_path, monkeypatch
):
    owner, session, _, job = _seed_job(db, mode="generate")
    monkeypatch.setattr(worker.get_settings(), "DESIGN_IMAGE_STORAGE_ROOT", str(tmp_path))
    for position in range(4):
        payload = f"ref-{position}".encode()
        path = tmp_path / str(owner.id) / "upload" / f"ref-{position}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        asset = DesignImageAsset(
            session_id=session.id, asset_type="upload",
            storage_path=f"{owner.id}/upload/ref-{position}.png", mime_type="image/png",
            file_size=len(payload), width=1, height=1, sha256=str(position).ljust(64, "0"),
            status="attached", created_by=owner.id,
        )
        db.add(asset)
        db.flush()
        db.add(DesignImageJobAsset(
            job_id=job.id, asset_id=asset.id, role="reference", position=position
        ))
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    calls = []
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: pytest.fail("generation must not run"))
    monkeypatch.setattr(
        worker.ai_service, "edit_image",
        lambda **kwargs: calls.append([image["content"] for image in kwargs["images"]])
        or _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode()),
    )
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/refs.png", "1/output/refs_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    worker.execute_claimed_job(job.id, claim.lease_token)
    assert calls == [[b"ref-0", b"ref-1", b"ref-2", b"ref-3"]]


def test_expired_lease_stops_before_provider(engine, db, monkeypatch):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    with factory() as expire_db:
        expire_db.get(DesignImageJob, job.id).lease_expires_at = _utcnow() - timedelta(seconds=1)
        expire_db.commit()
    calls = []
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: calls.append(1))
    worker.execute_claimed_job(job.id, claim.lease_token)
    assert calls == []


def test_provider_success_after_lease_expiry_cleans_stored_without_publish(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    def expire_then_succeed(**kwargs):
        with factory() as expire_db:
            expire_db.get(DesignImageJob, job.id).lease_expires_at = _utcnow() - timedelta(seconds=1)
            expire_db.commit()
        return _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())
    monkeypatch.setattr(worker.ai_service, "generate_image", expire_then_succeed)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/expired.png", "1/output/expired_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    deleted = []
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "running" and row.output_asset_id is None
    assert deleted == ["1/output/expired.png", "1/output/expired_thumb.png"]


def test_provider_failure_after_lease_expiry_does_not_overwrite_job(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    exc = RuntimeError("provider failed")
    setattr(exc, "log_id", 42)
    def expire_then_fail(**kwargs):
        with factory() as expire_db:
            expire_db.get(DesignImageJob, job.id).lease_expires_at = _utcnow() - timedelta(seconds=1)
            expire_db.commit()
        raise exc
    monkeypatch.setattr(worker.ai_service, "generate_image", expire_then_fail)
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "running" and row.error_code is None and row.ai_call_log_id is None


@pytest.mark.parametrize("change", ["provider", "model", "rate_card"])
def test_preset_change_after_queue_fails_before_provider(
    engine, db, monkeypatch, change
):
    _, _, _, job = _seed_job(
        db, pricing_snapshot={"output_image_microusd_per_token": 31}
    )
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {
        **(preset.parameters or {}),
        "rate_card": {"output_image_microusd_per_token": 31},
    }
    db.commit()
    # Align the queued snapshot first, then mutate the live preset.
    job.parameters["provider_id"] = preset.provider_id
    job.model = preset.model
    db.commit()
    if change == "provider":
        replacement = AiProvider(
            name="Replacement provider", provider_type="direct",
            api_base="https://replacement.test", api_type="openai",
            is_enabled=True, timeout_sec=30,
        )
        db.add(replacement)
        db.flush()
        preset.provider_id = replacement.id
    elif change == "model":
        preset.model = "gpt-image-new"
    else:
        preset.parameters = {
            **preset.parameters,
            "rate_card": {"output_image_microusd_per_token": 99},
        }
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    calls = []
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: calls.append(1))
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert calls == []
    assert row.status == "failed" and row.error_code == "configuration_error"


def test_late_provider_response_cannot_publish_after_stale_recovery(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "slow-worker", 120)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)

    def late_result(**kwargs):
        with factory() as recovery_db:
            stale_job = recovery_db.get(DesignImageJob, job.id)
            stale_job.lease_expires_at = _utcnow() - timedelta(seconds=1)
            recovery_db.commit()
            assert worker.recover_stale_jobs(recovery_db, _utcnow()) == 1
        return _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())

    deleted = []
    monkeypatch.setattr(worker.ai_service, "generate_image", late_result)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/late.png", "1/output/late_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    monkeypatch.setattr(worker.file_service, "delete_private_file", deleted.append)
    worker.execute_claimed_job(job.id, claim.lease_token)

    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed" and row.error_code == "worker_timeout"
    assert row.output_asset_id is None and row.response_message_id is None
    assert db.query(DesignImageAsset).filter_by(asset_type="output").count() == 0
    assert db.query(DesignImageMessage).filter_by(role="assistant").count() == 0
    assert deleted == ["1/output/late.png", "1/output/late_thumb.png"]


@pytest.mark.parametrize(
    ("exc", "error_code"),
    [
        (ValueError("bad request"), "validation_error"),
        (TimeoutError("slow"), "provider_timeout"),
        (RuntimeError("boom"), "unknown_error"),
    ],
)
def test_failures_have_stable_actionable_mapping(
    engine, db, monkeypatch, exc, error_code
):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    setattr(exc, "provider_attempt_count", 3)
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: (_ for _ in ()).throw(exc))
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed" and row.error_code == error_code
    assert row.error_message and "重试" in row.error_message
    assert row.provider_attempt_count == 3
    assert row.billing_certainty == "unknown"


def test_failure_persists_ai_call_log_id_while_lease_is_valid(
    engine, db, monkeypatch, caplog, capsys
):
    _, _, _, job = _seed_job(db)
    db.execute(text("PRAGMA foreign_keys=ON"))
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    exc = RuntimeError("provider failed")
    setattr(exc, "provider_attempt_count", 2)
    setattr(exc, "log_id", 77)
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: (_ for _ in ()).throw(exc))
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed" and row.ai_call_log_id is None
    assert "AI call log 77 is missing" in caplog.text
    assert "AI call log 77 is missing" in capsys.readouterr().out


def test_failure_compensates_pending_ai_call_log_in_same_transaction(
    engine, db, monkeypatch
):
    _, _, _, job = _seed_job(db)
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    log = AiCallLog(
        caller_module="design_image", preset_id=preset.id,
        preset_name=preset.preset_name, provider_type="direct",
        model=preset.model, prompt_snapshot="draw", status="pending",
    )
    db.add(log)
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    exc = RuntimeError("provider failed")
    setattr(exc, "log_id", log.id)

    assert worker._finalize_failure(job.id, claim.lease_token, exc) is True
    db.expire_all()
    assert db.get(AiCallLog, log.id).status == "error"
    assert db.get(AiCallLog, log.id).error_code == "unknown_error"
    assert db.get(DesignImageJob, job.id).ai_call_log_id == log.id


@pytest.mark.parametrize(
    ("rate_card", "usage_detail", "expected_cost", "certainty"),
    [
        (
            {"output_image_microusd_per_token": 31},
            {"output_tokens": 7, "output_tokens_details": {"image_tokens": 7}},
            217,
            "estimated",
        ),
        ({}, {"output_tokens_details": {"image_tokens": 7}}, None, "unknown"),
        ({"output_image_microusd_per_token": 31}, {"output_tokens": 7}, None, "unknown"),
    ],
)
def test_success_cost_requires_matching_detailed_usage_and_rate(
    engine, db, monkeypatch, rate_card, usage_detail, expected_cost, certainty
):
    _, _, _, job = _seed_job(db, pricing_snapshot=rate_card)
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {**(preset.parameters or {}), "rate_card": rate_card}
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    result = _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())
    result["usage_detail"] = usage_detail
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: result)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/cost.png", "1/output/cost_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )
    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.estimated_cost_microusd == expected_cost
    assert row.billing_certainty == certainty


def test_bad_top_level_usage_does_not_fail_paid_success(
    engine, db, monkeypatch
):
    rate_card = {"output_image_microusd_per_token": 31}
    _, _, _, job = _seed_job(db, pricing_snapshot=rate_card)
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {**(preset.parameters or {}), "rate_card": rate_card}
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    result = _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())
    result["tokens_used"] = "oops"
    result["usage_detail"] = {
        "input_tokens": "bad", "output_tokens": 7, "total_tokens": "oops",
        "output_tokens_details": {"image_tokens": 7},
    }
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: result)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/usage.png", "1/output/usage_thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )

    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "succeeded"
    assert (row.input_tokens, row.output_tokens, row.total_tokens) == (None, 7, None)
    assert row.estimated_cost_microusd == 217
    assert row.billing_certainty == "estimated"


@pytest.mark.parametrize("value", [True, "7", -1, 7.5, 2**63])
def test_top_level_usage_rejects_non_bigint_values(value):
    assert worker._usage_values({
        "usage_detail": {
            "input_tokens": value,
            "output_tokens": value,
            "total_tokens": value,
        }
    }) == (None, None, None)


@pytest.mark.parametrize("usage_detail", ["bad", [], 7])
def test_non_dict_usage_detail_keeps_image_success_unknown_cost(
    engine, db, monkeypatch, usage_detail
):
    rate_card = {"output_image_microusd_per_token": 31}
    _, _, _, job = _seed_job(db, pricing_snapshot=rate_card)
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {**(preset.parameters or {}), "rate_card": rate_card}
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    result = _result("data:image/png;base64," + base64.b64encode(_png_bytes()).decode())
    result["usage_detail"] = usage_detail
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: result)
    monkeypatch.setattr(
        worker.file_service, "save_private_image",
        lambda image, **kwargs: StoredImage(
            "1/output/non-dict.png", "1/output/non-dict-thumb.png", image.mime_type,
            image.file_size, image.width, image.height, image.sha256,
        ),
    )

    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "succeeded"
    assert row.billing_certainty == "unknown"
    assert row.estimated_cost_microusd is None


@pytest.mark.parametrize("failure_stage", ["decode", "normalize", "store"])
def test_post_result_failures_preserve_log_and_attempt_audit(
    engine, db, monkeypatch, failure_stage
):
    _, _, _, job = _seed_job(db)
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    log = AiCallLog(
        caller_module="design_image", preset_id=preset.id,
        preset_name=preset.preset_name, provider_type="direct",
        model=preset.model, prompt_snapshot="draw", status="pending",
    )
    db.add(log)
    db.commit()
    claim = worker.claim_next_job(db, "worker-a", 120)
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    content = "invalid" if failure_stage == "decode" else (
        "data:image/png;base64," + base64.b64encode(_png_bytes()).decode()
    )
    result = _result(content)
    result["log_id"] = log.id
    result["provider_attempt_count"] = 3
    monkeypatch.setattr(worker.ai_service, "generate_image", lambda **kwargs: result)
    if failure_stage == "normalize":
        monkeypatch.setattr(
            worker.file_service, "normalize_upload",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("normalize failed")),
        )
    elif failure_stage == "store":
        monkeypatch.setattr(
            worker.file_service, "save_private_image",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("store failed")),
        )

    worker.execute_claimed_job(job.id, claim.lease_token)
    db.expire_all()
    row = db.get(DesignImageJob, job.id)
    assert row.status == "failed"
    assert row.ai_call_log_id == log.id
    assert row.provider_attempt_count == 3
    assert db.get(AiCallLog, log.id).status == "error"


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (429, "rate limit", "rate_limited"),
        (503, "unavailable", "provider_unavailable"),
        (400, "content_policy moderation", "moderation_blocked"),
    ],
)
def test_http_provider_errors_have_stable_codes(status, body, code):
    response = httpx.Response(status, text=body, request=httpx.Request("POST", "https://provider"))
    exc = httpx.HTTPStatusError(body, request=response.request, response=response)
    assert worker._map_error(exc)[0] == code


def test_recover_stale_only_fails_expired_running_jobs(db):
    expired = _seed_job(db)[3]
    active = _seed_job(db)[3]
    queued = _seed_job(db)[3]
    now = _utcnow()
    for row, expires in ((expired, now - timedelta(seconds=1)), (active, now + timedelta(seconds=60))):
        row.status = "running"
        row.lease_token = f"lease-{row.id}"
        row.claimed_by = "worker"
        row.lease_expires_at = expires
    db.commit()

    assert worker.recover_stale_jobs(db, now) == 1
    db.expire_all()
    assert db.get(DesignImageJob, expired.id).error_code == "worker_timeout"
    assert db.get(DesignImageJob, active.id).status == "running"
    assert db.get(DesignImageJob, queued.id).status == "queued"


def test_heartbeat_renews_live_unexpired_lease_before_stale_recovery(engine, db, monkeypatch):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 1)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    with factory() as force_expired:
        row = force_expired.get(DesignImageJob, job.id)
        row.lease_expires_at = _utcnow() + timedelta(seconds=1)
        force_expired.commit()

    assert worker._renew_lease(job.id, claim.lease_token, 30) is True
    with factory() as recovery_db:
        assert worker.recover_stale_jobs(recovery_db, _utcnow()) == 0
        row = recovery_db.get(DesignImageJob, job.id)
        assert row.status == "running"
        assert row.lease_expires_at > _utcnow() + timedelta(seconds=20)


def test_heartbeat_cannot_revive_expired_lease(engine, db, monkeypatch):
    _, _, _, job = _seed_job(db)
    claim = worker.claim_next_job(db, "worker-a", 1)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", factory)
    with factory() as force_expired:
        row = force_expired.get(DesignImageJob, job.id)
        row.lease_expires_at = _utcnow() - timedelta(seconds=1)
        force_expired.commit()

    assert worker._renew_lease(job.id, claim.lease_token, 30) is False
    with factory() as recovery_db:
        assert worker.recover_stale_jobs(recovery_db, _utcnow()) == 1
        assert recovery_db.get(DesignImageJob, job.id).error_code == "worker_timeout"


def test_cleanup_soft_deletes_only_unreferenced_expired_drafts_then_deletes_files(
    engine, db, monkeypatch
):
    owner, session, _, job = _seed_job(db)
    now = _utcnow()

    def asset(name, expires):
        row = DesignImageAsset(
            session_id=session.id, asset_type="upload", storage_path=f"1/upload/{name}.png",
            mime_type="image/png", file_size=1, width=1, height=1, sha256=name.ljust(64, "0"),
            status="draft", expires_at=expires, created_by=owner.id,
        )
        db.add(row)
        db.flush()
        return row

    orphan = asset("orphan", now - timedelta(hours=1))
    base = asset("base", now - timedelta(hours=1))
    linked = asset("linked", now - timedelta(hours=1))
    current = asset("current", now + timedelta(hours=1))
    job.base_asset_id = base.id
    db.add(DesignImageJobAsset(job_id=job.id, asset_id=linked.id, role="reference", position=0))
    db.commit()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    deleted = []

    def delete_after_commit(path):
        with factory() as verify_db:
            assert verify_db.get(DesignImageAsset, orphan.id).deleted_at is not None
        deleted.append(path)

    monkeypatch.setattr(worker.file_service, "delete_private_file", delete_after_commit)
    assert worker.cleanup_expired_drafts(db, now) == 1
    db.expire_all()
    assert db.get(DesignImageAsset, orphan.id).deleted_at is not None
    assert all(db.get(DesignImageAsset, row.id).deleted_at is None for row in (base, linked, current))
    assert deleted == ["1/upload/orphan.png", "1/upload/orphan_thumb.png"]
