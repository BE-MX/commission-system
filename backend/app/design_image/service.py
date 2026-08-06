"""Owner-scoped Design Image Studio services.

The turn and retry writers use an ORM ``FOR UPDATE`` owner-row query. SQLite
unit tests verify the generated MySQL query and transaction outcomes, but cannot
prove InnoDB lock contention; that remains a Phase 5 MySQL integration gate.
Provider calls intentionally live outside this module and its transactions.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import BinaryIO
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, noload

from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.ai.service import build_image_config_version
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.design_image import file_service
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
    TurnCreate,
)


logger = logging.getLogger("commission")
SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
PRESET_NAME = "design_image_generation"
EXPECTED_MODEL = "gpt-image-2"
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
    pass


class DesignImageConfigurationError(DesignImageError):
    pass


class DesignImageQuotaExceededError(DesignImageError):
    pass


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
    job: DesignImageJob
    session: DesignImageSession
    message: DesignImageMessage
    reference_links: list[DesignImageJobAsset]


@dataclass(frozen=True)
class ActiveJobResult:
    job: DesignImageJob
    session: DesignImageSession


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


def get_active_job(db: Session, owner_user_id: int) -> ActiveJobResult | None:
    job = (
        db.query(DesignImageJob)
        .filter(
            DesignImageJob.owner_user_id == owner_user_id,
            DesignImageJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(DesignImageJob.created_at.desc(), DesignImageJob.id.desc())
        .first()
    )
    if job is None:
        return None
    session = _owner_session(db, owner_user_id, job.session_id)
    return ActiveJobResult(job=job, session=session)


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
        if asset.status != "draft" or referenced is not None or based_on is not None:
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
        .limit(1)
    )
    return statement.with_for_update() if for_update else statement


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


def _enforce_capacity(db: Session, owner_user_id: int, now: datetime | None) -> None:
    # Both reads are locking/current reads. Under MySQL REPEATABLE READ, the
    # earlier idempotency lookup may have established an old consistent-read
    # snapshot; ordinary SELECTs here would miss a job committed while this
    # transaction waited for the owner row lock.
    if _accepted_count(
        db, owner_user_id, now, for_update=True
    ) >= get_settings().DESIGN_IMAGE_DAILY_LIMIT:
        raise DesignImageQuotaExceededError("今日额度已用完；如有紧急任务请联系管理员")
    active = db.execute(
        _active_job_statement(owner_user_id, for_update=True)
    ).scalar_one_or_none()
    if active is not None:
        raise DesignImageActiveJobError("已有生成任务正在进行，请等待完成")


def _preset_snapshot(db: Session) -> tuple[str, str, int, dict | None, dict]:
    row = (
        db.query(AiPreset, AiProvider)
        .join(AiProvider, AiProvider.id == AiPreset.provider_id)
        .filter(
            AiPreset.preset_name == PRESET_NAME,
            AiPreset.deleted_at.is_(None),
            AiPreset.is_enabled.is_(True),
            AiProvider.deleted_at.is_(None),
            AiProvider.is_enabled.is_(True),
            AiProvider.provider_type == "direct",
        )
        .first()
    )
    if row is None or row[0].model != EXPECTED_MODEL:
        raise DesignImageConfigurationError("生图服务配置不可用，请联系管理员")
    rate_card = (row[0].parameters or {}).get("rate_card")
    if rate_card is not None and not isinstance(rate_card, dict):
        raise DesignImageConfigurationError("生图价格配置不可用，请联系管理员")
    config_version = {
        "provider_id": row[1].id,
        "fingerprint": build_image_config_version(row[0], row[1]),
    }
    return (
        row[0].preset_name, row[0].model, row[0].provider_id,
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


def _result_for_job(db: Session, job: DesignImageJob) -> TurnResult:
    session = db.query(DesignImageSession).filter_by(id=job.session_id).one()
    message = db.query(DesignImageMessage).filter_by(id=job.request_message_id).one()
    links = (
        db.query(DesignImageJobAsset)
        .filter_by(job_id=job.id)
        .order_by(DesignImageJobAsset.position)
        .all()
    )
    return TurnResult(job=job, session=session, message=message, reference_links=links)


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
    existing = _find_job_by_idempotency(db, owner_user_id, payload.request_id)
    if existing is not None:
        return _result_for_job(db, existing)
    try:
        _lock_active_owner(db, owner_user_id)
        winner = _find_job_by_idempotency(
            db, owner_user_id, payload.request_id, for_update=True
        )
        if winner is not None:
            return _rollback_and_reload_winner(
                db, owner_user_id, winner.id, context="turn"
            )
        _enforce_capacity(db, owner_user_id, now)
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
        base = (
            _usable_asset(
                db, owner_user_id, session.id, payload.base_asset_id,
                allow_draft=False, now=now,
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
        preset_name, model, provider_id, pricing_snapshot, config_version = _preset_snapshot(db)
        message = DesignImageMessage(
            session_id=session.id,
            role="user",
            content=payload.prompt,
            status="normal",
        )
        db.add(message)
        db.flush()
        job = DesignImageJob(
            owner_user_id=owner_user_id,
            session_id=session.id,
            request_message_id=message.id,
            base_asset_id=base.id if base else None,
            mode="edit" if base else "generate",
            status="queued",
            prompt_snapshot=_prompt_snapshot(payload.prompt, editing=base is not None),
            parameters={
                "size": payload.size, "quality": payload.quality,
                "provider_id": provider_id,
                "config_version": config_version,
            },
            preset_name=preset_name,
            model=model,
            idempotency_key=payload.request_id,
            pricing_snapshot=pricing_snapshot,
            created_at=operation_time,
        )
        db.add(job)
        db.flush()
        for position, asset in enumerate(references):
            db.add(
                DesignImageJobAsset(
                    job_id=job.id,
                    asset_id=asset.id,
                    role="reference",
                    position=position,
                )
            )
            if asset.status == "draft":
                asset.status = "attached"
                asset.message_id = message.id
                asset.expires_at = None
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = _find_job_by_idempotency(db, owner_user_id, payload.request_id)
        if winner is None:
            _warn_visible("design image turn integrity error without idempotent winner")
            raise
        _warn_visible("design image turn idempotency race recovered")
        return _reload_winner_result(
            db, owner_user_id, winner.id, context="turn integrity recovery"
        )
    except Exception:
        db.rollback()
        raise
    return _result_for_job(db, job)


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
        _enforce_capacity(db, owner_user_id, now)
        preset_name, model, provider_id, pricing_snapshot, config_version = _preset_snapshot(db)
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
