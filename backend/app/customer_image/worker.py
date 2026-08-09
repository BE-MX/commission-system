"""Leased worker for invitation-scoped customer image generations."""

from __future__ import annotations

import logging
import os
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select, update

from app.ai import image_job_runtime as image_runtime
from app.ai.service import build_image_config_version
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.customer_image import file_service
from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageProductAsset,
)


logger = logging.getLogger("commission")


class WorkerConfigurationError(ValueError):
    """Raised when a frozen job cannot be executed without configuration drift."""


class FrozenInputReadError(ValueError):
    """Raised before provider I/O when a frozen input cannot be read."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _warn_visible(message: str) -> None:
    logger.warning(message)
    print(f"[customer-image] {message}", flush=True)


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: int
    lease_token: str
    worker_id: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class _JobSnapshot:
    job_id: int
    invite_id: int
    caller_user_id: int
    prompt: str
    preset_name: str
    size: str | None
    quality: str | None
    input_paths: tuple[tuple[str, str], ...]
    download_hosts: frozenset[str]
    pricing_snapshot: dict | None
    config_version: dict


def _claim_job_statement():
    return (
        select(CustomerImageGeneration.id)
        .where(CustomerImageGeneration.status == "queued")
        .order_by(
            CustomerImageGeneration.created_at,
            CustomerImageGeneration.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def claim_next_job(db, worker_id: str, lease_seconds: int) -> ClaimedJob | None:
    if not worker_id or lease_seconds <= 0:
        raise ValueError("worker_id and lease_seconds must be valid")
    now = _utcnow()
    expires_at = now + timedelta(seconds=lease_seconds)
    lease_token = uuid4().hex
    try:
        job_id = db.execute(_claim_job_statement()).scalar_one_or_none()
        if job_id is None:
            db.commit()
            return None
        changed = db.execute(
            update(CustomerImageGeneration)
            .where(
                CustomerImageGeneration.id == job_id,
                CustomerImageGeneration.status == "queued",
            )
            .values(
                status="running",
                claimed_by=worker_id,
                lease_token=lease_token,
                lease_expires_at=expires_at,
                started_at=now,
                claim_count=CustomerImageGeneration.claim_count + 1,
            )
        ).rowcount
        if changed != 1:
            db.rollback()
            return None
        db.commit()
        return ClaimedJob(job_id, lease_token, worker_id, expires_at)
    except Exception:
        db.rollback()
        raise


def _lock_running_generation(db, job_id: int, lease_token: str):
    return db.scalar(
        select(CustomerImageGeneration)
        .where(
            CustomerImageGeneration.id == job_id,
            CustomerImageGeneration.status == "running",
            CustomerImageGeneration.lease_token == lease_token,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _live_locked_generation(db, job_id: int, lease_token: str):
    generation = _lock_running_generation(db, job_id, lease_token)
    now = _utcnow()
    if (
        generation is None
        or generation.lease_expires_at is None
        or generation.lease_expires_at <= now
    ):
        db.rollback()
        return None, now
    return generation, now


def _snapshot_parameters(generation: CustomerImageGeneration) -> tuple[dict, dict]:
    parameters = generation.parameters_snapshot
    if not isinstance(parameters, dict):
        raise WorkerConfigurationError("generation parameters snapshot is invalid")
    config_version = parameters.get("config_version")
    if not isinstance(config_version, dict):
        raise WorkerConfigurationError("generation config version is invalid")
    return parameters, config_version


def _load_snapshot(job_id: int, lease_token: str) -> _JobSnapshot | None:
    with SessionLocal() as db:
        generation, _now = _live_locked_generation(db, job_id, lease_token)
        if generation is None:
            return None
        parameters, config_version = _snapshot_parameters(generation)
        provider_id = parameters.get("provider_id")
        preset_row = db.execute(
            select(AiPreset, AiProvider)
            .join(AiProvider, AiProvider.id == AiPreset.provider_id)
            .where(
                AiPreset.preset_name == generation.preset_name,
                AiPreset.provider_id == provider_id,
                AiPreset.is_enabled.is_(True),
                AiPreset.deleted_at.is_(None),
                AiProvider.is_enabled.is_(True),
                AiProvider.deleted_at.is_(None),
                AiProvider.provider_type == "direct",
            )
        ).one_or_none()
        if preset_row is None:
            db.commit()
            raise WorkerConfigurationError("customer image preset is unavailable")
        preset, provider = preset_row
        if (
            generation.model != preset.model
            or config_version.get("provider_id") != provider.id
            or config_version.get("fingerprint")
            != build_image_config_version(preset, provider)
        ):
            db.commit()
            raise WorkerConfigurationError("customer image preset changed after queueing")

        invite = db.get(CustomerImageInvite, generation.invite_id)
        if invite is None:
            db.commit()
            raise WorkerConfigurationError("generation invite is unavailable")
        logo = db.scalar(select(CustomerImageAsset).where(
            CustomerImageAsset.id == generation.logo_asset_id,
            CustomerImageAsset.invite_id == generation.invite_id,
            CustomerImageAsset.asset_type == "logo",
        ))
        if logo is None:
            db.commit()
            raise ValueError("frozen logo is unavailable")

        reference_ids = generation.reference_asset_ids
        if not isinstance(reference_ids, list) or any(
            isinstance(asset_id, bool) or not isinstance(asset_id, int)
            for asset_id in reference_ids
        ):
            db.commit()
            raise WorkerConfigurationError("generation reference snapshot is invalid")
        references = list(db.scalars(select(CustomerImageProductAsset).where(
            CustomerImageProductAsset.id.in_(reference_ids),
            CustomerImageProductAsset.product_id == generation.product_id,
        )).all()) if reference_ids else []
        references_by_id = {asset.id: asset for asset in references}
        if len(references_by_id) != len(reference_ids):
            db.commit()
            raise ValueError("frozen product reference is unavailable")
        expected_asset_ids = [logo.id, *reference_ids]
        if parameters.get("input_asset_ids") != expected_asset_ids:
            db.commit()
            raise WorkerConfigurationError("generation input asset snapshot is invalid")
        configured_hosts = parameters.get("download_hosts")
        if not isinstance(configured_hosts, list):
            db.commit()
            raise WorkerConfigurationError("generation download hosts are invalid")
        input_paths = [(logo.storage_path, logo.mime_type)]
        input_paths.extend(
            (references_by_id[asset_id].storage_path, references_by_id[asset_id].mime_type)
            for asset_id in reference_ids
        )
        snapshot = _JobSnapshot(
            job_id=generation.id,
            invite_id=invite.id,
            caller_user_id=invite.created_by,
            prompt=generation.prompt_snapshot,
            preset_name=generation.preset_name,
            size=parameters.get("size"),
            quality=parameters.get("quality"),
            input_paths=tuple(input_paths),
            download_hosts=frozenset(
                str(host).strip().lower()
                for host in configured_hosts
                if str(host).strip()
            ),
            pricing_snapshot=(
                dict(generation.pricing_snapshot)
                if isinstance(generation.pricing_snapshot, dict) else None
            ),
            config_version=dict(config_version),
        )
        db.commit()
        return snapshot


def _image_inputs(snapshot: _JobSnapshot) -> tuple[image_runtime.ImageInput, ...]:
    images = []
    for index, (relative_path, mime_type) in enumerate(snapshot.input_paths):
        try:
            path = file_service.resolve_private_path(relative_path)
            content = path.read_bytes()
        except OSError as exc:
            failure = FrozenInputReadError("frozen input image is unavailable")
            setattr(failure, "billing_certainty", "not_billed")
            setattr(failure, "provider_attempt_count", 0)
            raise failure from exc
        images.append(image_runtime.ImageInput(
            filename=f"image-{index}{path.suffix.lower()}",
            content=content,
            content_type=mime_type,
        ))
    return tuple(images)


def _download_provider_image(url: str, allowed_hosts: frozenset[str]) -> bytes:
    return file_service.shared_files.download_provider_image(
        url, allowed_hosts=set(allowed_hosts)
    )


def _call_provider(snapshot: _JobSnapshot) -> image_runtime.ImageJobResult:
    request = image_runtime.ImageJobRequest(
        preset_name=snapshot.preset_name,
        prompt=snapshot.prompt,
        caller_module="customer_image",
        caller_user_id=snapshot.caller_user_id,
        size=snapshot.size,
        quality=snapshot.quality,
        input_images=_image_inputs(snapshot),
        expected_config_version=snapshot.config_version,
        download_hosts=snapshot.download_hosts,
        pricing_snapshot=snapshot.pricing_snapshot,
    )
    with SessionLocal() as db:
        return image_runtime.call_image_provider(
            db, request, download_image=_download_provider_image
        )


def _effective_log_id(
    db, log_id: int | None, job_id: int, failure: image_runtime.ImageJobFailure | None = None
) -> int | None:
    if log_id is None:
        return None
    log = db.scalar(select(AiCallLog).where(AiCallLog.id == log_id).with_for_update())
    if log is None:
        _warn_visible(f"job {job_id}: AI call log {log_id} is missing")
        return None
    if failure is not None and log.status == "pending":
        log.status = "error"
        log.error_code = failure.code
        log.error_message = failure.customer_message
    return log_id


def _finalize_success(
    snapshot: _JobSnapshot,
    lease_token: str,
    result: image_runtime.ImageJobResult,
    stored,
) -> bool:
    with SessionLocal() as db:
        try:
            generation, now = _live_locked_generation(db, snapshot.job_id, lease_token)
            if generation is None:
                return False
            output = CustomerImageAsset(
                invite_id=snapshot.invite_id,
                asset_type="generated",
                storage_path=stored.relative_path,
                mime_type=stored.mime_type,
                file_size=stored.file_size,
                width=stored.width,
                height=stored.height,
                sha256=stored.sha256,
            )
            db.add(output)
            db.flush()
            generation.status = "succeeded"
            generation.output_asset_id = output.id
            generation.ai_call_log_id = _effective_log_id(
                db, result.log_id, generation.id
            )
            generation.provider_attempt_count = result.provider_attempt_count
            generation.billing_certainty = result.billing_certainty
            generation.input_tokens = result.input_tokens
            generation.output_tokens = result.output_tokens
            generation.total_tokens = result.total_tokens
            generation.estimated_cost_microusd = result.estimated_cost_microusd
            generation.error_code = generation.error_message = None
            generation.finished_at = now
            generation.claimed_by = None
            generation.lease_token = None
            generation.lease_expires_at = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


def _invite_id_for_generation(db, job_id: int) -> int | None:
    return db.scalar(select(CustomerImageGeneration.invite_id).where(
        CustomerImageGeneration.id == job_id
    ))


def finalize_failure(
    job_id: int,
    lease_token: str,
    failure: image_runtime.ImageJobFailure,
) -> bool:
    """Finalize a classified failure using the global invite→generation lock order."""
    with SessionLocal() as db:
        try:
            invite_id = _invite_id_for_generation(db, job_id)
            if invite_id is None:
                db.rollback()
                return False
            invite = db.scalar(
                select(CustomerImageInvite)
                .where(CustomerImageInvite.id == invite_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if invite is None:
                db.rollback()
                return False
            generation, now = _live_locked_generation(db, job_id, lease_token)
            if generation is None or generation.invite_id != invite.id:
                return False
            generation.status = "failed"
            generation.error_code = failure.code
            generation.error_message = failure.customer_message
            generation.provider_attempt_count = failure.provider_attempt_count
            generation.ai_call_log_id = _effective_log_id(
                db, failure.log_id, generation.id, failure
            )
            generation.billing_certainty = (
                "not_billed" if failure.refund_eligible else "unknown"
            )
            generation.finished_at = now
            generation.claimed_by = None
            generation.lease_token = None
            generation.lease_expires_at = None
            if (
                failure.refund_eligible
                and generation.quota_refunded_at is None
                and invite.quota_used > 0
            ):
                invite.quota_used -= 1
                generation.quota_refunded_at = now
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


def _renew_lease(job_id: int, lease_token: str, lease_seconds: float) -> bool:
    with SessionLocal() as db:
        try:
            generation, now = _live_locked_generation(db, job_id, lease_token)
            if generation is None:
                return False
            generation.lease_expires_at = now + timedelta(seconds=lease_seconds)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


@contextmanager
def _lease_heartbeat(job_id: int, lease_token: str, lease_seconds: float):
    stop = Event()

    def heartbeat() -> None:
        interval = max(0.01, lease_seconds / 3)
        while not stop.wait(interval):
            try:
                if not _renew_lease(job_id, lease_token, lease_seconds):
                    return
            except Exception as exc:
                _warn_visible(f"job {job_id} lease heartbeat failed: {exc}")

    thread = Thread(
        target=heartbeat,
        name=f"customer-image-lease-{job_id}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def _delete_stored(stored, context: str) -> None:
    for path in (stored.relative_path, stored.thumbnail_relative_path):
        try:
            file_service.delete_private_file(path)
        except Exception as exc:
            _warn_visible(f"{context}: failed to delete {path}: {exc}")


def _reconcile_success(job_id: int, stored) -> str:
    """Resolve an uncertain finalize acknowledgement without risking live output."""
    try:
        with SessionLocal() as db:
            row = db.execute(
                select(
                    CustomerImageGeneration.status,
                    CustomerImageGeneration.output_asset_id,
                    CustomerImageAsset.storage_path,
                )
                .outerjoin(
                    CustomerImageAsset,
                    CustomerImageAsset.id
                    == CustomerImageGeneration.output_asset_id,
                )
                .where(CustomerImageGeneration.id == job_id)
            ).one_or_none()
    except Exception as exc:
        _warn_visible(
            f"job {job_id} success reconciliation failed: {type(exc).__name__}"
        )
        return "unknown"
    if (
        row is not None
        and row.status == "succeeded"
        and row.output_asset_id is not None
        and row.storage_path == stored.relative_path
    ):
        return "committed"
    return "not_committed"


def _execute_claimed_job(job_id: int, lease_token: str) -> None:
    result = None
    stored = None
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
            normalized,
            owner_user_id=snapshot.invite_id,
            kind="customer-output",
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
            reconciliation = _reconcile_success(job_id, stored)
            if reconciliation == "committed":
                _warn_visible(
                    f"job {job_id} success confirmed after acknowledgement error"
                )
                return
            if reconciliation == "unknown":
                _warn_visible(
                    f"job {job_id} output retained because database state is unknown"
                )
                return
            _delete_stored(stored, f"failed finalize for job {job_id}")
        failure = image_runtime.classify_image_error(exc)
        try:
            if not finalize_failure(job_id, lease_token, failure):
                _warn_visible(f"late failure ignored for job {job_id}: lease lost")
        except Exception as finalize_exc:
            _warn_visible(f"job {job_id} failure finalize failed: {finalize_exc}")


def execute_claimed_job(job_id: int, lease_token: str) -> None:
    lease_seconds = get_settings().CUSTOMER_IMAGE_LEASE_SECONDS
    if not _renew_lease(job_id, lease_token, lease_seconds):
        _warn_visible(f"job {job_id} lease expired before execution")
        return
    with _lease_heartbeat(job_id, lease_token, lease_seconds):
        _execute_claimed_job(job_id, lease_token)


def recover_stale_jobs(db, stale_before: datetime) -> int:
    now = _utcnow()
    try:
        changed = db.execute(
            update(CustomerImageGeneration)
            .where(
                CustomerImageGeneration.status == "running",
                or_(
                    CustomerImageGeneration.lease_expires_at <= now,
                    and_(
                        CustomerImageGeneration.lease_expires_at.is_(None),
                        CustomerImageGeneration.started_at <= stale_before,
                    ),
                ),
            )
            .values(
                status="failed",
                error_code="worker_timeout",
                error_message="任务执行超时，请联系业务员重试",
                billing_certainty="unknown",
                finished_at=now,
                claimed_by=None,
                lease_token=None,
                lease_expires_at=None,
            )
        ).rowcount
        db.commit()
        return changed
    except Exception:
        db.rollback()
        raise


def cleanup_expired_invite_assets(
    db, now: datetime, *, retention_days: int
) -> int:
    """Soft-delete expired invite assets, commit, then retry exact file removal."""
    cutoff = now - timedelta(days=retention_days)
    unfinished_generation = exists().where(
        CustomerImageGeneration.invite_id == CustomerImageInvite.id,
        CustomerImageGeneration.status.in_(("queued", "running")),
    )
    assets = list(db.scalars(
        select(CustomerImageAsset)
        .join(CustomerImageInvite, CustomerImageInvite.id == CustomerImageAsset.invite_id)
        .where(
            CustomerImageInvite.expires_at <= cutoff,
            ~unfinished_generation,
        )
        .order_by(CustomerImageAsset.invite_id, CustomerImageAsset.id)
    ).all())
    newly_deleted = 0
    try:
        for asset in assets:
            if asset.deleted_at is None:
                asset.deleted_at = now
                newly_deleted += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    for asset in assets:
        for path in (
            asset.storage_path,
            file_service._thumbnail_path(asset.storage_path),
        ):
            try:
                file_service.delete_private_file(path)
            except Exception as exc:
                _warn_visible(f"expired invite asset cleanup failed for {path}: {exc}")
    return newly_deleted


def process_customer_image_cleanup() -> int:
    settings = get_settings()
    with SessionLocal() as db:
        return cleanup_expired_invite_assets(
            db,
            _utcnow(),
            retention_days=settings.CUSTOMER_IMAGE_RETENTION_DAYS,
        )


def process_customer_image_queue() -> None:
    """Recover stale work, claim a bounded batch, then execute without scheduler DB state."""
    settings = get_settings()
    concurrency = settings.CUSTOMER_IMAGE_WORKER_CONCURRENCY
    now = _utcnow()
    try:
        with SessionLocal() as db:
            recover_stale_jobs(
                db,
                now - timedelta(seconds=settings.CUSTOMER_IMAGE_STALE_SECONDS),
            )
        worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        claims: list[ClaimedJob] = []
        for _ in range(concurrency):
            with SessionLocal() as db:
                claim = claim_next_job(
                    db,
                    worker_id=worker_id,
                    lease_seconds=settings.CUSTOMER_IMAGE_LEASE_SECONDS,
                )
            if claim is None:
                break
            claims.append(claim)
        if claims:
            with ThreadPoolExecutor(
                max_workers=concurrency,
                thread_name_prefix="customer-image",
            ) as executor:
                futures = [
                    executor.submit(
                        execute_claimed_job,
                        claim.job_id,
                        claim.lease_token,
                    )
                    for claim in claims
                ]
                wait(futures)
                for future in futures:
                    future.result()
    except Exception as exc:
        _warn_visible(f"queue wake-up failed: {exc}")
