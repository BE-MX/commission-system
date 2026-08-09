"""Atomic multi-output turn behavior."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import mysql

from app.ai.models import AiPreset, AiProvider
from app.auth.models import ArkUser
from app.design_image import service, worker
from app.design_image.models import (
    DesignImageAsset,
    DesignImageJob,
    DesignImageMessage,
    DesignImageSession,
)
from app.design_image.schemas import MessageActionRequest, TurnCreate


@pytest.fixture
def configured_owner(db):
    owner = ArkUser(
        username="multi-output-owner",
        password_hash="test",
        real_name="Multi Output Owner",
        is_active=True,
    )
    db.add(owner)
    db.flush()
    provider = AiProvider(
        name="Multi output provider",
        provider_type="direct",
        api_base="https://example.test",
        api_type="openai",
        api_key="encrypted",
        is_enabled=True,
        timeout_sec=30,
    )
    db.add(provider)
    db.flush()
    db.add(
        AiPreset(
            preset_name=service.PRESET_NAME,
            provider_id=provider.id,
            model=service.EXPECTED_MODEL,
            parameters={"output_format": "png"},
            is_enabled=True,
        )
    )
    session = DesignImageSession(
        owner_user_id=owner.id,
        title="multi output",
        status="active",
    )
    db.add(session)
    db.commit()
    return owner, session


def _turn(session_id: int, request_id: str, prompt: str) -> TurnCreate:
    return TurnCreate(
        session_id=session_id,
        request_id=request_id,
        prompt=prompt,
        size="1024x1024",
        quality="medium",
    )


def _draft(db, owner_id: int, session_id: int, *, suffix: str) -> DesignImageAsset:
    row = DesignImageAsset(
        session_id=session_id,
        asset_type="upload",
        storage_path=f"{owner_id}/upload/{suffix}.png",
        mime_type="image/png",
        file_size=10,
        width=10,
        height=10,
        sha256=sha256(suffix.encode()).hexdigest(),
        status="draft",
        expires_at=datetime(2026, 8, 10),
        created_by=owner_id,
    )
    db.add(row)
    db.flush()
    return row


def test_ambiguous_turn_persists_clarification_without_jobs(configured_owner, db):
    owner, session = configured_owner

    result = service.create_turn(
        db,
        owner.id,
        _turn(session.id, "ambiguous-1", "请生成3个角度的人像图"),
    )

    assert result.mode == "clarification"
    assert result.jobs == ()
    assert result.clarification.interaction_json["count"] == 3
    assert db.query(DesignImageJob).count() == 0
    assert db.query(DesignImageMessage).count() == 2


def test_explicit_separate_turn_creates_three_fixed_width_jobs(configured_owner, db):
    owner, session = configured_owner
    request_id = "r" * 64

    result = service.create_turn(
        db,
        owner.id,
        _turn(session.id, request_id, "分别生成3张：正面、左侧45度、右侧45度"),
    )

    assert result.mode == "jobs"
    assert len(result.jobs) == 3
    expected = [
        sha256(f"{session.id}:{request_id}:{position}".encode()).hexdigest()
        for position in range(1, 4)
    ]
    assert [job.idempotency_key for job in result.jobs] == expected
    assert all(job.request_message_id == result.message.id for job in result.jobs)
    assert all("仅生成这一张独立图片" in job.prompt_snapshot for job in result.jobs)


def test_explicit_composite_turn_creates_one_same_canvas_job(configured_owner, db):
    owner, session = configured_owner

    result = service.create_turn(
        db,
        owner.id,
        _turn(session.id, "composite-1", "把正面、左侧45度、右侧45度放在一张三视图里"),
    )

    assert result.mode == "jobs"
    assert len(result.jobs) == 1
    assert "同一张画布" in result.jobs[0].prompt_snapshot
    assert "正面" in result.jobs[0].prompt_snapshot
    assert "左侧 45°" in result.jobs[0].prompt_snapshot
    assert "右侧 45°" in result.jobs[0].prompt_snapshot


def test_same_request_id_in_two_sessions_derives_distinct_job_keys(configured_owner, db):
    owner, first_session = configured_owner
    second_session = DesignImageSession(
        owner_user_id=owner.id, title="second", status="active"
    )
    db.add(second_session)
    db.commit()

    first = service.create_turn(
        db, owner.id, _turn(first_session.id, "same-request", "生成一张人像图")
    )
    first.jobs[0].status = "succeeded"
    db.commit()
    second = service.create_turn(
        db, owner.id, _turn(second_session.id, "same-request", "生成一张人像图")
    )

    assert first.jobs[0].idempotency_key != second.jobs[0].idempotency_key


def test_more_than_four_rejects_without_messages_or_jobs(configured_owner, db):
    owner, session = configured_owner

    with pytest.raises(service.DesignImageValidationError) as exc:
        service.create_turn(
            db, owner.id, _turn(session.id, "too-many", "生成5个角度的人像图")
        )

    assert exc.value.code == "multi_output_limit"
    assert str(exc.value) == "一次最多生成 4 张，请拆成多轮请求。"
    assert exc.value.public_meta == {"max_outputs": 4}
    assert db.query(DesignImageMessage).count() == 0
    assert db.query(DesignImageJob).count() == 0


def test_full_batch_daily_capacity_is_checked_before_any_job(
    configured_owner, db, monkeypatch
):
    owner, session = configured_owner
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            DESIGN_IMAGE_DAILY_LIMIT=2,
            DESIGN_IMAGE_MAX_ACTIVE_PER_USER=2,
        ),
    )

    with pytest.raises(service.DesignImageQuotaExceededError) as exc:
        service.create_turn(
            db,
            owner.id,
            _turn(session.id, "quota-batch", "分别生成3张：正面、左侧45度、右侧45度"),
        )

    assert exc.value.public_meta == {"remaining": 2}
    assert db.query(DesignImageMessage).count() == 0
    assert db.query(DesignImageJob).count() == 0


def test_clarification_binds_draft_then_resolution_promotes_it(configured_owner, db):
    owner, session = configured_owner
    draft = _draft(db, owner.id, session.id, suffix="bound")
    db.commit()
    payload = _turn(session.id, "clarify-assets", "请生成3个角度的人像图")
    payload = payload.model_copy(update={"reference_asset_ids": [draft.id]})

    pending = service.create_turn(db, owner.id, payload)
    db.refresh(draft)
    assert draft.status == "draft"
    assert draft.message_id == pending.message.id
    assert draft.expires_at is not None
    with pytest.raises(service.DesignImageAssetConflictError):
        service.delete_draft_asset(db, owner.id, draft.id)

    resolved = service.resolve_message_action(
        db,
        owner.id,
        session.id,
        pending.clarification.id,
        MessageActionRequest(
            request_id="resolve-assets",
            action="choose_output_mode",
            mode="separate",
        ),
    )

    db.refresh(draft)
    assert resolved.mode == "jobs"
    assert len(resolved.jobs) == 3
    assert draft.status == "attached"
    assert draft.expires_at is None
    assert all(
        {
            link.asset_id
            for link in db.query(service.DesignImageJobAsset).filter_by(job_id=job.id)
        }
        == {draft.id}
        for job in resolved.jobs
    )


def test_resolve_action_is_idempotent_for_same_action_request(configured_owner, db):
    owner, session = configured_owner
    pending = service.create_turn(
        db, owner.id, _turn(session.id, "clarify-idem", "请生成2个角度的人像图")
    )
    action = MessageActionRequest(
        request_id="resolve-idem",
        action="choose_output_mode",
        mode="composite",
    )

    first = service.resolve_message_action(
        db, owner.id, session.id, pending.clarification.id, action
    )
    second = service.resolve_message_action(
        db, owner.id, session.id, pending.clarification.id, action
    )

    assert [job.id for job in second.jobs] == [job.id for job in first.jobs]
    assert db.query(DesignImageJob).count() == 1


def test_resolved_action_rejects_different_request_and_cross_owner(configured_owner, db):
    owner, session = configured_owner
    other = ArkUser(
        username="other-multi-owner",
        password_hash="test",
        real_name="Other Multi Owner",
        is_active=True,
    )
    db.add(other)
    db.commit()
    pending = service.create_turn(
        db, owner.id, _turn(session.id, "clarify-conflict", "请生成2个角度的人像图")
    )
    service.resolve_message_action(
        db,
        owner.id,
        session.id,
        pending.clarification.id,
        MessageActionRequest(
            request_id="first-resolution",
            action="choose_output_mode",
            mode="composite",
        ),
    )

    with pytest.raises(service.DesignImageAssetConflictError):
        service.resolve_message_action(
            db,
            owner.id,
            session.id,
            pending.clarification.id,
            MessageActionRequest(
                request_id="different-resolution",
                action="choose_output_mode",
                mode="composite",
            ),
        )
    with pytest.raises(service.DesignImageNotFoundError):
        service.resolve_message_action(
            db,
            other.id,
            session.id,
            pending.clarification.id,
            MessageActionRequest(
                request_id="cross-owner",
                action="choose_output_mode",
                mode="separate",
            ),
        )


def test_expired_bound_attachment_aborts_resolution_atomically(configured_owner, db):
    owner, session = configured_owner
    draft = _draft(db, owner.id, session.id, suffix="expired")
    db.commit()
    payload = _turn(session.id, "clarify-expired", "请生成2个角度的人像图")
    payload = payload.model_copy(update={"reference_asset_ids": [draft.id]})
    pending = service.create_turn(db, owner.id, payload)
    draft.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(service.DesignImageValidationError) as exc:
        service.resolve_message_action(
            db,
            owner.id,
            session.id,
            pending.clarification.id,
            MessageActionRequest(
                request_id="resolve-expired",
                action="choose_output_mode",
                mode="separate",
            ),
        )

    assert exc.value.code == "attachment_unavailable"
    assert str(exc.value) == "附件已失效，请重新上传后发送新请求。"
    assert db.query(DesignImageJob).count() == 0


def test_abandoned_clarification_draft_remains_eligible_for_expiry_cleanup(
    configured_owner, db, monkeypatch
):
    owner, session = configured_owner
    draft = _draft(db, owner.id, session.id, suffix="abandoned")
    db.commit()
    payload = _turn(session.id, "clarify-abandoned", "请生成2个角度的人像图")
    service.create_turn(
        db,
        owner.id,
        payload.model_copy(update={"reference_asset_ids": [draft.id]}),
    )
    cleanup_time = draft.expires_at + timedelta(seconds=1)
    monkeypatch.setattr(worker.file_service, "delete_private_file", lambda _path: None)

    assert worker.cleanup_expired_drafts(db, cleanup_time) == 1
    db.refresh(draft)
    assert draft.deleted_at == cleanup_time


def test_partial_batch_blocks_new_turn_until_every_root_job_is_terminal(
    configured_owner, db
):
    owner, batch_session = configured_owner
    next_session = DesignImageSession(
        owner_user_id=owner.id, title="next", status="active"
    )
    db.add(next_session)
    db.commit()
    batch = service.create_turn(
        db,
        owner.id,
        _turn(
            batch_session.id,
            "batch-four",
            "分别生成4张：正面、左侧45度、右侧45度、背面",
        ),
    )
    for job in batch.jobs[:3]:
        job.status = "succeeded"
    batch.jobs[3].status = "running"
    db.commit()

    with pytest.raises(service.DesignImageActiveJobError):
        service.create_turn(
            db,
            owner.id,
            _turn(next_session.id, "blocked-after-batch", "生成一张产品图"),
        )

    batch.jobs[3].status = "succeeded"
    db.commit()
    result = service.create_turn(
        db,
        owner.id,
        _turn(next_session.id, "allowed-after-batch", "生成一张产品图"),
    )
    assert len(result.jobs) == 1


def test_partial_batch_blocks_ambiguous_turn_without_new_rows_then_allows_it(
    configured_owner, db
):
    owner, batch_session = configured_owner
    clarification_session = DesignImageSession(
        owner_user_id=owner.id, title="clarification", status="active"
    )
    db.add(clarification_session)
    db.commit()
    batch = service.create_turn(
        db,
        owner.id,
        _turn(
            batch_session.id,
            "batch-before-clarify",
            "分别生成4张：正面、左侧45度、右侧45度、背面",
        ),
    )
    for job in batch.jobs[:3]:
        job.status = "succeeded"
    batch.jobs[3].status = "running"
    db.commit()
    messages_before = db.query(DesignImageMessage).count()
    jobs_before = db.query(DesignImageJob).count()

    with pytest.raises(service.DesignImageActiveJobError):
        service.create_turn(
            db,
            owner.id,
            _turn(
                clarification_session.id,
                "clarify-while-batch-active",
                "请生成3个角度的人像图",
            ),
        )

    assert db.query(DesignImageMessage).count() == messages_before
    assert db.query(DesignImageJob).count() == jobs_before
    batch.jobs[3].status = "succeeded"
    db.commit()
    result = service.create_turn(
        db,
        owner.id,
        _turn(
            clarification_session.id,
            "clarify-after-batch",
            "请生成3个角度的人像图",
        ),
    )
    assert result.mode == "clarification"
    assert result.jobs == ()


def test_active_retry_of_single_root_does_not_look_like_batch(configured_owner, db):
    owner, first_session = configured_owner
    next_session = DesignImageSession(
        owner_user_id=owner.id, title="next", status="active"
    )
    db.add(next_session)
    db.flush()
    message = DesignImageMessage(
        session_id=first_session.id, role="user", content="single", status="normal"
    )
    db.add(message)
    db.flush()
    root = DesignImageJob(
        owner_user_id=owner.id,
        session_id=first_session.id,
        request_message_id=message.id,
        mode="generate",
        status="failed",
        prompt_snapshot="single",
        parameters={"size": "1024x1024", "quality": "medium"},
        preset_name=service.PRESET_NAME,
        model=service.EXPECTED_MODEL,
        idempotency_key="single-root",
    )
    db.add(root)
    db.flush()
    retry = DesignImageJob(
        owner_user_id=owner.id,
        session_id=first_session.id,
        request_message_id=message.id,
        mode="generate",
        status="running",
        prompt_snapshot="single",
        parameters={"size": "1024x1024", "quality": "medium"},
        preset_name=service.PRESET_NAME,
        model=service.EXPECTED_MODEL,
        idempotency_key="single-retry",
        retry_of_job_id=root.id,
    )
    db.add(retry)
    db.commit()

    result = service.create_turn(
        db,
        owner.id,
        _turn(next_session.id, "not-a-batch", "生成一张产品图"),
    )

    assert len(result.jobs) == 1


def test_turn_and_action_lock_queries_compile_as_current_reads():
    request_sql = str(
        service._message_request_statement(
            7, 11, "request", for_update=True
        ).compile(dialect=mysql.dialect())
    ).upper()
    action_sql = str(
        service._message_action_statement(11, 22).compile(dialect=mysql.dialect())
    ).upper()

    assert "FOR UPDATE" in request_sql
    assert "ARK_DESIGN_IMAGE_MESSAGES.SESSION_ID = %S" in request_sql
    assert "FOR UPDATE" in action_sql
    assert "ARK_DESIGN_IMAGE_MESSAGES.ID = %S" in action_sql


def test_turn_replay_returns_only_root_jobs_after_single_job_retry(configured_owner, db):
    owner, session = configured_owner
    payload = _turn(session.id, "root-replay", "生成一张产品图")
    created = service.create_turn(db, owner.id, payload)
    created.jobs[0].status = "failed"
    db.commit()
    retry = service.retry_job(
        db,
        owner.id,
        created.jobs[0].id,
        service.RetryJobRequest(request_id="root-retry"),
    )

    replay = service.create_turn(db, owner.id, payload)

    assert [job.id for job in replay.jobs] == [created.jobs[0].id]
    assert retry.jobs[0].id not in [job.id for job in replay.jobs]
