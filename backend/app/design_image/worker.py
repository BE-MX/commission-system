"""Leased Design Image Studio queue worker.

Claim, provider I/O, and finalize deliberately use separate transactions.  A
provider call can therefore take minutes without retaining an InnoDB row lock,
while every terminal write still proves ownership with the lease token.
"""

from __future__ import annotations

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

from sqlalchemy import and_, exists, or_, select, update

from app.ai import service as ai_service
from app.ai import image_job_runtime as image_runtime
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


def _image_inputs(snapshot: _JobSnapshot) -> tuple[image_runtime.ImageInput, ...]:
    images = []
    for index, (relative_path, mime_type) in enumerate(snapshot.input_paths):
        path = file_service.resolve_private_path(relative_path)
        images.append(
            image_runtime.ImageInput(
                filename=f"image-{index}{path.suffix.lower()}",
                content=path.read_bytes(),
                content_type=mime_type,
            )
        )
    return tuple(images)


def _download_provider_image(url: str, allowed_hosts: frozenset[str]) -> bytes:
    return file_service.download_provider_image(url, allowed_hosts=set(allowed_hosts))


def _call_provider(snapshot: _JobSnapshot) -> image_runtime.ImageJobResult:
    """Stage B: facade owns its independent Session commit/rollback lifecycle."""
    request = image_runtime.ImageJobRequest(
        preset_name=snapshot.preset_name,
        prompt=snapshot.prompt,
        caller_module="design_image",
        caller_user_id=snapshot.owner_user_id,
        size=snapshot.size,
        quality=snapshot.quality,
        input_images=_image_inputs(snapshot),
        expected_config_version=snapshot.config_version,
        download_hosts=snapshot.download_hosts,
        pricing_snapshot=snapshot.pricing_snapshot,
    )
    with SessionLocal() as db:
        if not snapshot.input_paths and snapshot.mode != "generate":
            raise ValueError("unsupported design image mode")
        return image_runtime.call_image_provider(
            db, request, download_image=_download_provider_image
        )


def _decode_provider_content(content: str, allowed_hosts: frozenset[str]):
    image = image_runtime.decode_image_payload(
        content, allowed_hosts, download_image=_download_provider_image
    )
    return file_service.normalize_upload(image.content, image.declared_mime)


def _usage_values(result: dict) -> tuple[int | None, int | None, int | None]:
    return image_runtime.usage_values(result)


def _safe_nonnegative_bigint(value) -> int | None:
    return image_runtime._safe_nonnegative_bigint(value)


def _estimated_cost(pricing: dict | None, usage: dict) -> int | None:
    return image_runtime.estimated_cost_microusd(pricing, usage)


def _delete_stored(stored, context: str) -> None:
    for path in (stored.relative_path, stored.thumbnail_relative_path):
        try:
            file_service.delete_private_file(path)
        except Exception as exc:
            _warn_visible(f"{context}: failed to delete {path}: {exc}")


def _finalize_success(
    snapshot: _JobSnapshot,
    lease_token: str,
    result: image_runtime.ImageJobResult,
    stored,
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
            job.status = "succeeded"
            job.output_asset_id = asset.id
            job.response_message_id = message.id
            job.ai_call_log_id = result.log_id
            job.provider_attempt_count = result.provider_attempt_count
            job.billing_certainty = result.billing_certainty
            job.input_tokens = result.input_tokens
            job.output_tokens = result.output_tokens
            job.total_tokens = result.total_tokens
            job.estimated_cost_microusd = result.estimated_cost_microusd
            job.finished_at = now
            job.lease_token = job.lease_expires_at = job.claimed_by = None
            job.error_code = job.error_message = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


def _map_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, WorkerConfigurationError):
        return "configuration_error", "图片服务配置已变化，请手动重试"
    failure = image_runtime.classify_image_error(exc)
    return failure.code, failure.customer_message


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
        normalized = file_service.normalize_upload(
            result.image.content, result.image.declared_mime
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
            setattr(exc, "log_id", result.log_id)
            setattr(exc, "provider_attempt_count", result.provider_attempt_count)
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
