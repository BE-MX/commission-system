"""Lease-based worker for knowledge AI optimization jobs."""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from app.ai.models import AiPreset, AiProvider
from app.ai.service import chat
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.knowledge import ai_job_service, ai_prompt_service, service
from app.knowledge.models import (
    KnowledgeAiJob, KnowledgeAiJobSource, KnowledgeRevision, bj_now,
)


logger = logging.getLogger("commission")
MAX_CLAIM_COUNT = 3


@dataclass(frozen=True, slots=True)
class ClaimedKnowledgeJob:
    job_id: int
    lease_token: str


def lease_seconds_for_provider(provider: AiProvider) -> int:
    return max(
        get_settings().KNOWLEDGE_AI_LEASE_SECONDS,
        int(provider.timeout_sec or 60) + 60,
    )


def claim_next_job(db, worker_id: str) -> ClaimedKnowledgeJob | None:
    now = bj_now()
    row = db.query(KnowledgeAiJob).filter(
        KnowledgeAiJob.status == "queued"
    ).order_by(KnowledgeAiJob.created_at, KnowledgeAiJob.id).with_for_update(skip_locked=True).first()
    if not row:
        db.commit()
        return None
    token = uuid4().hex
    row.status = "running"
    row.claimed_by = worker_id
    row.lease_token = token
    row.lease_expires_at = now + timedelta(seconds=get_settings().KNOWLEDGE_AI_LEASE_SECONDS)
    row.claim_count += 1
    row.started_at = now
    row.error_code = row.error_message = None
    db.commit()
    return ClaimedKnowledgeJob(row.id, token)


def recover_stale_jobs(db) -> int:
    now = bj_now()
    rows = db.query(KnowledgeAiJob).filter(
        KnowledgeAiJob.status == "running", KnowledgeAiJob.lease_expires_at < now,
    ).with_for_update().all()
    for row in rows:
        exhausted = row.claim_count >= MAX_CLAIM_COUNT
        row.status = "failed" if exhausted else "queued"
        row.claimed_by = row.lease_token = None
        row.lease_expires_at = None
        row.error_code = "stale_exhausted" if exhausted else "stale_requeued"
        if exhausted:
            row.error_message = "knowledge AI worker lease expired repeatedly"
            row.finished_at = now
    db.commit()
    return len(rows)


def execute_claimed_job(job_id: int, lease_token: str) -> None:
    with SessionLocal() as db:
        job = db.query(KnowledgeAiJob).filter(
            KnowledgeAiJob.id == job_id, KnowledgeAiJob.status == "running",
            KnowledgeAiJob.lease_token == lease_token,
        ).first()
        if not job:
            return
        try:
            identity = ai_job_service.identity_for_user(db, job.owner_user_id)
            ai_job_service.require_ai(identity)
            service._require_platform(identity, "knowledge:write")
            document = service._document(db, identity, job.document_id, "write")
            profile = ai_job_service.profile_for_target(db, job.profile_id, document.library_id)
            if profile.config_version != job.config_snapshot.get("config_version"):
                logger.info("knowledge AI job uses frozen profile version job_id=%s", job.id)
            base = db.query(KnowledgeRevision).filter(KnowledgeRevision.id == job.base_revision_id).first()
            if not base:
                raise service.NotFoundError("base revision not found")
            source_rows = db.query(KnowledgeAiJobSource, KnowledgeRevision).join(
                KnowledgeRevision, KnowledgeRevision.id == KnowledgeAiJobSource.revision_id,
            ).filter(KnowledgeAiJobSource.job_id == job.id).order_by(
                KnowledgeAiJobSource.position
            ).all()
            allowed_ids = set(ai_job_service.allowed_source_library_ids(
                db, identity, profile, document.library_id
            ))
            if any(source.library_id not in allowed_ids for source, _ in source_rows):
                raise service.ForbiddenError("knowledge source access was revoked")
            if not ai_job_service._job_sources_are_readable(db, identity, job.id):
                raise service.ForbiddenError("knowledge source document was deleted or revoked")
            preset = db.query(AiPreset).filter(
                AiPreset.id == job.config_snapshot.get("preset_id"),
                AiPreset.deleted_at.is_(None),
                AiPreset.is_enabled.is_(True),
            ).first()
            if not preset:
                raise service.NotFoundError("knowledge AI preset not found")
            provider = db.query(AiProvider).filter(
                AiProvider.id == preset.provider_id,
                AiProvider.deleted_at.is_(None),
                AiProvider.is_enabled.is_(True),
            ).first()
            if not provider:
                raise service.NotFoundError("knowledge AI provider not found")
            snapshot = job.config_snapshot
            preset_fingerprint, provider_fingerprint = ai_job_service.ai_runtime_fingerprints(
                preset, provider
            )
            if (
                preset_fingerprint != snapshot.get("preset_fingerprint")
                or provider_fingerprint != snapshot.get("provider_fingerprint")
            ):
                raise service.ConflictError(
                    "knowledge AI preset changed after the job was created; create a new job"
                )
            # The provider timeout is configurable and can exceed the default lease.
            # Extend this claim before the blocking network call so another scheduler
            # cannot requeue the same job and send a duplicate AI request.
            job.lease_expires_at = bj_now() + timedelta(
                seconds=lease_seconds_for_provider(provider)
            )
            db.commit()
            response = chat(
                db, preset_name=preset.preset_name,
                messages=ai_prompt_service.build_messages(job, base, source_rows),
                caller_module="knowledge_ai_optimization",
                caller_user_id=job.owner_user_id, snapshot_mode="metadata",
            )
            result = ai_prompt_service.parse_result(response["content"])
            job.ai_call_log_id = response["log_id"]
            db.commit()
            if not db.query(KnowledgeAiJob.id).populate_existing().filter(
                KnowledgeAiJob.id == job.id,
                KnowledgeAiJob.status == "running",
                KnowledgeAiJob.lease_token == lease_token,
            ).first():
                return
            comparison = ai_prompt_service.validate_result(
                job,
                base,
                result,
                {source.revision_id: revision.content_text for source, revision in source_rows},
            )
            verification_response = None
            if job.mode == "enhance":
                job.lease_expires_at = bj_now() + timedelta(
                    seconds=lease_seconds_for_provider(provider)
                )
                db.commit()
                verification_response = chat(
                    db, preset_name=preset.preset_name,
                    messages=ai_prompt_service.build_verification_messages(
                        job, base, result["content_json"], result.get("citations", [])
                    ),
                    caller_module="knowledge_ai_semantic_verification",
                    caller_user_id=job.owner_user_id, snapshot_mode="metadata",
                )
                job.verification_ai_call_log_id = verification_response["log_id"]
                db.commit()
                verification = ai_prompt_service.parse_verification(
                    verification_response["content"]
                )
                ai_prompt_service.validate_verification(job, base, result, verification)
            current = db.query(KnowledgeAiJob).filter(
                KnowledgeAiJob.id == job.id, KnowledgeAiJob.status == "running",
                KnowledgeAiJob.lease_token == lease_token,
            ).with_for_update().first()
            if not current:
                return
            current.status = "completed"
            current.result_json = result
            current.comparison_json = comparison
            current.ai_call_log_id = response["log_id"]
            if verification_response:
                current.verification_ai_call_log_id = verification_response["log_id"]
            current.total_tokens = sum(filter(None, [
                response.get("tokens_used"),
                verification_response.get("tokens_used") if verification_response else None,
            ])) or None
            current.finished_at = bj_now()
            current.claimed_by = current.lease_token = None
            current.lease_expires_at = None
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("knowledge AI job failed job_id=%s error=%s", job_id, exc)
            print(f"[knowledge-ai] job failed id={job_id}: {exc}", flush=True)
            current = db.query(KnowledgeAiJob).filter(
                KnowledgeAiJob.id == job_id, KnowledgeAiJob.status == "running",
                KnowledgeAiJob.lease_token == lease_token,
            ).with_for_update().first()
            if current:
                current.status = "failed"
                current.error_code = type(exc).__name__[:64]
                current.error_message = str(exc)[:1000]
                current.finished_at = bj_now()
                current.claimed_by = current.lease_token = None
                current.lease_expires_at = None
                db.commit()


def process_queue() -> dict:
    worker_id = f"{socket.gethostname()}:{uuid4().hex[:8]}"
    with SessionLocal() as db:
        recovered = recover_stale_jobs(db)
        claim = claim_next_job(db, worker_id)
    if claim:
        execute_claimed_job(claim.job_id, claim.lease_token)
    return {"recovered": recovered, "processed": 1 if claim else 0}
