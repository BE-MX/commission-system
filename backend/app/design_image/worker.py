"""Leased Design Image Studio queue worker.

Claim, provider I/O, and finalize deliberately use separate transactions.  A
provider call can therefore take minutes without retaining an InnoDB row lock,
while every terminal write still proves ownership with the lease token.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from threading import Event, Thread
from uuid import uuid4

import httpx
from sqlalchemy import and_, exists, or_, select, update

from app.ai import service as ai_service
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.design_image import file_service
from app.design_image.models import (
    DesignImageAsset,
    DesignImageJob,
    DesignImageJobAsset,
    DesignImageMessage,
)


logger = logging.getLogger("commission")
MAX_DECODED_IMAGE_BYTES = 20 * 1024 * 1024


class WorkerConfigurationError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: int
    lease_token: str
    worker_id: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class _JobSnapshot:
    job_id: int
    owner_user_id: int
    session_id: int
    mode: str
    prompt: str
    preset_name: str
    size: str | None
    quality: str | None
    input_paths: tuple[tuple[str, str], ...]
    download_hosts: frozenset[str]
    pricing_snapshot: dict | None
    config_version: dict | None


def _warn_visible(message: str) -> None:
    logger.warning(message)
    print(f"[design-image] {message}", flush=True)


def _lock_running_job(db, job_id: int, lease_token: str):
    return db.execute(
        select(DesignImageJob)
        .where(
            DesignImageJob.id == job_id,
            DesignImageJob.status == "running",
            DesignImageJob.lease_token == lease_token,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _live_locked_job(db, job_id: int, lease_token: str):
    job = _lock_running_job(db, job_id, lease_token)
    now = _utcnow()
    if job is None or job.lease_expires_at is None or job.lease_expires_at <= now:
        db.rollback()
        return None, now
    return job, now


def _claim_candidate_statement():
    return (
        select(DesignImageJob.id)
        .where(DesignImageJob.status == "queued")
        .order_by(DesignImageJob.created_at, DesignImageJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _claim_update_statement(
    job_id: int, lease_token: str, worker_id: str, lease_expires_at: datetime
):
    return (
        update(DesignImageJob)
        .where(DesignImageJob.id == job_id, DesignImageJob.status == "queued")
        .values(
            status="running",
            lease_token=lease_token,
            claimed_by=worker_id,
            lease_expires_at=lease_expires_at,
            started_at=_utcnow(),
            claim_count=DesignImageJob.claim_count + 1,
        )
    )


def claim_next_job(
    db, worker_id: str, lease_seconds: int
) -> ClaimedJob | None:
    """Atomically claim the oldest queued row and return a detached snapshot."""
    if not worker_id or lease_seconds <= 0:
        raise ValueError("worker_id and lease_seconds must be valid")
    now = _utcnow()
    expires = now + timedelta(seconds=lease_seconds)
    token = uuid4().hex
    try:
        job_id = db.execute(_claim_candidate_statement()).scalar_one_or_none()
        if job_id is None:
            db.commit()
            return None
        changed = db.execute(
            _claim_update_statement(job_id, token, worker_id, expires)
        ).rowcount
        if changed != 1:
            db.rollback()
            return None
        db.commit()
        return ClaimedJob(job_id, token, worker_id, expires)
    except Exception:
        db.rollback()
        raise


def _load_snapshot(job_id: int, lease_token: str) -> _JobSnapshot | None:
    """Stage A: current-read immutable inputs, then release the transaction."""
    with SessionLocal() as db:
        job, _now = _live_locked_job(db, job_id, lease_token)
        if job is None:
            return None

        preset_row = db.execute(
            select(AiPreset, AiProvider)
            .join(AiProvider, AiProvider.id == AiPreset.provider_id)
            .where(
                AiPreset.preset_name == job.preset_name,
                AiPreset.is_enabled.is_(True),
                AiPreset.deleted_at.is_(None),
                AiProvider.is_enabled.is_(True),
                AiProvider.deleted_at.is_(None),
                AiProvider.provider_type == "direct",
            )
        ).one_or_none()
        if preset_row is None:
            db.commit()
            raise WorkerConfigurationError("design image preset is unavailable")
        preset, _provider = preset_row
        preset_parameters = dict(preset.parameters or {})
        job_parameters = dict(job.parameters or {})
        if (
            job_parameters.get("provider_id") != preset.provider_id
            or job.model != preset.model
            or job.pricing_snapshot != preset_parameters.get("rate_card")
        ):
            db.commit()
            raise WorkerConfigurationError("design image preset changed after queueing")
        configured_hosts = preset_parameters.get("download_hosts")
        hosts = frozenset(
            str(host).strip().lower()
            for host in configured_hosts
            if str(host).strip()
        ) if isinstance(configured_hosts, list) else frozenset()

        paths: list[tuple[str, str]] = []
        if job.base_asset_id is not None:
            base = db.get(DesignImageAsset, job.base_asset_id)
            if base is None or base.deleted_at is not None:
                db.commit()
                raise ValueError("base image is unavailable")
            paths.append((base.storage_path, base.mime_type))
        references = db.execute(
            select(DesignImageAsset)
            .join(DesignImageJobAsset, DesignImageJobAsset.asset_id == DesignImageAsset.id)
            .where(
                DesignImageJobAsset.job_id == job.id,
                DesignImageJobAsset.role == "reference",
                DesignImageAsset.deleted_at.is_(None),
            )
            .order_by(DesignImageJobAsset.position, DesignImageJobAsset.id)
        ).scalars().all()
        paths.extend((row.storage_path, row.mime_type) for row in references)

        parameters = job_parameters
        snapshot = _JobSnapshot(
            job_id=job.id,
            owner_user_id=job.owner_user_id,
            session_id=job.session_id,
            mode=job.mode,
            prompt=job.prompt_snapshot,
            preset_name=job.preset_name,
            size=parameters.get("size"),
            quality=parameters.get("quality"),
            input_paths=tuple(paths),
            download_hosts=hosts,
            pricing_snapshot=dict(job.pricing_snapshot) if job.pricing_snapshot else None,
            config_version=dict(job_parameters.get("config_version") or {}) or None,
        )
        db.commit()
        return snapshot


def _image_inputs(snapshot: _JobSnapshot) -> list[dict]:
    images = []
    for index, (relative_path, mime_type) in enumerate(snapshot.input_paths):
        path = file_service.resolve_private_path(relative_path)
        images.append(
            {
                "filename": f"image-{index}{path.suffix.lower()}",
                "content": path.read_bytes(),
                "content_type": mime_type,
            }
        )
    return images


def _call_provider(snapshot: _JobSnapshot) -> dict:
    """Stage B: facade owns its independent Session commit/rollback lifecycle."""
    kwargs = {
        "preset_name": snapshot.preset_name,
        "prompt": snapshot.prompt,
        "caller_module": "design_image",
        "caller_user_id": snapshot.owner_user_id,
        "size": snapshot.size,
        "quality": snapshot.quality,
    }
    if snapshot.config_version is not None:
        kwargs["expected_config_version"] = snapshot.config_version
    with SessionLocal() as db:
        if snapshot.input_paths:
            return ai_service.edit_image(
                db=db, images=_image_inputs(snapshot), **kwargs
            )
        if snapshot.mode == "generate":
            return ai_service.generate_image(db=db, **kwargs)
        raise ValueError("unsupported design image mode")


def _decode_provider_content(content: str, allowed_hosts: frozenset[str]):
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned no image")
    content = content.strip()
    if content.startswith("https://"):
        if not allowed_hosts:
            raise ValueError("provider download host is not configured")
        payload = file_service.download_provider_image(
            content, allowed_hosts=set(allowed_hosts)
        )
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            declared_mime = "image/png"
        elif payload.startswith(b"\xff\xd8\xff"):
            declared_mime = "image/jpeg"
        elif payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            declared_mime = "image/webp"
        else:
            raise ValueError("provider URL did not return a supported image")
    else:
        declared_mime = "image/png"
        encoded = content
        if content.startswith("data:"):
            header, separator, encoded = content.partition(",")
            if not separator or ";base64" not in header.lower():
                raise ValueError("provider image data URL is invalid")
            declared_mime = header[5:].split(";", 1)[0].lower()
            if declared_mime not in {"image/jpeg", "image/png", "image/webp"}:
                raise ValueError("provider image type is unsupported")
        if len(encoded) > ((MAX_DECODED_IMAGE_BYTES + 2) // 3) * 4:
            raise ValueError("provider image is too large")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("provider image base64 is invalid") from None
    return file_service.normalize_upload(payload, declared_mime)


def _usage_values(result: dict) -> tuple[int | None, int | None, int | None]:
    usage = dict(result.get("usage_detail") or {})
    input_tokens = _safe_nonnegative_bigint(
        usage.get("input_tokens", usage.get("prompt_tokens"))
    )
    output_tokens = _safe_nonnegative_bigint(
        usage.get("output_tokens", usage.get("completion_tokens"))
    )
    total_tokens = _safe_nonnegative_bigint(
        usage.get("total_tokens", result.get("tokens_used"))
    )
    return input_tokens, output_tokens, total_tokens


def _safe_nonnegative_bigint(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 2**63 - 1:
        return None
    return value


def _estimated_cost(pricing: dict | None, usage: dict) -> int | None:
    if not pricing:
        return None
    total = 0
    found = False
    limit = 2**63 - 1
    for direction in ("input", "output"):
        details = usage.get(f"{direction}_tokens_details")
        for kind in ("text", "image"):
            rate = pricing.get(f"{direction}_{kind}_microusd_per_token")
            if rate is None:
                continue
            found = True
            tokens = details.get(f"{kind}_tokens") if isinstance(details, dict) else None
            try:
                if isinstance(tokens, bool) or isinstance(rate, bool):
                    return None
                tokens_int = int(tokens)
                rate_int = int(rate)
                if tokens_int != tokens or rate_int != rate:
                    return None
            except (TypeError, ValueError, OverflowError):
                return None
            if tokens_int < 0 or rate_int < 0 or tokens_int > limit or rate_int > limit:
                return None
            amount = tokens_int * rate_int
            if amount > limit - total:
                return None
            total += amount
    return total if found else None


def _delete_stored(stored, context: str) -> None:
    for path in (stored.relative_path, stored.thumbnail_relative_path):
        try:
            file_service.delete_private_file(path)
        except Exception as exc:
            _warn_visible(f"{context}: failed to delete {path}: {exc}")


def _finalize_success(
    snapshot: _JobSnapshot, lease_token: str, result: dict, stored
) -> bool:
    with SessionLocal() as db:
        try:
            job, now = _live_locked_job(db, snapshot.job_id, lease_token)
            if job is None:
                return False
            message = DesignImageMessage(
                session_id=snapshot.session_id,
                role="assistant",
                content="图片已生成",
                status="normal",
            )
            db.add(message)
            db.flush()
            asset = DesignImageAsset(
                session_id=snapshot.session_id,
                message_id=message.id,
                asset_type="output",
                storage_path=stored.relative_path,
                mime_type=stored.mime_type,
                file_size=stored.file_size,
                width=stored.width,
                height=stored.height,
                sha256=stored.sha256,
                source_asset_id=job.base_asset_id,
                status="attached",
                created_by=snapshot.owner_user_id,
            )
            db.add(asset)
            db.flush()
            input_tokens, output_tokens, total_tokens = _usage_values(result)
            estimated_cost = _estimated_cost(
                snapshot.pricing_snapshot, dict(result.get("usage_detail") or {})
            )
            job.status = "succeeded"
            job.output_asset_id = asset.id
            job.response_message_id = message.id
            job.ai_call_log_id = result.get("log_id")
            job.provider_attempt_count = result.get("provider_attempt_count", 0)
            job.billing_certainty = "estimated" if estimated_cost is not None else "unknown"
            job.input_tokens = input_tokens
            job.output_tokens = output_tokens
            job.total_tokens = total_tokens
            job.estimated_cost_microusd = estimated_cost
            job.finished_at = now
            job.lease_token = job.lease_expires_at = job.claimed_by = None
            job.error_code = job.error_message = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


def _map_error(exc: Exception) -> tuple[str, str]:
    detail = str(exc).lower()
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "rate_limited", "服务请求过多，请稍后手动重试"
        if status in {502, 503}:
            return "provider_unavailable", "图片服务暂不可用，请稍后重试"
        if status == 504:
            return "provider_timeout", "图片服务响应超时，请稍后重试"
        if status in {400, 422} and any(
            word in detail for word in ("moderation", "safety", "content_policy")
        ):
            return "moderation_blocked", "内容未通过安全检查，请修改描述后重试"
        if status in {400, 422}:
            return "validation_error", "图片参数无效，请调整后重试"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "provider_timeout", "图片服务响应超时，请稍后重试"
    if isinstance(exc, (ValueError, file_service.ImageValidationError)):
        if isinstance(exc, WorkerConfigurationError):
            return "configuration_error", "图片服务配置已变化，请手动重试"
        return "validation_error", "图片或参数无效，请调整后重试"
    return "unknown_error", "生成失败，请稍后重试；若持续失败请联系管理员"


def _finalize_failure(job_id: int, lease_token: str, exc: Exception) -> bool:
    code, message = _map_error(exc)
    attempts = max(0, int(getattr(exc, "provider_attempt_count", 0) or 0))
    with SessionLocal() as db:
        try:
            job, now = _live_locked_job(db, job_id, lease_token)
            if job is None:
                return False
            candidate_log_id = getattr(exc, "log_id", None)
            effective_log_id = None
            if candidate_log_id is not None:
                log = db.execute(
                    select(AiCallLog)
                    .where(AiCallLog.id == candidate_log_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if log is None:
                    _warn_visible(
                        f"job {job_id}: AI call log {candidate_log_id} is missing"
                    )
                else:
                    effective_log_id = candidate_log_id
                    if log.status == "pending":
                        log.status = "error"
                        log.error_code = code
                        log.error_message = message
            job.status = "failed"
            job.error_code = code
            job.error_message = message
            job.provider_attempt_count = attempts
            job.ai_call_log_id = effective_log_id
            job.billing_certainty = "unknown"
            job.finished_at = now
            job.lease_token = job.lease_expires_at = job.claimed_by = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


def _renew_lease(job_id: int, lease_token: str, lease_seconds: int) -> bool:
    """Extend a live lease in its own short transaction."""
    with SessionLocal() as db:
        try:
            job, now = _live_locked_job(db, job_id, lease_token)
            if job is None:
                return False
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


@contextmanager
def _lease_heartbeat(job_id: int, lease_token: str, lease_seconds: int):
    """Keep long Provider retries leased without holding any transaction open."""
    stop = Event()

    def heartbeat() -> None:
        interval = max(1.0, lease_seconds / 3)
        while not stop.wait(interval):
            try:
                if not _renew_lease(job_id, lease_token, lease_seconds):
                    return
            except Exception as exc:
                _warn_visible(f"job {job_id} lease heartbeat failed: {exc}")

    thread = Thread(target=heartbeat, name=f"design-image-lease-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def _execute_claimed_job(job_id: int, lease_token: str) -> None:
    stored = None
    result = None
    try:
        snapshot = _load_snapshot(job_id, lease_token)
        if snapshot is None:
            _warn_visible(f"job {job_id} lease was lost before execution")
            return
        result = _call_provider(snapshot)
        normalized = _decode_provider_content(
            result.get("content", ""), snapshot.download_hosts
        )
        stored = file_service.save_private_image(
            normalized, owner_user_id=snapshot.owner_user_id, kind="output"
        )
        if not _finalize_success(snapshot, lease_token, result, stored):
            _delete_stored(stored, f"orphan response for job {job_id}")
            _warn_visible(f"orphan response ignored for job {job_id}: lease lost")
    except Exception as exc:
        _warn_visible(f"job {job_id} execution failed: {type(exc).__name__}: {exc}")
        if result is not None:
            setattr(exc, "log_id", result.get("log_id"))
            setattr(exc, "provider_attempt_count", result.get("provider_attempt_count", 0))
        if stored is not None:
            _delete_stored(stored, f"failed finalize for job {job_id}")
        try:
            if not _finalize_failure(job_id, lease_token, exc):
                _warn_visible(f"late failure ignored for job {job_id}: lease lost")
        except Exception as finalize_exc:
            _warn_visible(f"job {job_id} failure finalize failed: {finalize_exc}")


def execute_claimed_job(job_id: int, lease_token: str) -> None:
    lease_seconds = get_settings().DESIGN_IMAGE_LEASE_SECONDS
    if not _renew_lease(job_id, lease_token, lease_seconds):
        _warn_visible(f"job {job_id} lease expired before execution")
        return
    with _lease_heartbeat(job_id, lease_token, lease_seconds):
        _execute_claimed_job(job_id, lease_token)


def recover_stale_jobs(db, stale_before: datetime) -> int:
    """Fail running jobs with an expired lease or a missing-lease stale start."""
    now = _utcnow()
    try:
        changed = db.execute(
            update(DesignImageJob)
            .where(
                DesignImageJob.status == "running",
                or_(
                    DesignImageJob.lease_expires_at <= now,
                    and_(
                        DesignImageJob.lease_expires_at.is_(None),
                        DesignImageJob.started_at <= stale_before,
                    ),
                ),
            )
            .values(
                status="failed",
                error_code="worker_timeout",
                error_message="任务执行超时，请手动重试",
                billing_certainty="unknown",
                finished_at=now,
                lease_token=None,
                lease_expires_at=None,
                claimed_by=None,
            )
        ).rowcount
        db.commit()
        return changed
    except Exception:
        db.rollback()
        raise


def _thumbnail_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    return str(path.with_name(f"{path.stem}_thumb{path.suffix}"))


def cleanup_expired_drafts(db, now: datetime) -> int:
    """Soft-delete eligible drafts, commit, then remove exact files best-effort."""
    linked = exists().where(DesignImageJobAsset.asset_id == DesignImageAsset.id)
    used_as_base = exists().where(DesignImageJob.base_asset_id == DesignImageAsset.id)
    candidate_ids = db.execute(
        select(DesignImageAsset.id)
        .where(
            DesignImageAsset.status == "draft",
            DesignImageAsset.deleted_at.is_(None),
            DesignImageAsset.expires_at <= now,
            ~linked,
            ~used_as_base,
        )
        .order_by(DesignImageAsset.created_by, DesignImageAsset.id)
    ).scalars().all()
    paths: list[str] = []
    try:
        for asset_id in candidate_ids:
            asset = db.get(DesignImageAsset, asset_id)
            if asset is None:
                continue
            db.execute(select(ArkUser.id).where(ArkUser.id == asset.created_by).with_for_update())
            locked = db.execute(
                select(DesignImageAsset)
                .where(
                    DesignImageAsset.id == asset_id,
                    DesignImageAsset.status == "draft",
                    DesignImageAsset.deleted_at.is_(None),
                    DesignImageAsset.expires_at <= now,
                    ~linked,
                    ~used_as_base,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if locked is not None:
                locked.deleted_at = now
                paths.extend([locked.storage_path, _thumbnail_path(locked.storage_path)])
        db.commit()
    except Exception:
        db.rollback()
        raise

    for path in paths:
        try:
            file_service.delete_private_file(path)
        except Exception as exc:
            _warn_visible(f"expired draft cleanup failed for {path}: {exc}")
    return len(paths) // 2


def process_design_image_queue() -> None:
    """Recover/clean, claim a bounded batch, and wait for its worker threads."""
    settings = get_settings()
    concurrency = settings.DESIGN_IMAGE_WORKER_CONCURRENCY
    now = _utcnow()
    try:
        with SessionLocal() as db:
            recover_stale_jobs(
                db, now - timedelta(seconds=settings.DESIGN_IMAGE_STALE_SECONDS)
            )
        with SessionLocal() as db:
            cleanup_expired_drafts(db, now)

        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        claims: list[ClaimedJob] = []
        for _ in range(concurrency):
            with SessionLocal() as db:
                claim = claim_next_job(
                    db, worker_id, settings.DESIGN_IMAGE_LEASE_SECONDS
                )
            if claim is None:
                break
            claims.append(claim)
        if claims:
            with ThreadPoolExecutor(
                max_workers=concurrency, thread_name_prefix="design-image"
            ) as executor:
                futures = [
                    executor.submit(
                        execute_claimed_job, claim.job_id, claim.lease_token
                    )
                    for claim in claims
                ]
                wait(futures)
                for future in futures:
                    future.result()
    except Exception as exc:
        _warn_visible(f"queue wake-up failed: {exc}")
