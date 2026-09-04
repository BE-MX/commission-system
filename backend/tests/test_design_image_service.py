from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.ai import service as ai_service
from app.auth.models import ArkUser
from app.core.time import beijing_now
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
        api_base="https://api.teamorouter.cn",
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


def _additional_model_preset(
    db,
    *,
    preset_name: str,
    model: str,
    parameters: dict | None = None,
    api_base: str = "https://api.teamorouter.cn",
) -> AiPreset:
    provider = db.query(AiProvider).filter_by(api_base=api_base).one_or_none()
    if provider is None:
        provider = AiProvider(
            name="Additional image provider", provider_type="direct",
            api_base=api_base, api_type="openai", api_key="encrypted",
            is_enabled=True, timeout_sec=30,
        )
        db.add(provider)
        db.flush()
    preset = AiPreset(
        preset_name=preset_name,
        provider_id=provider.id,
        model=model,
        parameters=parameters or {"output_format": "png"},
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
        created_at=created_at or beijing_now(),
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


def test_turn_schema_allows_catalog_model_and_forbids_controlled_preset_provider_and_bad_choices():
    assert _turn(model="grok-imagine-image-2.0").model == "grok-imagine-image-2.0"
    for field in ("mode", "preset", "provider"):
        with pytest.raises(PydanticValidationError):
            _turn(**{field: "client-controlled"})
    with pytest.raises(PydanticValidationError):
        _turn(model="client-controlled")
    with pytest.raises(PydanticValidationError):
        _turn(size="2048x2048")
    with pytest.raises(PydanticValidationError):
        _turn(quality="ultra")
    with pytest.raises(PydanticValidationError):
        _turn(reference_asset_ids=[1, 2, 3, 4, 5])
    with pytest.raises(PydanticValidationError):
        _turn(base_asset_id=1, reference_asset_ids=[1])


def test_turn_and_retry_snapshot_the_selected_openlux_model(configured, db):
    owner, _ = configured
    preset = _additional_model_preset(
        db,
        preset_name="design_image_generation_grok_image_2",
        model="grok-imagine-image-2.0",
        api_base="https://api.openlux.ai/v1",
    )
    db.commit()

    result = service.create_turn(
        db,
        owner.id,
        _turn(request_id="grok-turn", model="grok-imagine-image-2.0"),
    )
    job = result.jobs[0]
    assert job.model == "grok-imagine-image-2.0"
    assert job.preset_name == preset.preset_name

    job.status = "failed"
    db.commit()
    retried = service.retry_job(
        db,
        owner.id,
        job.id,
        RetryJobRequest(request_id="grok-retry"),
    )
    assert retried.jobs[0].model == "grok-imagine-image-2.0"
    assert retried.jobs[0].preset_name == preset.preset_name


def test_retry_legacy_null_model_falls_back_to_original_default(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    legacy = _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="legacy-null-model",
        status="failed",
    )
    legacy.model = None
    db.commit()

    retried = service.retry_job(
        db,
        owner.id,
        legacy.id,
        RetryJobRequest(request_id="retry-legacy-null-model"),
    )

    assert retried.jobs[0].model == "gpt-image-2"
    assert retried.jobs[0].preset_name == "design_image_generation"


def test_gemini_model_is_available_only_with_chat_style_teamrouter_preset(configured, db):
    owner, _ = configured
    preset = _additional_model_preset(
        db,
        preset_name="design_image_generation_nano_banana_pro",
        model="gemini-3-pro-image",
        parameters={"api_style": "chat", "max_tokens": 4096},
    )
    db.commit()

    models = {item["id"]: item for item in service.get_config(db, owner.id)["models"]}
    assert models["gemini-3-pro-image"]["available"] is True

    preset.parameters = {"output_format": "png"}
    db.commit()
    models = {item["id"]: item for item in service.get_config(db, owner.id)["models"]}
    assert models["gemini-3-pro-image"]["available"] is False
    with pytest.raises(service.DesignImageConfigurationError):
        service.create_turn(
            db,
            owner.id,
            _turn(request_id="bad-gemini-style", model="gemini-3-pro-image"),
        )


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

    assert second.jobs[0].id == first.jobs[0].id
    assert db.query(DesignImageJob).count() == 1
    assert db.query(DesignImageSession).filter_by(owner_user_id=owner.id).count() == 1
    assert db.query(DesignImageMessage).count() == 1


def test_create_turn_names_default_titled_session_from_first_message(configured, db):
    owner, _ = configured
    session = _session(db, owner.id, service.DEFAULT_SESSION_TITLE)
    db.commit()

    prompt = "  生成一张白底产品图\n柔和自然光   高级质感  超出长度限制的部分会被截断掉哦"
    result = service.create_turn(db, owner.id, _turn(session_id=session.id, prompt=prompt))

    collapsed = "生成一张白底产品图 柔和自然光 高级质感 超出长度限制的部分会被截断掉哦"
    expected = collapsed[: service.SESSION_TITLE_MAX_LENGTH]
    assert result.session.title == expected
    assert len(result.session.title) == service.SESSION_TITLE_MAX_LENGTH

    # 第二轮起不再改名
    result.jobs[0].status = "succeeded"
    db.flush()
    second = service.create_turn(
        db, owner.id, _turn(request_id="request-0002", session_id=session.id, prompt="换个新名字")
    )
    assert second.session.title == expected


def test_create_turn_keeps_explicit_title_and_titles_implicit_session(configured, db):
    owner, _ = configured
    named = _session(db, owner.id, "618 大促海报")
    db.commit()

    result = service.create_turn(db, owner.id, _turn(session_id=named.id, prompt="第一轮内容"))
    assert result.session.title == "618 大促海报"

    result.jobs[0].status = "succeeded"
    db.flush()
    implicit = service.create_turn(
        db, owner.id, _turn(request_id="request-0003", prompt="  隐式会话\n换行压平  ")
    )
    assert implicit.session.title == "隐式会话 换行压平"


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
        .filter_by(job_id=result.jobs[0].id)
        .order_by(DesignImageJobAsset.position)
        .all()
    )
    assert result.jobs[0].mode == "edit"
    assert result.jobs[0].base_asset_id == base.id
    assert [(link.asset_id, link.position) for link in links] == [
        (second_ref.id, 0),
        (first_ref.id, 1),
    ]
    assert second_ref.status == first_ref.status == "attached"
    assert second_ref.message_id == first_ref.message_id == result.message.id
    assert "当前基准图" in result.jobs[0].prompt_snapshot
    assert "把背景换成高端门店" in result.jobs[0].prompt_snapshot
    assert historical.content not in result.jobs[0].prompt_snapshot
    assert result.jobs[0].parameters == {
        "size": "1024x1536", "quality": "medium",
        "provider_id": db.query(AiPreset).filter_by(
            preset_name="design_image_generation"
        ).one().provider_id,
            "config_version": {
                "provider_id": db.query(AiProvider).one().id,
                "fingerprint": ai_service.build_image_config_version(
                    db.query(AiPreset).filter_by(
                        preset_name="design_image_generation"
                    ).one(),
                    db.query(AiProvider).one(),
                ),
            },
    }


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

    assert result.jobs[0].mode == "generate"
    assert result.jobs[0].base_asset_id is None


def test_create_turn_accepts_draft_base_and_promotes_it(configured, db):
    """图库克隆进会话的图是 draft，可直接作为基准图，随本轮使用转正。"""
    owner, _ = configured
    session = _session(db, owner.id)
    draft_base = _asset(db, owner.id, session.id)
    db.commit()

    result = service.create_turn(
        db,
        owner.id,
        _turn(request_id="draft-base", session_id=session.id, base_asset_id=draft_base.id),
    )

    assert result.jobs[0].mode == "edit"
    assert result.jobs[0].base_asset_id == draft_base.id
    assert draft_base.status == "attached"
    assert draft_base.message_id == result.message.id
    assert draft_base.expires_at is None


def test_create_turn_rejects_expired_draft_base(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    expired = _asset(db, owner.id, session.id)
    expired.expires_at = datetime(2026, 8, 4, 0, 0, 0)
    db.commit()

    with pytest.raises(service.DesignImageNotFoundError):
        service.create_turn(
            db,
            owner.id,
            _turn(request_id="expired-base", session_id=session.id, base_asset_id=expired.id),
            now=datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI),
        )
    assert db.query(DesignImageJob).count() == 0


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

    assert result.jobs[0].pricing_snapshot == preset.parameters["rate_card"]
    assert result.jobs[0].parameters["provider_id"] == preset.provider_id
    assert "api_key" not in result.jobs[0].parameters
    assert "api_base" not in result.jobs[0].parameters
    assert result.jobs[0].estimated_cost_microusd is None


def test_quota_uses_asia_shanghai_natural_day_and_counts_failed_accepted_jobs(
    configured, db, monkeypatch
):
    owner, _ = configured
    monkeypatch.setattr(service.get_settings(), "DESIGN_IMAGE_DAILY_LIMIT", 2)
    session = _session(db, owner.id)
    message = _message(db, session.id)
    # 业务 DATETIME 直接保存北京钟面，以 2026-08-05 00:00 为日切换点。
    _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="before-day",
        status="failed",
        created_at=datetime(2026, 8, 4, 23, 59, 59),
    )
    _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="today-failed",
        status="failed",
        created_at=datetime(2026, 8, 5, 0, 0, 0),
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
        service._idempotency_job_statement(
            owner.id, "request-key", for_update=True
        ),
        service._accepted_jobs_statement(
            owner.id, datetime(2026, 8, 5, 12, 0, tzinfo=SHANGHAI), for_update=True
        ),
        service._active_job_statement(owner.id, for_update=True),
        service._job_statement(owner.id, 123, for_update=True),
        service._asset_statement(owner.id, 456, for_update=True),
    )
    sql = [
        str(statement.compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )).upper()
        for statement in statements
    ]
    assert "ARK_USERS" in sql[0]
    assert "IDEMPOTENCY_KEY" in sql[1]
    assert "CREATED_AT" in sql[2]
    assert "STATUS" in sql[3]
    assert "ARK_DESIGN_IMAGE_JOBS" in sql[4]
    assert "ARK_DESIGN_IMAGE_ASSETS" in sql[5]
    assert all("FOR UPDATE" in statement for statement in sql)


def test_lock_wait_rechecks_idempotency_and_returns_queued_winner_before_capacity(
    configured, db, monkeypatch
):
    owner, _ = configured
    session = _session(db, owner.id, "winner")
    message = _message(db, session.id, "winner")
    message.client_request_id = "wait-winner"
    winner = _job(
        db, owner.id, session.id, message.id, key="wait-winner", status="queued"
    )
    reference = _asset(db, owner.id, session.id, status="attached")
    db.add(
        DesignImageJobAsset(
            job_id=winner.id, asset_id=reference.id, role="reference", position=0
        )
    )
    db.commit()
    original_find = service._find_request_message
    original_result = service._result_for_message
    original_rollback = db.rollback
    events = []

    def snapshot_miss_then_current_read(
        current_db, owner_id, session_id, key, *, for_update=False
    ):
        if not for_update:
            return None
        return original_find(
            current_db, owner_id, session_id, key, for_update=for_update
        )

    monkeypatch.setattr(
        service, "_find_request_message", snapshot_miss_then_current_read
    )
    monkeypatch.setattr(
        service,
        "_result_for_message",
        lambda *args, **kwargs: (
            events.append("result"), original_result(*args, **kwargs)
        )[1],
    )
    monkeypatch.setattr(
        db,
        "rollback",
        lambda: (events.append("rollback"), original_rollback())[1],
    )

    replay = service.create_turn(db, owner.id, _turn(request_id="wait-winner"))

    assert replay.jobs[0].id == winner.id
    assert db.query(DesignImageJob).count() == 1
    assert db.query(DesignImageSession).count() == 1
    assert db.query(DesignImageMessage).count() == 1
    assert [
        (link.asset_id, link.position)
        for link in db.query(DesignImageJobAsset).filter_by(job_id=replay.jobs[0].id)
    ] == [
        (reference.id, 0)
    ]
    assert events[:2] == ["rollback", "result"]


def test_retry_lock_wait_rechecks_idempotency_before_active_limit(
    configured, db, monkeypatch
):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    old = _job(db, owner.id, session.id, message.id, key="old-failed", status="failed")
    winner = _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="retry-wait-winner",
        status="queued",
        retry_of_job_id=old.id,
    )
    reference = _asset(db, owner.id, session.id, status="attached")
    db.add(
        DesignImageJobAsset(
            job_id=winner.id, asset_id=reference.id, role="reference", position=0
        )
    )
    db.commit()
    original_find = service._find_job_by_idempotency
    original_result = service._result_for_job
    original_rollback = db.rollback
    events = []

    def snapshot_miss_then_current_read(
        current_db, owner_id, key, *, for_update=False
    ):
        if not for_update:
            return None
        return original_find(
            current_db, owner_id, key, for_update=for_update
        )

    monkeypatch.setattr(
        service, "_find_job_by_idempotency", snapshot_miss_then_current_read
    )
    monkeypatch.setattr(
        service,
        "_result_for_job",
        lambda *args, **kwargs: (
            events.append("result"), original_result(*args, **kwargs)
        )[1],
    )
    monkeypatch.setattr(
        db,
        "rollback",
        lambda: (events.append("rollback"), original_rollback())[1],
    )

    replay = service.retry_job(
        db,
        owner.id,
        old.id,
        RetryJobRequest(request_id="retry-wait-winner"),
    )

    assert replay.jobs[0].id == winner.id
    assert db.query(DesignImageJob).count() == 2
    assert [
        (link.asset_id, link.position)
        for link in db.query(DesignImageJobAsset).filter_by(job_id=replay.jobs[0].id)
    ] == [
        (reference.id, 0)
    ]
    assert events[:2] == ["rollback", "result"]


def test_unique_key_race_rolls_back_every_write_and_returns_winner(
    configured, db, monkeypatch
):
    owner, _ = configured
    existing_session = _session(db, owner.id, "winner")
    existing_message = _message(db, existing_session.id, "winner")
    existing_message.client_request_id = "race-key"
    winner = _job(
        db,
        owner.id,
        existing_session.id,
        existing_message.id,
        key="race-key",
        status="succeeded",
    )
    db.commit()
    original_find = service._find_request_message
    calls = 0

    def miss_then_find(session, owner_id, session_id, key, *, for_update=False):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return None
        return original_find(
            session, owner_id, session_id, key, for_update=for_update
        )

    monkeypatch.setattr(service, "_find_request_message", miss_then_find)
    monkeypatch.setattr(
        db,
        "commit",
        lambda: (_ for _ in ()).throw(IntegrityError("insert", {}, Exception("race"))),
    )
    warnings = []
    prints = []
    monkeypatch.setattr(
        service.logger,
        "warning",
        lambda message, *args, **_kwargs: warnings.append(
            message % args if args else message
        ),
    )
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: prints.append((args, kwargs)),
    )

    replay = service.create_turn(db, owner.id, _turn(request_id="race-key"))

    assert replay.jobs[0].id == winner.id
    assert db.query(DesignImageJob).count() == 1
    assert db.query(DesignImageSession).count() == 1
    assert db.query(DesignImageMessage).count() == 1
    assert any("race recovered" in message for message in warnings)
    assert any(kwargs.get("flush") is True for _, kwargs in prints)


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

    assert result.jobs[0].id != old.id
    assert replay.jobs[0].id == result.jobs[0].id
    assert result.jobs[0].retry_of_job_id == old.id
    assert result.jobs[0].status == "queued"
    assert old.status == "failed"
    assert db.query(DesignImageJob).count() == 2
    assert [
        (x.asset_id, x.position)
        for x in db.query(DesignImageJobAsset).filter_by(job_id=result.jobs[0].id)
    ] == [
        (reference.id, 0)
    ]


def test_retry_validates_path_before_idempotency_replay(configured, db):
    owner, other = configured
    owner_session = _session(db, owner.id)
    owner_message = _message(db, owner_session.id)
    winner = _job(
        db,
        owner.id,
        owner_session.id,
        owner_message.id,
        key="existing-retry-key",
        status="failed",
    )
    foreign_session = _session(db, other.id)
    foreign_message = _message(db, foreign_session.id)
    foreign_job = _job(
        db,
        other.id,
        foreign_session.id,
        foreign_message.id,
        key="foreign-old",
        status="failed",
    )
    db.commit()

    for invalid_job_id in (foreign_job.id, 999_999):
        with pytest.raises(service.DesignImageNotFoundError):
            service.retry_job(
                db,
                owner.id,
                invalid_job_id,
                RetryJobRequest(request_id=winner.idempotency_key),
            )


@pytest.mark.parametrize("status", ["succeeded", "queued", "running"])
def test_retry_only_accepts_failed_jobs(configured, db, status):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    old = _job(db, owner.id, session.id, message.id, key=f"old-{status}", status=status)
    db.commit()

    with pytest.raises(service.DesignImageAssetConflictError, match="失败"):
        service.retry_job(
            db,
            owner.id,
            old.id,
            RetryJobRequest(request_id=f"retry-{status}"),
        )
    assert db.query(DesignImageJob).count() == 1


def test_retry_blocked_when_same_session_has_active_job(configured, db):
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


def test_concurrent_turns_allowed_up_to_per_user_cap(configured, db):
    """不同会话可同时各有一个进行中任务（默认上限 2），第三个被拦。"""
    owner, _ = configured
    sessions = [_session(db, owner.id, f"对话 {index}") for index in range(3)]
    db.commit()

    service.create_turn(db, owner.id, _turn(request_id="turn-1", session_id=sessions[0].id))
    service.create_turn(db, owner.id, _turn(request_id="turn-2", session_id=sessions[1].id))
    with pytest.raises(service.DesignImageActiveJobError, match="同时进行"):
        service.create_turn(
            db, owner.id, _turn(request_id="turn-3", session_id=sessions[2].id)
        )


def test_same_session_rejects_second_active_job(configured, db):
    """同一会话仍只允许一个进行中任务，其他会话不受影响。"""
    owner, _ = configured
    first = _session(db, owner.id, "对话 1")
    second = _session(db, owner.id, "对话 2")
    db.commit()

    service.create_turn(db, owner.id, _turn(request_id="turn-1", session_id=first.id))
    with pytest.raises(service.DesignImageActiveJobError, match="当前对话"):
        service.create_turn(db, owner.id, _turn(request_id="turn-1b", session_id=first.id))
    other = service.create_turn(db, owner.id, _turn(request_id="turn-2", session_id=second.id))
    assert other.jobs[0].session_id == second.id


def test_retry_allowed_when_active_job_is_in_another_session(configured, db):
    owner, _ = configured
    failed_session = _session(db, owner.id, "对话 1")
    failed_message = _message(db, failed_session.id)
    active_session = _session(db, owner.id, "对话 2")
    active_message = _message(db, active_session.id)
    failed = _job(db, owner.id, failed_session.id, failed_message.id, key="failed", status="failed")
    _job(db, owner.id, active_session.id, active_message.id, key="active", status="running")
    db.commit()

    result = service.retry_job(
        db, owner.id, failed.id, RetryJobRequest(request_id="retry-ok")
    )
    assert result.jobs[0].retry_of_job_id == failed.id


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
        parameters={"size": "1024x1024", "quality": "medium", "provider_id": -1},
    )
    preset = db.query(AiPreset).filter_by(preset_name="design_image_generation").one()
    preset.parameters = {"rate_card": {"name": "current"}}
    db.commit()

    retried = service.retry_job(
        db, owner.id, old.id, RetryJobRequest(request_id="current-rate")
    )
    assert retried.jobs[0].pricing_snapshot == {"name": "current"}
    assert retried.jobs[0].parameters["provider_id"] == preset.provider_id
    assert old.pricing_snapshot == {"name": "old"}

    retried.jobs[0].status = "failed"
    preset.is_enabled = False
    db.commit()
    with pytest.raises(service.DesignImageConfigurationError):
        service.retry_job(
            db, owner.id, old.id, RetryJobRequest(request_id="disabled-preset")
        )


def test_list_active_jobs_is_owner_scoped_and_ordered(configured, db):
    owner, other = configured
    session = _session(db, owner.id, "owner-active")
    message = _message(db, session.id)
    active = _job(db, owner.id, session.id, message.id, key="active-owner", status="queued")
    foreign_session = _session(db, other.id, "foreign-active")
    foreign_message = _message(db, foreign_session.id)
    _job(db, other.id, foreign_session.id, foreign_message.id, key="active-foreign", status="running")
    db.commit()

    rows = service.list_active_jobs(db, owner.id)

    assert [row.id for row in rows] == [active.id]
    assert rows[0].session_id == session.id


def test_success_updates_session_activity_but_idempotent_replay_does_not(configured, db):
    owner, _ = configured
    session = _session(db, owner.id, "target")
    session.updated_at = datetime(2026, 8, 1, 0, 0, 0)
    other = _session(db, owner.id, "other")
    other.updated_at = datetime(2026, 8, 2, 0, 0, 0)
    db.commit()
    turn_time = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
    payload = _turn(request_id="activity-turn", session_id=session.id)

    created = service.create_turn(db, owner.id, payload, now=turn_time)
    assert created.session.updated_at == datetime(2026, 8, 5, 9, 0, 0)
    page = service.list_sessions(db, owner.id, limit=1)
    assert [row.id for row in page.items] == [session.id]
    assert page.next_cursor is not None

    replay = service.create_turn(
        db,
        owner.id,
        payload,
        now=datetime(2026, 8, 6, 1, 0, tzinfo=timezone.utc),
    )
    assert replay.session.updated_at == datetime(2026, 8, 5, 9, 0, 0)
    second_page = service.list_sessions(db, owner.id, limit=1, cursor=page.next_cursor)
    assert [row.id for row in second_page.items] == [other.id]

    created.jobs[0].status = "failed"
    db.commit()
    retry = service.retry_job(
        db,
        owner.id,
            created.jobs[0].id,
        RetryJobRequest(request_id="activity-retry"),
        now=datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc),
    )
    assert retry.session.updated_at == datetime(2026, 8, 7, 9, 0, 0)
    retry_replay = service.retry_job(
        db,
        owner.id,
            created.jobs[0].id,
        RetryJobRequest(request_id="activity-retry"),
        now=datetime(2026, 8, 8, 1, 0, tzinfo=timezone.utc),
    )
    assert retry_replay.session.updated_at == datetime(2026, 8, 7, 9, 0, 0)


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


@pytest.mark.parametrize("failure_point", ["settings", "constructor"])
def test_draft_upload_compensates_any_failure_after_file_save(
    configured, db, monkeypatch, failure_point
):
    owner, _ = configured
    session = _session(db, owner.id)
    db.commit()
    stored = StoredImage(
        relative_path=f"{owner.id}/upload/compensate.png",
        thumbnail_relative_path=f"{owner.id}/upload/compensate_thumb.png",
        mime_type="image/png",
        file_size=10,
        width=10,
        height=10,
        sha256="c" * 64,
    )
    monkeypatch.setattr(
        service.file_service,
        "normalize_upload",
        lambda *_: SimpleNamespace(content=b"normalized"),
    )
    monkeypatch.setattr(
        service.file_service, "save_private_image", lambda *_args, **_kwargs: stored
    )
    deleted = []
    monkeypatch.setattr(service.file_service, "delete_private_file", deleted.append)
    rollback_calls = 0
    real_rollback = db.rollback

    def rollback_spy():
        nonlocal rollback_calls
        rollback_calls += 1
        return real_rollback()

    monkeypatch.setattr(db, "rollback", rollback_spy)

    def fail(message):
        raise RuntimeError(message)

    if failure_point == "settings":
        monkeypatch.setattr(service, "get_settings", lambda: fail("settings failed"))
    else:
        monkeypatch.setattr(
            service, "DesignImageAsset", lambda **_kwargs: fail("construct failed")
        )

    with pytest.raises(RuntimeError, match="failed"):
        service.create_draft_asset(db, owner.id, session.id, b"raw", "image/png")

    assert rollback_calls == 1
    assert deleted == [stored.relative_path, stored.thumbnail_relative_path]


def test_cleanup_failure_is_visible_in_logger_and_service_log(monkeypatch):
    warnings = []
    prints = []
    monkeypatch.setattr(
        service.file_service,
        "delete_private_file",
        lambda _path: (_ for _ in ()).throw(OSError("locked")),
    )
    monkeypatch.setattr(
        service.logger,
        "warning",
        lambda message, *args, **_kwargs: warnings.append(
            message % args if args else message
        ),
    )
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: prints.append((args, kwargs)),
    )

    service._delete_files_best_effort(["1/upload/a.png"], "test cleanup")

    assert any("cleanup failed" in message for message in warnings)
    assert any(kwargs.get("flush") is True for _, kwargs in prints)


def test_missing_winner_after_snapshot_refresh_raises_consistency_error(
    configured, db, monkeypatch
):
    owner, _ = configured
    warnings = []
    prints = []
    monkeypatch.setattr(
        service.logger,
        "warning",
        lambda message, *args, **_kwargs: warnings.append(
            message % args if args else message
        ),
    )
    monkeypatch.setattr(
        "builtins.print",
        lambda *args, **kwargs: prints.append((args, kwargs)),
    )

    with pytest.raises(service.DesignImageConsistencyError):
        service._reload_winner_result(db, owner.id, 999_999, context="turn")

    assert any("winner missing" in message for message in warnings)
    assert any(kwargs.get("flush") is True for _, kwargs in prints)


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


def test_delete_rechecks_references_after_owner_lock_before_soft_delete(
    configured, db, monkeypatch
):
    owner, _ = configured
    session = _session(db, owner.id)
    draft = _asset(db, owner.id, session.id, storage_path=f"{owner.id}/upload/race.png")
    message = _message(db, session.id)
    job = _job(db, owner.id, session.id, message.id, key="race-ref", status="failed")
    db.commit()
    original_lock = service._lock_active_owner
    deleted_files = []

    def lock_then_interleave(current_db, owner_id):
        locked = original_lock(current_db, owner_id)
        current_db.add(
            DesignImageJobAsset(
                job_id=job.id, asset_id=draft.id, role="reference", position=0
            )
        )
        current_db.flush()
        return locked

    monkeypatch.setattr(service, "_lock_active_owner", lock_then_interleave)
    monkeypatch.setattr(
        service.file_service, "delete_private_file", deleted_files.append
    )

    with pytest.raises(service.DesignImageAssetConflictError):
        service.delete_draft_asset(db, owner.id, draft.id)

    db.refresh(draft)
    assert draft.deleted_at is None
    assert deleted_files == []


def test_day_window_returns_beijing_naive_storage_boundaries():
    naive_utc = datetime(2026, 8, 4, 16, 0, 0)
    aware_utc = naive_utc.replace(tzinfo=timezone.utc)

    assert service._day_window(naive_utc) == service._day_window(aware_utc)
    assert service._day_window(naive_utc) == (
        datetime(2026, 8, 5, 0, 0, 0),
        datetime(2026, 8, 6, 0, 0, 0),
    )


def test_config_reports_verified_choices_limit_and_remaining(configured, db, monkeypatch):
    owner, _ = configured
    monkeypatch.setattr(service.get_settings(), "DESIGN_IMAGE_DAILY_LIMIT", 3)
    monkeypatch.setattr(service.get_settings(), "DESIGN_IMAGE_MAX_UPLOAD_MB", 2)
    session = _session(db, owner.id)
    message = _message(db, session.id)
    _job(db, owner.id, session.id, message.id, key="used", status="failed")
    db.commit()

    config = service.get_config(
        db, owner.id, now=datetime.now(SHANGHAI)
    )

    assert config == {
        "models": [
            {"id": "gpt-image-2", "label": "GPT Image 2", "available": True},
            {"id": "grok-imagine-image-2.0", "label": "Grok Image 2", "available": False},
            {"id": "gemini-3-pro-image", "label": "Nano Banana Pro", "available": False},
            {"id": "gemini-3.1-flash-image", "label": "Nano Banana 2", "available": False},
        ],
        "default_model": "gpt-image-2",
        "accepted_upload_mime_types": [
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/svg+xml",
            "application/pdf",
        ],
        "pdf_page_limit": 1,
        "sizes": ["1024x1024", "1024x1536", "1536x1024"],
        "qualities": ["low", "medium", "high"],
        "default_size": "1024x1024",
        "default_quality": "medium",
        "max_reference_assets": 4,
        "max_upload_bytes": 2 * 1024 * 1024,
        "draft_ttl_hours": 24,
        "daily_limit": 3,
        "used_today": 1,
        "remaining_today": 2,
        "max_active_per_user": 2,
    }


def test_usage_empty_and_unknown_cost_are_not_reported_as_zero(configured, db):
    owner, _ = configured
    empty = service.get_usage(db, owner_user_id=owner.id)
    assert empty["task_count"] == 0
    assert empty["success_rate"] is None
    assert empty["end_to_end_duration_ms"] == {"p50": None, "p95": None}
    assert empty["provider_duration_ms"] == {"p50": None, "p95": None}
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
    created_at = datetime(2026, 8, 5, 0, 0, 0)
    end_to_end_durations = [1000, 2000, 3000, 4000]
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
            created_at=created_at,
            finished_at=created_at + timedelta(milliseconds=end_to_end_durations[index]),
        )
    db.commit()

    usage = service.get_usage(db, owner_user_id=owner.id)

    assert usage["task_count"] == 4
    assert usage["success_rate"] == 0.75
    assert usage["end_to_end_duration_ms"] == {"p50": 2500, "p95": 3850}
    assert usage["provider_duration_ms"] == {"p50": 250, "p95": 385}
    assert usage["tokens"] == {"input": 40, "output": 80, "total": 120}
    assert usage["error_categories"] == {"moderation_blocked": 1}
    assert usage["estimated_cost_microusd"] == 406
    assert usage["unknown_cost_jobs"] == 0
    assert usage["by_status"] == {"failed": 1, "succeeded": 3}
    assert usage["by_date"] == [
        {
            "date": created_at.replace(tzinfo=timezone.utc)
            .astimezone(SHANGHAI)
            .date()
            .isoformat(),
            "task_count": 4,
        }
    ]

    failed_only = service.get_usage(
        db, owner_user_id=owner.id, status="failed"
    )
    assert failed_only["task_count"] == 1
    with pytest.raises(service.DesignImageValidationError):
        service.get_usage(db, status="not-a-job-status")


def test_usage_end_to_end_duration_includes_completed_job_without_ai_log(configured, db):
    owner, _ = configured
    session = _session(db, owner.id)
    message = _message(db, session.id)
    started = datetime(2026, 8, 5, 1, 0, 0)
    _job(
        db,
        owner.id,
        session.id,
        message.id,
        key="no-log-duration",
        status="succeeded",
        created_at=started,
        finished_at=started + timedelta(seconds=5),
    )
    db.commit()

    usage = service.get_usage(db, owner_user_id=owner.id)

    assert usage["end_to_end_duration_ms"] == {"p50": 5000, "p95": 5000}
    assert usage["provider_duration_ms"] == {"p50": None, "p95": None}


@pytest.mark.parametrize("has_base,reference_count", [(False, 4), (True, 3)])
@pytest.mark.parametrize("prompt", ["改成蓝色", "请生成三个角度的人像图"])
def test_grok_rejects_more_than_three_inputs_before_queueing(configured, db, has_base, reference_count, prompt):
    owner, _ = configured
    _additional_model_preset(db, preset_name="design_image_generation_grok_image_2",
                             model="grok-imagine-image-2.0", api_base="https://api.openlux.ai/v1")
    session = _session(db, owner.id)
    refs = [_asset(db, owner.id, session.id) for _ in range(reference_count)]
    base = _asset(db, owner.id, session.id) if has_base else None
    db.commit()
    with pytest.raises(service.DesignImageValidationError, match="3") as caught:
        service.create_turn(db, owner.id, _turn(
            model="grok-imagine-image-2.0", session_id=session.id, prompt=prompt,
            reference_asset_ids=[row.id for row in refs], base_asset_id=base.id if base else None,
        ))
    assert caught.value.code == "model_reference_limit"
    assert db.query(DesignImageJob).count() == 0
    assert db.query(DesignImageMessage).count() == 0


def test_grok_accepts_base_plus_two_references(configured, db):
    owner, _ = configured
    _additional_model_preset(db, preset_name="design_image_generation_grok_image_2",
                             model="grok-imagine-image-2.0", api_base="https://api.openlux.ai/v1")
    session = _session(db, owner.id)
    base = _asset(db, owner.id, session.id)
    refs = [_asset(db, owner.id, session.id) for _ in range(2)]
    db.commit()
    result = service.create_turn(db, owner.id, _turn(
        model="grok-imagine-image-2.0", session_id=session.id,
        reference_asset_ids=[row.id for row in refs], base_asset_id=base.id,
    ))
    assert result.jobs[0].model == "grok-imagine-image-2.0"
    assert result.jobs[0].base_asset_id == base.id
