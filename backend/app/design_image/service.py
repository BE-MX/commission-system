"""Owner-scoped Design Image Studio services.

The turn and retry writers use an ORM ``FOR UPDATE`` owner-row query. SQLite
unit tests verify the generated MySQL query and transaction outcomes, but cannot
prove InnoDB lock contention; that remains a Phase 5 MySQL integration gate.
Provider calls intentionally live outside this module and its transactions.
"""

from __future__ import annotations

import logging
import re
from hashlib import sha256
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import BinaryIO, Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, noload

from app.ai.models import AiCallLog
from app.ai.service import build_image_config_version
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.design_image import file_service
from app.design_image import model_catalog
from app.design_image.multi_output_intent import (
    MultiOutputIntent,
    build_composite_prompt,
    build_output_prompt,
    classify_multi_output_intent,
)
from app.design_image.models import (
    DesignImageAsset,
    DesignImageJob,
    DesignImageJobAsset,
    DesignImageMessage,
    DesignImageSession,
)
from app.design_image.schemas import (
    MAX_REFERENCE_ASSETS,
    VERIFIED_QUALITIES,
    VERIFIED_SIZES,
    RetryJobRequest,
    MessageActionRequest,
    OutputModeConfirmationInteraction,
    TurnCreate,
)


logger = logging.getLogger("commission")
SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
# Compatibility aliases retained for callers/tests that import the original default.
PRESET_NAME = model_catalog.IMAGE_MODEL_OPTIONS[0].preset_name
EXPECTED_MODEL = model_catalog.DEFAULT_IMAGE_MODEL_ID
ACTIVE_STATUSES = ("queued", "running")
JOB_STATUSES = ("queued", "running", "succeeded", "failed")
NOT_FOUND_MESSAGE = "资源不存在"
DEFAULT_SESSION_TITLE = "新对话"
# 会话名取自首条消息，压平空白后截断，避免撑爆侧栏
SESSION_TITLE_MAX_LENGTH = 30


class DesignImageError(ValueError):
    """Base error translated to an actionable HTTP response by the router."""


class DesignImageNotFoundError(DesignImageError):
    pass


class DesignImageValidationError(DesignImageError):
    code = "validation_error"
    public_meta: dict | None = None

    def __init__(self, message: str, *, code: str | None = None, public_meta: dict | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.public_meta = public_meta


class DesignImageConfigurationError(DesignImageError):
    pass


class DesignImageQuotaExceededError(DesignImageError):
    code = "daily_limit_exceeded"

    def __init__(self, message: str, *, remaining: int = 0):
        super().__init__(message)
        self.public_meta = {"remaining": max(remaining, 0)}


class DesignImageActiveJobError(DesignImageError):
    pass


class DesignImageAssetConflictError(DesignImageError):
    pass


class DesignImageConsistencyError(DesignImageError):
    pass


@dataclass(frozen=True)
class SessionPage:
    items: list[DesignImageSession]
    next_cursor: str | None


@dataclass(frozen=True)
class TurnResult:
    mode: Literal["jobs", "clarification"]
    session: DesignImageSession
    message: DesignImageMessage
    jobs: tuple[DesignImageJob, ...]
    clarification: DesignImageMessage | None = None


@dataclass(frozen=True)
class AssetContent:
    stream: BinaryIO
    mime_type: str
    suffix: str


def _not_found() -> DesignImageNotFoundError:
    return DesignImageNotFoundError(NOT_FOUND_MESSAGE)


def _warn_visible(message: str) -> None:
    logger.warning(message)
    print(f"[design-image] {message}", flush=True)


def _utc_naive(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _day_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    instant = now or datetime.now(SHANGHAI)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    local = instant.astimezone(SHANGHAI)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return _utc_naive(start_local), _utc_naive(end_local)


def _owner_lock_statement(owner_user_id: int):
    return (
        select(ArkUser)
        .options(noload(ArkUser.roles))
        .where(ArkUser.id == owner_user_id)
        .with_for_update()
    )


def _lock_active_owner(db: Session, owner_user_id: int) -> ArkUser:
    owner = db.execute(_owner_lock_statement(owner_user_id)).scalar_one_or_none()
    if owner is None or not owner.is_active or owner.deleted_at is not None:
        raise _not_found()
    return owner


def _idempotency_job_statement(
    owner_user_id: int, idempotency_key: str, *, for_update: bool = False
):
    statement = select(DesignImageJob).where(
            DesignImageJob.owner_user_id == owner_user_id,
            DesignImageJob.idempotency_key == idempotency_key,
        )
    return statement.with_for_update() if for_update else statement


def _job_statement(owner_user_id: int, job_id: int, *, for_update: bool = False):
    statement = select(DesignImageJob).where(
        DesignImageJob.id == job_id,
        DesignImageJob.owner_user_id == owner_user_id,
    )
    return statement.with_for_update() if for_update else statement


def _asset_statement(
    owner_user_id: int, asset_id: int, *, for_update: bool = False
):
    statement = select(DesignImageAsset).where(
        DesignImageAsset.id == asset_id,
        DesignImageAsset.created_by == owner_user_id,
    )
    return statement.with_for_update() if for_update else statement


def _find_job_by_idempotency(
    db: Session,
    owner_user_id: int,
    idempotency_key: str,
    *,
    for_update: bool = False,
) -> DesignImageJob | None:
    return db.execute(
        _idempotency_job_statement(
            owner_user_id, idempotency_key, for_update=for_update
        )
    ).scalar_one_or_none()


def _owner_session(
    db: Session,
    owner_user_id: int,
    session_id: int,
    *,
    for_update: bool = False,
) -> DesignImageSession:
    statement = select(DesignImageSession).where(
            DesignImageSession.id == session_id,
            DesignImageSession.owner_user_id == owner_user_id,
            DesignImageSession.status == "active",
        )
    if for_update:
        statement = statement.with_for_update()
    row = db.execute(statement).scalar_one_or_none()
    if row is None:
        raise _not_found()
    return row


def _session_title_from_prompt(prompt: str) -> str:
    """首条消息内容作为会话名：压平换行/连续空白，截断，空串回退默认名。"""
    collapsed = re.sub(r"\s+", " ", prompt or "").strip()
    return collapsed[:SESSION_TITLE_MAX_LENGTH] or DEFAULT_SESSION_TITLE


def _session_has_messages(db: Session, session_id: int) -> bool:
    return (
        db.query(DesignImageMessage.id)
        .filter(DesignImageMessage.session_id == session_id)
        .limit(1)
        .first()
        is not None
    )


def create_session(
    db: Session, owner_user_id: int, title: str = DEFAULT_SESSION_TITLE
) -> DesignImageSession:
    _lock_active_owner(db, owner_user_id)
    normalized = (title or DEFAULT_SESSION_TITLE).strip()[:200] or DEFAULT_SESSION_TITLE
    row = DesignImageSession(
        owner_user_id=owner_user_id, title=normalized, status="active"
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return row


def _encode_cursor(row: DesignImageSession) -> str:
    return f"{row.updated_at.isoformat()}|{row.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw_time, raw_id = cursor.rsplit("|", 1)
        return datetime.fromisoformat(raw_time), int(raw_id)
    except (AttributeError, TypeError, ValueError):
        raise DesignImageValidationError("会话游标无效") from None


def list_sessions(
    db: Session,
    owner_user_id: int,
    *,
    limit: int = 20,
    cursor: str | None = None,
) -> SessionPage:
    if limit < 1 or limit > 100:
        raise DesignImageValidationError("分页数量必须在 1 到 100 之间")
    query = db.query(DesignImageSession).filter(
        DesignImageSession.owner_user_id == owner_user_id
    )
    if cursor:
        cursor_time, cursor_id = _decode_cursor(cursor)
        query = query.filter(
            or_(
                DesignImageSession.updated_at < cursor_time,
                and_(
                    DesignImageSession.updated_at == cursor_time,
                    DesignImageSession.id < cursor_id,
                ),
            )
        )
    rows = (
        query.order_by(
            DesignImageSession.updated_at.desc(), DesignImageSession.id.desc()
        )
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    return SessionPage(
        items=items,
        next_cursor=_encode_cursor(items[-1]) if has_more else None,
    )


def get_session_detail(
    db: Session,
    owner_user_id: int,
    session_id: int,
    *,
    now: datetime | None = None,
) -> dict:
    session = _owner_session(db, owner_user_id, session_id)
    messages = (
        db.query(DesignImageMessage)
        .filter(DesignImageMessage.session_id == session.id)
        .order_by(DesignImageMessage.created_at, DesignImageMessage.id)
        .all()
    )
    assets = (
        db.query(DesignImageAsset)
        .filter(
            DesignImageAsset.session_id == session.id,
            DesignImageAsset.created_by == owner_user_id,
            DesignImageAsset.deleted_at.is_(None),
            or_(
                DesignImageAsset.status != "draft",
                DesignImageAsset.expires_at.is_(None),
                DesignImageAsset.expires_at > _utc_naive(now),
            ),
        )
        .order_by(DesignImageAsset.created_at, DesignImageAsset.id)
        .all()
    )
    jobs = (
        db.query(DesignImageJob)
        .filter(
            DesignImageJob.session_id == session.id,
            DesignImageJob.owner_user_id == owner_user_id,
        )
        .order_by(DesignImageJob.created_at, DesignImageJob.id)
        .all()
    )
    return {"session": session, "messages": messages, "assets": assets, "jobs": jobs}


def get_asset(db: Session, owner_user_id: int, asset_id: int) -> DesignImageAsset:
    row = (
        db.query(DesignImageAsset)
        .filter(
            DesignImageAsset.id == asset_id,
            DesignImageAsset.created_by == owner_user_id,
            DesignImageAsset.deleted_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise _not_found()
    return row


def open_asset_content(
    db: Session,
    owner_user_id: int,
    asset_id: int,
    *,
    thumbnail: bool = False,
) -> AssetContent:
    """Authorize, validate, then atomically open a private asset for streaming."""
    asset = get_asset(db, owner_user_id, asset_id)
    relative_path = _thumbnail_path(asset.storage_path) if thumbnail else asset.storage_path
    try:
        path = file_service.resolve_private_path(relative_path)
    except file_service.ImageStorageError as exc:
        raise DesignImageConsistencyError("图片存储暂不可用，请稍后重试") from exc
    suffix_by_mime = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    suffix = suffix_by_mime.get(asset.mime_type)
    if suffix is None:
        raise DesignImageConsistencyError("图片格式记录异常，请联系管理员")
    try:
        stream = path.open("rb")
    except (FileNotFoundError, IsADirectoryError):
        raise _not_found() from None
    except OSError as exc:
        raise DesignImageConsistencyError("图片存储暂不可用，请稍后重试") from exc
    return AssetContent(stream=stream, mime_type=asset.mime_type, suffix=suffix)


def get_job(db: Session, owner_user_id: int, job_id: int) -> DesignImageJob:
    row = db.execute(_job_statement(owner_user_id, job_id)).scalar_one_or_none()
    if row is None:
        raise _not_found()
    return row


def list_active_jobs(db: Session, owner_user_id: int) -> list[DesignImageJob]:
    return (
        db.query(DesignImageJob)
        .filter(
            DesignImageJob.owner_user_id == owner_user_id,
            DesignImageJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(DesignImageJob.created_at.desc(), DesignImageJob.id.desc())
        .all()
    )


def _delete_files_best_effort(paths: list[str], context: str) -> None:
    for path in paths:
        try:
            file_service.delete_private_file(path)
        except Exception as exc:
            message = f"{context} cleanup failed {PurePosixPath(path).name}: {exc}"
            _warn_visible(message)


def _thumbnail_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    return str(path.with_name(f"{path.stem}_thumb{path.suffix}"))


def create_draft_asset(
    db: Session,
    owner_user_id: int,
    session_id: int,
    content: bytes,
    declared_mime: str,
    *,
    now: datetime | None = None,
) -> DesignImageAsset:
    _owner_session(db, owner_user_id, session_id)
    normalized = file_service.normalize_upload(content, declared_mime)
    stored = file_service.save_private_image(
        normalized, owner_user_id=owner_user_id, kind="upload"
    )
    try:
        row = DesignImageAsset(
            session_id=session_id,
            asset_type="upload",
            storage_path=stored.relative_path,
            mime_type=stored.mime_type,
            file_size=stored.file_size,
            width=stored.width,
            height=stored.height,
            sha256=stored.sha256,
            status="draft",
            expires_at=_utc_naive(now) + timedelta(
                hours=get_settings().DESIGN_IMAGE_DRAFT_TTL_HOURS
            ),
            created_by=owner_user_id,
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        _delete_files_best_effort(
            [stored.relative_path, stored.thumbnail_relative_path], "draft database rollback"
        )
        raise
    db.refresh(row)
    return row


def delete_draft_asset(db: Session, owner_user_id: int, asset_id: int) -> None:
    try:
        _lock_active_owner(db, owner_user_id)
        asset = db.execute(
            _asset_statement(owner_user_id, asset_id, for_update=True).where(
                DesignImageAsset.deleted_at.is_(None)
            )
        ).scalar_one_or_none()
        if asset is None:
            raise _not_found()
        referenced = db.execute(
            select(DesignImageJobAsset.id)
            .where(DesignImageJobAsset.asset_id == asset.id)
            .with_for_update()
        ).first()
        based_on = db.execute(
            select(DesignImageJob.id)
            .where(DesignImageJob.base_asset_id == asset.id)
            .with_for_update()
        ).first()
        if (
            asset.status != "draft"
            or asset.message_id is not None
            or referenced is not None
            or based_on is not None
        ):
            raise DesignImageAssetConflictError("图片已被任务引用，不能删除")
        asset.deleted_at = _utc_naive()
        db.commit()
    except Exception:
        db.rollback()
        raise
    _delete_files_best_effort(
        [asset.storage_path, _thumbnail_path(asset.storage_path)], "draft delete"
    )


def _accepted_jobs_statement(
    owner_user_id: int,
    now: datetime | None = None,
    *,
    for_update: bool = False,
):
    start, end = _day_window(now)
    statement = select(DesignImageJob.id).where(
            DesignImageJob.owner_user_id == owner_user_id,
            DesignImageJob.created_at >= start,
            DesignImageJob.created_at < end,
        )
    return statement.with_for_update() if for_update else statement


def _active_job_statement(owner_user_id: int, *, for_update: bool = False):
    statement = (
        select(DesignImageJob.id)
        .where(
            DesignImageJob.owner_user_id == owner_user_id,
            DesignImageJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(DesignImageJob.created_at.desc(), DesignImageJob.id.desc())
    )
    return statement.with_for_update() if for_update else statement


def _session_active_job_statement(session_id: int, *, for_update: bool = False):
    statement = (
        select(DesignImageJob.id)
        .where(
            DesignImageJob.session_id == session_id,
            DesignImageJob.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    return statement.with_for_update() if for_update else statement


def _message_request_statement(
    owner_user_id: int,
    session_id: int | None,
    request_id: str,
    *,
    for_update: bool = False,
):
    statement = (
        select(DesignImageMessage)
        .join(DesignImageSession, DesignImageSession.id == DesignImageMessage.session_id)
        .where(
            DesignImageSession.owner_user_id == owner_user_id,
            DesignImageMessage.client_request_id == request_id,
        )
    )
    if session_id is not None:
        statement = statement.where(DesignImageMessage.session_id == session_id)
    else:
        statement = statement.order_by(DesignImageMessage.id.desc()).limit(1)
    return statement.with_for_update() if for_update else statement


def _find_request_message(
    db: Session,
    owner_user_id: int,
    session_id: int | None,
    request_id: str,
    *,
    for_update: bool = False,
) -> DesignImageMessage | None:
    return db.execute(
        _message_request_statement(
            owner_user_id,
            session_id,
            request_id,
            for_update=for_update,
        )
    ).scalar_one_or_none()


def _message_action_statement(session_id: int, message_id: int):
    return (
        select(DesignImageMessage)
        .where(
            DesignImageMessage.id == message_id,
            DesignImageMessage.session_id == session_id,
            DesignImageMessage.role == "assistant",
        )
        .with_for_update()
    )


def _accepted_count(
    db: Session,
    owner_user_id: int,
    now: datetime | None = None,
    *,
    for_update: bool = False,
) -> int:
    rows = db.execute(
        _accepted_jobs_statement(owner_user_id, now, for_update=for_update)
    ).scalars().all()
    return len(rows)


def _has_active_multi_job_batch(db: Session, owner_user_id: int) -> bool:
    active_message_ids = db.execute(
        select(DesignImageJob.request_message_id)
        .where(
            DesignImageJob.owner_user_id == owner_user_id,
            DesignImageJob.status.in_(ACTIVE_STATUSES),
        )
        .with_for_update()
    ).scalars().all()
    for message_id in set(active_message_ids):
        root_ids = db.execute(
            select(DesignImageJob.id)
            .where(
                DesignImageJob.owner_user_id == owner_user_id,
                DesignImageJob.request_message_id == message_id,
                DesignImageJob.retry_of_job_id.is_(None),
            )
            .with_for_update()
        ).scalars().all()
        if len(root_ids) > 1:
            return True
    return False


def _enforce_capacity(
    db: Session,
    owner_user_id: int,
    now: datetime | None,
    session_id: int | None = None,
    *,
    required: int = 1,
    require_owner_idle: bool = False,
) -> None:
    # Both reads are locking/current reads. Under MySQL REPEATABLE READ, the
    # earlier idempotency lookup may have established an old consistent-read
    # snapshot; ordinary SELECTs here would miss a job committed while this
    # transaction waited for the owner row lock.
    used = _accepted_count(db, owner_user_id, now, for_update=True)
    daily_limit = get_settings().DESIGN_IMAGE_DAILY_LIMIT
    remaining = max(daily_limit - used, 0)
    if required > remaining:
        raise DesignImageQuotaExceededError(
            "今日生成额度不足，请减少张数或联系管理员",
            remaining=remaining,
        )
    max_active = get_settings().DESIGN_IMAGE_MAX_ACTIVE_PER_USER
    active_ids = db.execute(
        _active_job_statement(owner_user_id, for_update=True)
    ).scalars().all()
    if require_owner_idle and active_ids:
        raise DesignImageActiveJobError("当前已有任务进行中，请等待完成后再确认")
    if not require_owner_idle and _has_active_multi_job_batch(db, owner_user_id):
        raise DesignImageActiveJobError("当前批量任务尚未全部完成，请稍后再发送")
    if not require_owner_idle and len(active_ids) >= max_active:
        raise DesignImageActiveJobError(
            f"当前已有 {max_active} 个任务同时进行，请等待任一完成后再发送"
        )
    # 会话级仍限单个进行中任务，保住会话内单活跃卡片的交互模型
    if session_id is not None and db.execute(
        _session_active_job_statement(session_id, for_update=True)
    ).scalar_one_or_none() is not None:
        raise DesignImageActiveJobError("当前对话已有任务进行中，请等待完成")


def _enforce_clarification_guard(
    db: Session, owner_user_id: int, session_id: int
) -> None:
    if _has_active_multi_job_batch(db, owner_user_id):
        raise DesignImageActiveJobError("当前批量任务尚未全部完成，请稍后再发送")
    if db.execute(
        _session_active_job_statement(session_id, for_update=True)
    ).scalar_one_or_none() is not None:
        raise DesignImageActiveJobError("当前对话已有任务进行中，请等待完成")


def _preset_snapshot(
    db: Session,
    model_id: str = model_catalog.DEFAULT_IMAGE_MODEL_ID,
) -> tuple[str, str, int, dict | None, dict]:
    configured = model_catalog.configured_model_row(db, model_id)
    if configured is None:
        raise DesignImageConfigurationError("生图服务配置不可用，请联系管理员")
    _option, preset, provider = configured
    rate_card = (preset.parameters or {}).get("rate_card")
    if rate_card is not None and not isinstance(rate_card, dict):
        raise DesignImageConfigurationError("生图价格配置不可用，请联系管理员")
    config_version = {
        "provider_id": provider.id,
        "fingerprint": build_image_config_version(preset, provider),
    }
    return (
        preset.preset_name, preset.model, preset.provider_id,
        deepcopy(rate_card), config_version,
    )


def _usable_asset(
    db: Session,
    owner_user_id: int,
    session_id: int,
    asset_id: int,
    *,
    allow_draft: bool,
    now: datetime | None,
) -> DesignImageAsset:
    statuses = ("attached", "draft") if allow_draft else ("attached",)
    statement = _asset_statement(
        owner_user_id, asset_id, for_update=True
    ).where(
        DesignImageAsset.session_id == session_id,
        DesignImageAsset.deleted_at.is_(None),
        DesignImageAsset.status.in_(statuses),
    )
    if allow_draft:
        statement = statement.where(
            or_(
                DesignImageAsset.status == "attached",
                DesignImageAsset.expires_at.is_(None),
                DesignImageAsset.expires_at > _utc_naive(now),
            )
        )
    row = db.execute(statement).scalar_one_or_none()
    if row is None:
        raise _not_found()
    return row


def _prompt_snapshot(prompt: str, *, editing: bool) -> str:
    lines = []
    if editing:
        lines.append("当前基准图：仅修改本轮明确要求的部分。")
    lines.extend((f"本轮用户要求：{prompt}", "保持未提及部分不变。"))
    return "\n".join(lines)


def _result_for_message(db: Session, message: DesignImageMessage) -> TurnResult:
    session = db.query(DesignImageSession).filter_by(id=message.session_id).one()
    jobs = tuple(
        db.query(DesignImageJob)
        .filter_by(request_message_id=message.id, retry_of_job_id=None)
        .order_by(DesignImageJob.id)
        .all()
    )
    clarification = (
        db.query(DesignImageMessage)
        .filter(
            DesignImageMessage.session_id == message.session_id,
            DesignImageMessage.role == "assistant",
            DesignImageMessage.interaction_json.is_not(None),
        )
        .order_by(DesignImageMessage.id.desc())
        .all()
    )
    matching = None
    for row in clarification:
        raw = row.interaction_json
        if not isinstance(raw, dict) or raw.get("source_message_id") != message.id:
            continue
        try:
            OutputModeConfirmationInteraction.model_validate(raw)
        except ValidationError:
            logger.warning(
                "invalid stored design image confirmation message_id=%s",
                row.id,
            )
            raise DesignImageConsistencyError(
                "确认状态异常，请刷新页面后重新发送请求。"
            ) from None
        matching = row
        break
    if not jobs and matching is None:
        raise DesignImageConsistencyError(
            "确认状态异常，请刷新页面后重新发送请求。"
        )
    return TurnResult(
        mode="jobs" if jobs else "clarification",
        session=session,
        message=message,
        jobs=jobs,
        clarification=matching,
    )


def _result_for_job(db: Session, job: DesignImageJob) -> TurnResult:
    message = db.query(DesignImageMessage).filter_by(id=job.request_message_id).one()
    result = _result_for_message(db, message)
    return TurnResult(
        mode="jobs",
        session=result.session,
        message=result.message,
        jobs=(job,),
    )


def _job_key(session_id: int, request_id: str, position: int) -> str:
    return sha256(f"{session_id}:{request_id}:{position}".encode("utf-8")).hexdigest()


def _attach_assets_to_message(
    message: DesignImageMessage,
    base: DesignImageAsset | None,
    references: list[DesignImageAsset],
    *,
    promote: bool,
) -> None:
    for asset in ([base] if base is not None else []) + references:
        if asset.status == "draft":
            asset.message_id = message.id
            if promote:
                asset.status = "attached"
                asset.expires_at = None


def _create_jobs_for_intent(
    db: Session,
    owner_user_id: int,
    session: DesignImageSession,
    message: DesignImageMessage,
    payload: TurnCreate,
    intent: MultiOutputIntent,
    base: DesignImageAsset | None,
    references: list[DesignImageAsset],
    *,
    operation_time: datetime,
) -> tuple[DesignImageJob, ...]:
    preset_name, model, provider_id, pricing_snapshot, config_version = _preset_snapshot(
        db, payload.model
    )
    labels: tuple[str | None, ...] = intent.labels if intent.mode == "separate" else (None,)
    rows: list[DesignImageJob] = []
    for position, label in enumerate(labels, start=1):
        if label is not None:
            effective_prompt = build_output_prompt(payload.prompt, label)
        elif intent.mode == "composite":
            effective_prompt = build_composite_prompt(payload.prompt, intent.labels)
        else:
            effective_prompt = payload.prompt
        job = DesignImageJob(
            owner_user_id=owner_user_id,
            session_id=session.id,
            request_message_id=message.id,
            base_asset_id=base.id if base else None,
            mode="edit" if base else "generate",
            status="queued",
            prompt_snapshot=_prompt_snapshot(effective_prompt, editing=base is not None),
            parameters={
                "size": payload.size,
                "quality": payload.quality,
                "provider_id": provider_id,
                "config_version": config_version,
            },
            preset_name=preset_name,
            model=model,
            idempotency_key=_job_key(session.id, payload.request_id, position),
            pricing_snapshot=pricing_snapshot,
            created_at=operation_time,
        )
        db.add(job)
        db.flush()
        for reference_position, asset in enumerate(references):
            db.add(
                DesignImageJobAsset(
                    job_id=job.id,
                    asset_id=asset.id,
                    role="reference",
                    position=reference_position,
                )
            )
        rows.append(job)
    _attach_assets_to_message(message, base, references, promote=True)
    return tuple(rows)


def _reload_winner_result(
    db: Session, owner_user_id: int, winner_id: int, *, context: str
) -> TurnResult:
    winner = db.execute(
        _job_statement(owner_user_id, winner_id)
    ).scalar_one_or_none()
    if winner is None:
        _warn_visible(f"{context} idempotency winner missing after snapshot refresh")
        raise DesignImageConsistencyError("幂等任务结果暂不可见，请重试")
    return _result_for_job(db, winner)


def _rollback_and_reload_winner(
    db: Session, owner_user_id: int, winner_id: int, *, context: str
) -> TurnResult:
    db.rollback()
    return _reload_winner_result(
        db, owner_user_id, winner_id, context=context
    )


def create_turn(
    db: Session,
    owner_user_id: int,
    payload: TurnCreate,
    *,
    now: datetime | None = None,
) -> TurnResult:
    existing_message = _find_request_message(
        db, owner_user_id, payload.session_id, payload.request_id
    )
    if existing_message is not None:
        return _result_for_message(db, existing_message)
    try:
        _lock_active_owner(db, owner_user_id)
        if payload.session_id is None:
            winner_message = _find_request_message(
                db,
                owner_user_id,
                None,
                payload.request_id,
                for_update=True,
            )
            if winner_message is not None:
                db.rollback()
                return _result_for_message(db, winner_message)
        session = (
            _owner_session(
                db, owner_user_id, payload.session_id, for_update=True
            )
            if payload.session_id is not None
            else None
        )
        operation_time = _utc_naive(now)
        if session is None:
            session = DesignImageSession(
                owner_user_id=owner_user_id,
                title=_session_title_from_prompt(payload.prompt),
                status="active",
                created_at=operation_time,
                updated_at=operation_time,
            )
            db.add(session)
            db.flush()
        else:
            session.updated_at = operation_time
            # 首轮消息自动命名：仅当仍是默认名（没显式起过名）且会话还没有任何消息
            if session.title == DEFAULT_SESSION_TITLE and not _session_has_messages(db, session.id):
                session.title = _session_title_from_prompt(payload.prompt)
        if payload.session_id is not None:
            winner_message = _find_request_message(
                db,
                owner_user_id,
                session.id,
                payload.request_id,
                for_update=True,
            )
            if winner_message is not None:
                db.rollback()
                return _result_for_message(db, winner_message)
        intent = classify_multi_output_intent(payload.prompt)
        if intent.mode == "reject":
            raise DesignImageValidationError(
                "一次最多生成 4 张，请拆成多轮请求。",
                code="multi_output_limit",
                public_meta={"max_outputs": 4},
            )
        if intent.mode == "clarify":
            _enforce_clarification_guard(db, owner_user_id, session.id)
        base = (
            _usable_asset(
                db, owner_user_id, session.id, payload.base_asset_id,
                # 允许草稿基准图：图库克隆进会话的图就是 draft，使用后即刻转正（见下方提升逻辑）
                allow_draft=True, now=now,
            )
            if payload.base_asset_id is not None
            else None
        )
        references = [
            _usable_asset(
                db, owner_user_id, session.id, asset_id,
                allow_draft=True, now=now,
            )
            for asset_id in payload.reference_asset_ids
        ]
        message = DesignImageMessage(
            session_id=session.id,
            role="user",
            content=payload.prompt,
            status="normal",
            client_request_id=payload.request_id,
        )
        db.add(message)
        db.flush()
        if intent.mode == "clarify":
            _attach_assets_to_message(message, base, references, promote=False)
            clarification = DesignImageMessage(
                session_id=session.id,
                role="assistant",
                content="请选择生成方式",
                status="normal",
                interaction_json={
                    "type": "output_mode_confirmation",
                    "status": "pending",
                    "source_message_id": message.id,
                    "request_id": payload.request_id,
                    "count": intent.count,
                    "item_kind": intent.item_kind,
                    "labels": list(intent.labels),
                    "request": {
                        "base_asset_id": payload.base_asset_id,
                        "reference_asset_ids": list(payload.reference_asset_ids),
                        "model": payload.model,
                        "size": payload.size,
                        "quality": payload.quality,
                    },
                    "selected_mode": None,
                    "resolved_at": None,
                },
                created_at=operation_time,
            )
            db.add(clarification)
            db.commit()
            return _result_for_message(db, message)
        required = intent.count if intent.mode == "separate" else 1
        _enforce_capacity(
            db,
            owner_user_id,
            now,
            session_id=session.id,
            required=required,
            require_owner_idle=intent.mode == "separate",
        )
        jobs = _create_jobs_for_intent(
            db,
            owner_user_id,
            session,
            message,
            payload,
            intent,
            base,
            references,
            operation_time=operation_time,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        winner_message = _find_request_message(
            db, owner_user_id, payload.session_id, payload.request_id
        )
        if winner_message is None:
            _warn_visible("design image turn integrity error without idempotent winner")
            raise
        _warn_visible("design image turn idempotency race recovered")
        return _result_for_message(db, winner_message)
    except Exception:
        db.rollback()
        raise
    return TurnResult(
        mode="jobs",
        session=session,
        message=message,
        jobs=jobs,
    )


def resolve_message_action(
    db: Session,
    owner_user_id: int,
    session_id: int,
    message_id: int,
    payload: MessageActionRequest,
    *,
    now: datetime | None = None,
) -> TurnResult:
    try:
        _lock_active_owner(db, owner_user_id)
        session = _owner_session(db, owner_user_id, session_id, for_update=True)
        clarification = db.execute(
            _message_action_statement(session.id, message_id)
        ).scalar_one_or_none()
        if clarification is None:
            raise _not_found()
        try:
            interaction = OutputModeConfirmationInteraction.model_validate(
                clarification.interaction_json
            )
        except Exception as exc:
            raise DesignImageAssetConflictError("该确认请求已失效，请重新发送") from exc
        source = db.execute(
            select(DesignImageMessage)
            .where(
                DesignImageMessage.id == interaction.source_message_id,
                DesignImageMessage.session_id == session.id,
                DesignImageMessage.role == "user",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if source is None:
            raise _not_found()
        stored = dict(clarification.interaction_json or {})
        if interaction.status == "resolved":
            if (
                stored.get("resolved_request_id") == payload.request_id
                and interaction.selected_mode == payload.mode
            ):
                db.rollback()
                return _result_for_message(db, source)
            raise DesignImageAssetConflictError("该生成方式已经确认")

        request = interaction.request
        turn_payload = TurnCreate(
            request_id=interaction.request_id,
            prompt=source.content,
            session_id=session.id,
            base_asset_id=request.base_asset_id,
            reference_asset_ids=list(request.reference_asset_ids),
            model=request.model,
            size=request.size,
            quality=request.quality,
        )
        try:
            base = (
                _usable_asset(
                    db,
                    owner_user_id,
                    session.id,
                    request.base_asset_id,
                    allow_draft=True,
                    now=now,
                )
                if request.base_asset_id is not None
                else None
            )
            references = [
                _usable_asset(
                    db,
                    owner_user_id,
                    session.id,
                    asset_id,
                    allow_draft=True,
                    now=now,
                )
                for asset_id in request.reference_asset_ids
            ]
        except DesignImageNotFoundError as exc:
            raise DesignImageValidationError(
                "附件已失效，请重新上传后发送新请求。",
                code="attachment_unavailable",
            ) from exc
        required = interaction.count if payload.mode == "separate" else 1
        _enforce_capacity(
            db,
            owner_user_id,
            now,
            session_id=session.id,
            required=required,
            require_owner_idle=True,
        )
        intent = MultiOutputIntent(
            mode=payload.mode,
            count=interaction.count,
            labels=tuple(interaction.labels),
            item_kind=interaction.item_kind,
        )
        jobs = _create_jobs_for_intent(
            db,
            owner_user_id,
            session,
            source,
            turn_payload,
            intent,
            base,
            references,
            operation_time=_utc_naive(now),
        )
        stored.update(
            {
                "status": "resolved",
                "selected_mode": payload.mode,
                "resolved_request_id": payload.request_id,
                "resolved_at": _utc_naive(now).isoformat(),
            }
        )
        clarification.interaction_json = stored
        session.updated_at = _utc_naive(now)
        db.commit()
    except IntegrityError:
        db.rollback()
        current = db.get(DesignImageMessage, message_id)
        if current is None or not isinstance(current.interaction_json, dict):
            raise
        if current.interaction_json.get("resolved_request_id") != payload.request_id:
            raise DesignImageAssetConflictError("该生成方式已经确认")
        source = db.get(
            DesignImageMessage, current.interaction_json.get("source_message_id")
        )
        if source is None:
            raise DesignImageConsistencyError("确认结果暂不可见，请重试")
        return _result_for_message(db, source)
    except Exception:
        db.rollback()
        raise
    return TurnResult(
        mode="jobs",
        session=session,
        message=source,
        jobs=jobs,
        clarification=clarification,
    )


def retry_job(
    db: Session,
    owner_user_id: int,
    job_id: int,
    payload: RetryJobRequest,
    *,
    now: datetime | None = None,
) -> TurnResult:
    old = get_job(db, owner_user_id, job_id)
    existing = _find_job_by_idempotency(db, owner_user_id, payload.request_id)
    if existing is not None:
        return _result_for_job(db, existing)
    try:
        _lock_active_owner(db, owner_user_id)
        old = db.execute(
            _job_statement(owner_user_id, job_id, for_update=True)
        ).scalar_one_or_none()
        if old is None:
            raise _not_found()
        if old.status != "failed":
            raise DesignImageAssetConflictError("只有失败任务可以重试")
        winner = _find_job_by_idempotency(
            db, owner_user_id, payload.request_id, for_update=True
        )
        if winner is not None:
            return _rollback_and_reload_winner(
                db, owner_user_id, winner.id, context="retry"
            )
        _enforce_capacity(db, owner_user_id, now, session_id=old.session_id)
        preset_name, model, provider_id, pricing_snapshot, config_version = _preset_snapshot(
            db, old.model or model_catalog.DEFAULT_IMAGE_MODEL_ID
        )
        links = db.execute(
            select(DesignImageJobAsset)
            .where(DesignImageJobAsset.job_id == old.id)
            .order_by(DesignImageJobAsset.position)
            .with_for_update()
        ).scalars().all()
        session = _owner_session(
            db, owner_user_id, old.session_id, for_update=True
        )
        operation_time = _utc_naive(now)
        session.updated_at = operation_time
        job = DesignImageJob(
            owner_user_id=owner_user_id,
            session_id=old.session_id,
            request_message_id=old.request_message_id,
            base_asset_id=old.base_asset_id,
            mode=old.mode,
            status="queued",
            prompt_snapshot=old.prompt_snapshot,
            parameters={
                **dict(old.parameters or {}),
                "provider_id": provider_id,
                "config_version": config_version,
            },
            preset_name=preset_name,
            model=model,
            idempotency_key=payload.request_id,
            retry_of_job_id=old.id,
            pricing_snapshot=pricing_snapshot,
            created_at=operation_time,
        )
        db.add(job)
        db.flush()
        for link in links:
            db.add(
                DesignImageJobAsset(
                    job_id=job.id,
                    asset_id=link.asset_id,
                    role=link.role,
                    position=link.position,
                )
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = _find_job_by_idempotency(db, owner_user_id, payload.request_id)
        if winner is None:
            _warn_visible("design image retry integrity error without idempotent winner")
            raise
        _warn_visible("design image retry idempotency race recovered")
        return _reload_winner_result(
            db, owner_user_id, winner.id, context="retry integrity recovery"
        )
    except Exception:
        db.rollback()
        raise
    return _result_for_job(db, job)


def get_config(
    db: Session, owner_user_id: int, *, now: datetime | None = None
) -> dict:
    settings = get_settings()
    limit = settings.DESIGN_IMAGE_DAILY_LIMIT
    used = _accepted_count(db, owner_user_id, now)
    return {
        "models": model_catalog.public_model_options(db),
        "default_model": model_catalog.DEFAULT_IMAGE_MODEL_ID,
        "sizes": list(VERIFIED_SIZES),
        "qualities": list(VERIFIED_QUALITIES),
        "default_size": "1024x1024",
        "default_quality": "medium",
        "max_reference_assets": MAX_REFERENCE_ASSETS,
        "max_upload_bytes": file_service.effective_max_upload_bytes(),
        "draft_ttl_hours": settings.DESIGN_IMAGE_DRAFT_TTL_HOURS,
        "daily_limit": limit,
        "used_today": used,
        "remaining_today": max(limit - used, 0),
        "max_active_per_user": settings.DESIGN_IMAGE_MAX_ACTIVE_PER_USER,
    }


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    result = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(result)


def get_usage(
    db: Session,
    *,
    owner_user_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    status: str | None = None,
) -> dict:
    if status is not None and status not in JOB_STATUSES:
        raise DesignImageValidationError("任务状态无效")
    query = db.query(DesignImageJob, AiCallLog).outerjoin(
        AiCallLog, AiCallLog.id == DesignImageJob.ai_call_log_id
    )
    if owner_user_id is not None:
        query = query.filter(DesignImageJob.owner_user_id == owner_user_id)
    if start_at is not None:
        query = query.filter(DesignImageJob.created_at >= _utc_naive(start_at))
    if end_at is not None:
        query = query.filter(DesignImageJob.created_at < _utc_naive(end_at))
    if status is not None:
        query = query.filter(DesignImageJob.status == status)
    rows = query.all()
    succeeded = sum(job.status == "succeeded" for job, _ in rows)
    provider_durations = [
        log.duration_ms for _, log in rows if log and log.duration_ms is not None
    ]
    end_to_end_durations = []
    for job, _ in rows:
        if job.finished_at is None:
            continue
        elapsed_ms = round(
            (_utc_naive(job.finished_at) - _utc_naive(job.created_at)).total_seconds()
            * 1000
        )
        if elapsed_ms >= 0:
            end_to_end_durations.append(elapsed_ms)
    input_tokens = sum(
        job.input_tokens if job.input_tokens is not None else (log.tokens_prompt or 0 if log else 0)
        for job, log in rows
    )
    output_tokens = sum(
        job.output_tokens if job.output_tokens is not None else (log.tokens_completion or 0 if log else 0)
        for job, log in rows
    )
    total_tokens = sum(
        job.total_tokens if job.total_tokens is not None else (log.tokens_used or 0 if log else 0)
        for job, log in rows
    )
    errors: dict[str, int] = {}
    certainty: dict[str, int] = {}
    by_user: dict[int, int] = {}
    by_status: dict[str, int] = {}
    by_date: dict[str, int] = {}
    known_costs = []
    unknown_cost_jobs = 0
    for job, log in rows:
        by_user[job.owner_user_id] = by_user.get(job.owner_user_id, 0) + 1
        by_status[job.status] = by_status.get(job.status, 0) + 1
        local_date = (
            _utc_naive(job.created_at)
            .replace(tzinfo=UTC)
            .astimezone(SHANGHAI)
            .date()
            .isoformat()
        )
        by_date[local_date] = by_date.get(local_date, 0) + 1
        if job.status == "failed":
            code = job.error_code or (log.error_code if log else None) or "unknown"
            errors[code] = errors.get(code, 0) + 1
        label = job.billing_certainty or "unknown"
        certainty[label] = certainty.get(label, 0) + 1
        if job.estimated_cost_microusd is None:
            unknown_cost_jobs += 1
        else:
            known_costs.append(job.estimated_cost_microusd)
    count = len(rows)
    return {
        "task_count": count,
        "succeeded_count": succeeded,
        "success_rate": succeeded / count if count else None,
        "end_to_end_duration_ms": {
            "p50": _percentile(end_to_end_durations, 0.50),
            "p95": _percentile(end_to_end_durations, 0.95),
        },
        "provider_duration_ms": {
            "p50": _percentile(provider_durations, 0.50),
            "p95": _percentile(provider_durations, 0.95),
        },
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        },
        "error_categories": errors,
        "estimated_cost_microusd": sum(known_costs) if known_costs else None,
        "unknown_cost_jobs": unknown_cost_jobs,
        "billing_certainty": certainty,
        "by_user": [
            {"owner_user_id": user_id, "task_count": task_count}
            for user_id, task_count in sorted(by_user.items())
        ],
        "by_status": dict(sorted(by_status.items())),
        "by_date": [
            {"date": day, "task_count": task_count}
            for day, task_count in sorted(by_date.items())
        ],
    }
