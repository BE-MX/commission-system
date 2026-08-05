from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.dialects import mysql

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.auth.models import ArkUser
from app.design_image import service
from app.design_image.file_service import NormalizedImage, StoredImage
from app.design_image.models import (
    DesignImageAsset,
    DesignImageJob,
    DesignImageJobAsset,
    DesignImageMessage,
    DesignImageSession,
)
from app.design_image.schemas import RetryJobRequest, TurnCreate


SHANGHAI = timezone(timedelta(hours=8))


def _user(db, username: str, *, active: bool = True) -> ArkUser:
    row = ArkUser(
        username=username,
        password_hash="test-hash",
        real_name=username,
        is_active=active,
    )
    db.add(row)
    db.flush()
    return row


def _preset(db) -> AiPreset:
    provider = AiProvider(
        name="Design image provider",
        provider_type="direct",
        api_base="https://example.test",
        api_type="openai",
        api_key="encrypted",
        is_enabled=True,
        timeout_sec=30,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={"output_format": "png"},
        is_enabled=True,
    )
    db.add(preset)
    db.flush()
    return preset


def _session(db, owner_id: int, title: str = "对话") -> DesignImageSession:
    row = DesignImageSession(owner_user_id=owner_id, title=title, status="active")
    db.add(row)
    db.flush()
    return row


def _message(db, session_id: int, content: str = "要求") -> DesignImageMessage:
    row = DesignImageMessage(
        session_id=session_id, role="user", content=content, status="normal"
    )
    db.add(row)
    db.flush()
    return row


def _asset(
    db,
    owner_id: int,
    session_id: int,
    *,
    status: str = "draft",
    asset_type: str = "upload",
    storage_path: str | None = None,
) -> DesignImageAsset:
    row = DesignImageAsset(
        session_id=session_id,
        asset_type=asset_type,
        storage_path=storage_path or f"{owner_id}/upload/test-{owner_id}.png",
        mime_type="image/png",
        file_size=10,
        width=10,
        height=10,
        sha256=f"{owner_id:064d}"[-64:],
        status=status,
        created_by=owner_id,
    )
    db.add(row)
    db.flush()
    return row


def _job(
    db,
    owner_id: int,
    session_id: int,
    message_id: int,
    *,
    key: str,
    status: str = "succeeded",
    created_at: datetime | None = None,
    **values,
) -> DesignImageJob:
    row = DesignImageJob(
        owner_user_id=owner_id,
        session_id=session_id,
        request_message_id=message_id,
        mode=values.pop("mode", "generate"),
        status=status,
        prompt_snapshot=values.pop("prompt_snapshot", "本轮用户要求：要求"),
        parameters=values.pop(
            "parameters", {"size": "1024x1024", "quality": "medium"}
        ),
        preset_name="design_image_generation",
        model="gpt-image-2",
        idempotency_key=key,
        created_at=created_at or datetime.now(timezone.utc).replace(tzinfo=None),
        **values,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def configured(db):
    owner = _user(db, "owner")
    other = _user(db, "other")
    _preset(db)
    db.commit()
    return owner, other


def _turn(**overrides) -> TurnCreate:
    values = {
        "request_id": "request-0001",
        "prompt": "把背景换成高端门店",
        "size": "1024x1536",
        "quality": "medium",
    }
    values.update(overrides)
    return TurnCreate(**values)


def test_turn_schema_forbids_client_controlled_mode_model_provider_and_bad_choices():
    for field in ("mode", "model", "provider"):
        with pytest.raises(PydanticValidationError):
            _turn(**{field: "client-controlled"})
    with pytest.raises(PydanticValidationError):
        _turn(size="2048x2048")
    with pytest.raises(PydanticValidationError):
        _turn(quality="ultra")
    with pytest.raises(PydanticValidationError):
        _turn(reference_asset_ids=[1, 2, 3, 4, 5])
    with pytest.raises(PydanticValidationError):
        _turn(base_asset_id=1, reference_asset_ids=[1])


def test_owner_scoped_resources_hide_absent_and_cross_owner_with_one_error(configured, db):
    owner, other = configured
    foreign_session = _session(db, other.id)
    foreign_message = _message(db, foreign_session.id)
    foreign_asset = _asset(db, other.id, foreign_session.id, status="attached")
    foreign_job = _job(
        db, other.id, foreign_session.id, foreign_message.id, key="foreign"
    )
    db.commit()

    accessors = (
        (service.get_session_detail, foreign_session.id),
        (service.get_asset, foreign_asset.id),
        (service.get_job, foreign_job.id),
    )
    for accessor, foreign_id in accessors:
        errors = []
        for resource_id in (foreign_id, 999_999):
            with pytest.raises(service.DesignImageNotFoundError) as exc:
                accessor(db, owner.id, resource_id)
            errors.append(str(exc.value))
        assert errors == [service.NOT_FOUND_MESSAGE, service.NOT_FOUND_MESSAGE]


def test_session_list_is_owner_only_stable_cursor_pagination(configured, db):
    owner, other = configured
    base = datetime(2026, 8, 5, 3, 0, 0)
    rows = []
    for index in range(3):
        row = _session(db, owner.id, f"owner-{index}")
        row.updated_at = base + timedelta(minutes=index)
        rows.append(row)
    foreign = _session(db, other.id, "foreign")
    foreign.updated_at = base + timedelta(days=1)
    db.commit()

    first = service.list_sessions(db, owner.id, limit=2)
    second = service.list_sessions(db, owner.id, limit=2, cursor=first.next_cursor)

    assert [row.title for row in first.items] == ["owner-2", "owner-1"]
    assert [row.title for row in second.items] == ["owner-0"]
    assert second.next_cursor is None


def test_session_detail_hides_expired_drafts_but_keeps_attached_assets(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    expired = _asset(db, owner.id, session.id)
    expired.expires_at = datetime(2026, 8, 4, 0, 0, 0)
    attached = _asset(db, owner.id, session.id, status="attached")
    db.commit()

    detail = service.get_session_detail(
        db,
        owner.id,
        session.id,
        now=datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI),
    )

    assert [asset.id for asset in detail["assets"]] == [attached.id]


def test_create_turn_is_idempotent_and_implicitly_creates_one_session(configured, db):
    owner, _ = configured
    payload = _turn()

    first = service.create_turn(db, owner.id, payload)
    second = service.create_turn(db, owner.id, payload)

    assert second.job.id == first.job.id
    assert db.query(DesignImageJob).count() == 1
    assert db.query(DesignImageSession).filter_by(owner_user_id=owner.id).count() == 1
    assert db.query(DesignImageMessage).count() == 1


def test_create_turn_attaches_ordered_references_and_uses_explicit_base(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    base = _asset(db, owner.id, session.id, status="attached", asset_type="generated")
    first_ref = _asset(db, owner.id, session.id, storage_path="1/upload/a.png")
    second_ref = _asset(db, owner.id, session.id, storage_path="1/upload/b.png")
    historical = _message(db, session.id, "不要把这条历史消息发给模型")
    db.commit()

    result = service.create_turn(
        db,
        owner.id,
        _turn(
            request_id="ordered-assets",
            session_id=session.id,
            base_asset_id=base.id,
            reference_asset_ids=[second_ref.id, first_ref.id],
        ),
    )

    links = (
        db.query(DesignImageJobAsset)
        .filter_by(job_id=result.job.id)
        .order_by(DesignImageJobAsset.position)
        .all()
    )
    assert result.job.mode == "edit"
    assert result.job.base_asset_id == base.id
    assert [(link.asset_id, link.position) for link in links] == [
        (second_ref.id, 0),
        (first_ref.id, 1),
    ]
    assert second_ref.status == first_ref.status == "attached"
    assert second_ref.message_id == first_ref.message_id == result.message.id
    assert "当前基准图" in result.job.prompt_snapshot
    assert "把背景换成高端门店" in result.job.prompt_snapshot
    assert historical.content not in result.job.prompt_snapshot
    assert result.job.parameters == {"size": "1024x1536", "quality": "medium"}


@pytest.mark.parametrize("resource_kind", ["base", "reference"])
def test_create_turn_rejects_cross_owner_cross_session_and_unusable_assets(
    configured, db, resource_kind
):
    owner, other = configured
    current = _session(db, owner.id)
    other_owner_session = _session(db, other.id)
    foreign = _asset(db, other.id, other_owner_session.id, status="attached")
    db.commit()
    kwargs = (
        {"base_asset_id": foreign.id}
        if resource_kind == "base"
        else {"reference_asset_ids": [foreign.id]}
    )
    with pytest.raises(service.DesignImageNotFoundError):
        service.create_turn(
            db,
            owner.id,
            _turn(request_id=f"foreign-{resource_kind}", session_id=current.id, **kwargs),
        )
    assert db.query(DesignImageJob).count() == 0
    assert db.query(DesignImageMessage).count() == 0


def test_create_turn_rejects_own_asset_from_another_session_and_expired_draft(
    configured, db
):
    owner, _ = configured
    current = _session(db, owner.id, "current")
    other_session = _session(db, owner.id, "other")
    wrong_session = _asset(db, owner.id, other_session.id, status="attached")
    expired = _asset(db, owner.id, current.id)
    expired.expires_at = datetime(2026, 8, 4, 0, 0, 0)
    db.commit()
    now = datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI)

    for request_id, reference_id in (
        ("wrong-session", wrong_session.id),
        ("expired-draft", expired.id),
    ):
        with pytest.raises(service.DesignImageNotFoundError):
            service.create_turn(
                db,
                owner.id,
                _turn(
                    request_id=request_id,
                    session_id=current.id,
                    reference_asset_ids=[reference_id],
                ),
                now=now,
            )


def test_create_turn_never_falls_back_to_latest_generated_asset(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    _asset(db, owner.id, session.id, status="attached", asset_type="generated")
    db.commit()

    result = service.create_turn(
        db, owner.id, _turn(request_id="no-latest", session_id=session.id)
    )

    assert result.job.mode == "generate"
    assert result.job.base_asset_id is None


def test_create_turn_snapshots_configured_rate_card_without_hardcoded_prices(
    configured, db
):
    owner, _ = configured
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {
        "output_format": "png",
        "rate_card": {
            "name": "teamrouter-pilot-2026-08",
            "currency": "USD",
            "output_image_microusd_per_token": 31,
        },
    }
    db.commit()

    result = service.create_turn(db, owner.id, _turn(request_id="priced"))

    assert result.job.pricing_snapshot == preset.parameters["rate_card"]
    assert result.job.estimated_cost_microusd is None


def test_quota_uses_asia_shanghai_natural_day_and_counts_failed_accepted_jobs(
    configured, db, monkeypatch
):
    owner, _ = configured
    monkeypatch.setattr(service.get_settings(), "DESIGN_IMAGE_DAILY_LIMIT", 2)
    session = _session(db, owner.id)
    message = _message(db, session.id)
    # 2026-08-05 00:00 Shanghai == 2026-08-04 16:00 UTC.
    _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="before-day",
        status="failed",
        created_at=datetime(2026, 8, 4, 15, 59, 59),
    )
    _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="today-failed",
        status="failed",
        created_at=datetime(2026, 8, 4, 16, 0, 0),
    )
    db.commit()
    now = datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI)

    service.create_turn(
        db, owner.id, _turn(request_id="last-slot", session_id=session.id), now=now
    )
    with pytest.raises(service.DesignImageQuotaExceededError):
        service.create_turn(
            db, owner.id, _turn(request_id="over-limit", session_id=session.id), now=now
        )


def test_capacity_queries_use_mysql_current_reads_after_owner_row_lock(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    _job(db, owner.id, session.id, message.id, key="active", status="queued")
    db.commit()

    with pytest.raises(service.DesignImageActiveJobError):
        service.create_turn(
            db, owner.id, _turn(request_id="blocked", session_id=session.id)
        )

    statements = (
        service._owner_lock_statement(owner.id),
        service._accepted_jobs_statement(
            owner.id, datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI), for_update=True
        ),
        service._active_job_statement(owner.id, for_update=True),
    )
    sql = [
        str(statement.compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )).upper()
        for statement in statements
    ]
    assert "ARK_USERS" in sql[0]
    assert "CREATED_AT" in sql[1]
    assert "STATUS" in sql[2]
    assert all("FOR UPDATE" in statement for statement in sql)


def test_unique_key_race_rolls_back_every_write_and_returns_winner(
    configured, db, monkeypatch
):
    owner, _ = configured
    existing_session = _session(db, owner.id, "winner")
    existing_message = _message(db, existing_session.id, "winner")
    winner = _job(
        db,
        owner.id,
        existing_session.id,
        existing_message.id,
        key="race-key",
        status="succeeded",
    )
    db.commit()
    original_find = service._find_job_by_idempotency
    calls = 0

    def miss_then_find(session, owner_id, key):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_find(session, owner_id, key)

    monkeypatch.setattr(service, "_find_job_by_idempotency", miss_then_find)

    replay = service.create_turn(db, owner.id, _turn(request_id="race-key"))

    assert replay.job.id == winner.id
    assert db.query(DesignImageJob).count() == 1
    assert db.query(DesignImageSession).count() == 1
    assert db.query(DesignImageMessage).count() == 1


def test_retry_creates_new_job_with_new_idempotency_without_mutating_old(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    reference = _asset(db, owner.id, session.id, status="attached")
    old = _job(db, owner.id, session.id, message.id, key="old", status="failed")
    db.add(DesignImageJobAsset(job_id=old.id, asset_id=reference.id, role="reference", position=0))
    db.commit()

    result = service.retry_job(
        db, owner.id, old.id, RetryJobRequest(request_id="retry-new")
    )
    replay = service.retry_job(
        db, owner.id, old.id, RetryJobRequest(request_id="retry-new")
    )

    assert result.job.id != old.id
    assert replay.job.id == result.job.id
    assert result.job.retry_of_job_id == old.id
    assert result.job.status == "queued"
    assert old.status == "failed"
    assert db.query(DesignImageJob).count() == 2
    assert [(x.asset_id, x.position) for x in result.reference_links] == [
        (reference.id, 0)
    ]


def test_retry_obeys_same_one_active_job_limit(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    failed = _job(db, owner.id, session.id, message.id, key="failed", status="failed")
    _job(db, owner.id, session.id, message.id, key="active", status="running")
    db.commit()

    with pytest.raises(service.DesignImageActiveJobError):
        service.retry_job(
            db, owner.id, failed.id, RetryJobRequest(request_id="retry-blocked")
        )


def test_retry_requires_current_preset_and_snapshots_current_rate_card(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    old = _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="old-rate",
        status="failed",
        pricing_snapshot={"name": "old"},
    )
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {"rate_card": {"name": "current"}}
    db.commit()

    retried = service.retry_job(
        db, owner.id, old.id, RetryJobRequest(request_id="current-rate")
    )
    assert retried.job.pricing_snapshot == {"name": "current"}
    assert old.pricing_snapshot == {"name": "old"}

    retried.job.status = "failed"
    preset.is_enabled = False
    db.commit()
    with pytest.raises(service.DesignImageConfigurationError):
        service.retry_job(
            db, owner.id, old.id, RetryJobRequest(request_id="disabled-preset")
        )


def test_draft_upload_uses_file_service_and_db_failure_cleans_only_created_files(
    configured, db, monkeypatch
):
    owner, _ = configured
    session = _session(db, owner.id)
    db.commit()
    normalized = NormalizedImage(
        content=b"normalized", mime_type="image/png", width=10, height=20, sha256="a" * 64
    )
    stored = StoredImage(
        relative_path=f"{owner.id}/upload/a.png",
        thumbnail_relative_path=f"{owner.id}/upload/a_thumb.png",
        mime_type="image/png",
        file_size=10,
        width=10,
        height=20,
        sha256="a" * 64,
    )
    deleted = []
    monkeypatch.setattr(service.file_service, "normalize_upload", lambda *_: normalized)
    monkeypatch.setattr(service.file_service, "save_private_image", lambda *_args, **_kw: stored)
    monkeypatch.setattr(service.file_service, "delete_private_file", deleted.append)
    real_commit = db.commit

    def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.create_draft_asset(
            db, owner.id, session.id, b"raw", "image/png"
        )
    monkeypatch.setattr(db, "commit", real_commit)

    assert deleted == [stored.relative_path, stored.thumbnail_relative_path]
    assert db.query(DesignImageAsset).count() == 0


def test_draft_upload_persists_normalized_metadata_and_expiration(
    configured, db, monkeypatch
):
    owner, _ = configured
    session = _session(db, owner.id)
    db.commit()
    stored = StoredImage(
        relative_path=f"{owner.id}/upload/a.png",
        thumbnail_relative_path=f"{owner.id}/upload/a_thumb.png",
        mime_type="image/png",
        file_size=123,
        width=640,
        height=480,
        sha256="b" * 64,
    )
    monkeypatch.setattr(
        service.file_service,
        "normalize_upload",
        lambda *_: SimpleNamespace(content=b"normalized"),
    )
    monkeypatch.setattr(
        service.file_service, "save_private_image", lambda *_args, **_kwargs: stored
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI)

    asset = service.create_draft_asset(
        db, owner.id, session.id, b"raw", "image/png", now=now
    )

    assert asset.status == "draft"
    assert asset.storage_path == stored.relative_path
    assert (asset.file_size, asset.width, asset.height, asset.sha256) == (
        123,
        640,
        480,
        "b" * 64,
    )
    assert asset.expires_at == datetime(2026, 8, 6, 4, 0, 0)


def test_delete_draft_rejects_attached_or_referenced_and_deletes_file_after_commit(
    configured, db, monkeypatch
):
    owner, _ = configured
    session = _session(db, owner.id)
    attached = _asset(db, owner.id, session.id, status="attached")
    draft = _asset(db, owner.id, session.id, storage_path=f"{owner.id}/upload/draft.png")
    message = _message(db, session.id)
    job = _job(db, owner.id, session.id, message.id, key="ref", status="failed")
    db.add(DesignImageJobAsset(job_id=job.id, asset_id=draft.id, role="reference", position=0))
    db.commit()

    for asset_id in (attached.id, draft.id):
        with pytest.raises(service.DesignImageAssetConflictError):
            service.delete_draft_asset(db, owner.id, asset_id)

    unreferenced = _asset(
        db, owner.id, session.id, storage_path=f"{owner.id}/upload/free.png"
    )
    db.commit()
    deleted = []
    monkeypatch.setattr(service.file_service, "delete_private_file", deleted.append)

    service.delete_draft_asset(db, owner.id, unreferenced.id)

    assert unreferenced.deleted_at is not None
    assert deleted == [
        f"{owner.id}/upload/free.png",
        f"{owner.id}/upload/free_thumb.png",
    ]


def test_config_reports_verified_choices_limit_and_remaining(configured, db, monkeypatch):
    owner, _ = configured
    monkeypatch.setattr(service.get_settings(), "DESIGN_IMAGE_DAILY_LIMIT", 3)
    session = _session(db, owner.id)
    message = _message(db, session.id)
    _job(db, owner.id, session.id, message.id, key="used", status="failed")
    db.commit()

    config = service.get_config(
        db, owner.id, now=datetime.now(SHANGHAI)
    )

    assert config == {
        "sizes": ["1024x1024", "1024x1536", "1536x1024"],
        "qualities": ["low", "medium", "high"],
        "default_size": "1024x1024",
        "default_quality": "medium",
        "max_reference_assets": 4,
        "daily_limit": 3,
        "used_today": 1,
        "remaining_today": 2,
    }


def test_usage_empty_and_unknown_cost_are_not_reported_as_zero(configured, db):
    owner, _ = configured
    empty = service.get_usage(db, owner_user_id=owner.id)
    assert empty["task_count"] == 0
    assert empty["success_rate"] is None
    assert empty["duration_ms"] == {"p50": None, "p95": None}
    assert empty["estimated_cost_microusd"] is None

    session = _session(db, owner.id)
    message = _message(db, session.id)
    _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="unknown-cost",
        status="failed",
        billing_certainty="unknown",
        error_code="provider_unavailable",
    )
    db.commit()
    usage = service.get_usage(db, owner_user_id=owner.id)
    assert usage["estimated_cost_microusd"] is None
    assert usage["unknown_cost_jobs"] == 1
    assert usage["error_categories"] == {"provider_unavailable": 1}


def test_usage_derives_percentiles_tokens_errors_and_snapshot_cost_from_jobs_and_logs(
    configured, db
):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    durations = [100, 200, 300, 400]
    for index, duration in enumerate(durations):
        log = AiCallLog(
            caller_module="design_image",
            caller_user_id=owner.id,
            preset_name="design_image_generation",
            provider_type="direct",
            model="gpt-image-2",
            status="success" if index < 3 else "error",
            duration_ms=duration,
            tokens_prompt=10,
            tokens_completion=20,
            tokens_used=30,
        )
        db.add(log)
        db.flush()
        _job(
            db,
            owner.id,
            session.id,
            message.id,
            key=f"usage-{index}",
            status="succeeded" if index < 3 else "failed",
            ai_call_log_id=log.id,
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
            error_code=None if index < 3 else "moderation_blocked",
            billing_certainty="certain",
            estimated_cost_microusd=100 + index,
            pricing_snapshot={"rate_card": "pilot-v1"},
        )
    db.commit()

    usage = service.get_usage(db, owner_user_id=owner.id)

    assert usage["task_count"] == 4
    assert usage["success_rate"] == 0.75
    assert usage["duration_ms"] == {"p50": 250, "p95": 385}
    assert usage["tokens"] == {"input": 40, "output": 80, "total": 120}
    assert usage["error_categories"] == {"moderation_blocked": 1}
    assert usage["estimated_cost_microusd"] == 406
    assert usage["unknown_cost_jobs"] == 0
    assert usage["by_status"] == {"failed": 1, "succeeded": 3}
    assert usage["by_date"] == [
        {"date": datetime.now(SHANGHAI).date().isoformat(), "task_count": 4}
    ]

    failed_only = service.get_usage(
        db, owner_user_id=owner.id, status="failed"
    )
    assert failed_only["task_count"] == 1
    with pytest.raises(service.DesignImageValidationError):
        service.get_usage(db, status="not-a-job-status")
