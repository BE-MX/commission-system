"""Governed asynchronous AI optimization for knowledge documents."""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.knowledge import access, service
from app.knowledge.models import (
    KnowledgeAiJob,
    KnowledgeAiJobSource,
    KnowledgeAiProfile,
    KnowledgeAiProfileSource,
    KnowledgeAiProfileTarget,
    KnowledgeDocument,
    KnowledgeLibrary,
    KnowledgeLibraryMember,
    KnowledgeRevision,
    bj_now,
)


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "applied"}
ACTIVE_STATUSES = {"queued", "running"}


def has_ai_permission(identity: dict, permission: str) -> bool:
    return access.is_super_admin(identity) or permission in set(identity.get("permissions", [])) or (
        permission == "knowledge_ai:write" and "knowledge_ai:admin" in set(identity.get("permissions", []))
    )


def require_ai(identity: dict, permission: str = "knowledge_ai:write") -> None:
    if not has_ai_permission(identity, permission):
        raise service.ForbiddenError(f"missing permission: {permission}")


def profile_for_target(db, profile_id: int, library_id: int, *, enabled: bool = True) -> KnowledgeAiProfile:
    query = db.query(KnowledgeAiProfile).join(
        KnowledgeAiProfileTarget,
        KnowledgeAiProfileTarget.profile_id == KnowledgeAiProfile.id,
    ).filter(
        KnowledgeAiProfile.id == profile_id,
        KnowledgeAiProfile.deleted_at.is_(None),
        KnowledgeAiProfileTarget.library_id == library_id,
    )
    if enabled:
        query = query.filter(KnowledgeAiProfile.is_enabled.is_(True))
    row = query.first()
    if not row:
        raise service.NotFoundError("knowledge AI profile not found")
    return row


def identity_for_user(db, user_id: int) -> dict:
    user = db.query(ArkUser).filter(
        ArkUser.id == user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).first()
    if not user:
        raise service.ForbiddenError("knowledge AI owner is inactive")
    return {
        "sub": str(user.id),
        "username": user.username,
        "roles": get_user_roles(user),
        "permissions": get_user_permissions(user),
    }


def _keywords(title: str, text: str) -> list[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z0-9_-]{3,24}", f"{title}\n{text}")
    result: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        candidates = [chunk]
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk) and len(chunk) > 2:
            # Chinese text has no spaces. Add overlapping phrases so a target
            # sentence can match a shorter sentence in an authorized source.
            candidates.extend(
                chunk[index:index + width]
                for width in (4, 3, 2)
                for index in range(len(chunk) - width + 1)
            )
        for candidate in candidates:
            normalized = candidate.lower()
            if normalized not in seen:
                result.append(candidate)
                seen.add(normalized)
            if len(result) >= 30:
                return result
    return result


def allowed_source_library_ids(
    db, identity: dict, profile: KnowledgeAiProfile, target_library_id: int
) -> list[int]:
    configured = [row[0] for row in db.query(KnowledgeAiProfileSource.library_id).filter(
        KnowledgeAiProfileSource.profile_id == profile.id
    ).all()]
    active = {row[0] for row in db.query(KnowledgeLibrary.id).filter(
        KnowledgeLibrary.id.in_(configured or [-1]),
        KnowledgeLibrary.status == "active",
        KnowledgeLibrary.deleted_at.is_(None),
    ).all()}
    configured = [library_id for library_id in configured if library_id in active]
    if not profile.allow_cross_library:
        configured = [library_id for library_id in configured if library_id == target_library_id]
    if access.is_super_admin(identity):
        return configured
    readable = {row[0] for row in db.query(KnowledgeLibraryMember.library_id).filter(
        KnowledgeLibraryMember.user_id == access.user_id(identity),
        KnowledgeLibraryMember.library_id.in_(configured or [-1]),
    ).all()}
    return [library_id for library_id in configured if library_id in readable]


def retrieve_sources(
    db,
    identity: dict,
    profile: KnowledgeAiProfile,
    *,
    target_library_id: int,
    title: str,
    content_text: str,
) -> list[dict]:
    """Rank published revisions inside the authorized configured source set."""
    allowed_ids = allowed_source_library_ids(db, identity, profile, target_library_id)
    if not allowed_ids:
        return []
    terms = _keywords(title, content_text)
    query = db.query(KnowledgeDocument, KnowledgeRevision).join(
        KnowledgeRevision,
        KnowledgeRevision.id == KnowledgeDocument.published_revision_id,
    ).join(
        KnowledgeLibrary,
        KnowledgeLibrary.id == KnowledgeDocument.library_id,
    ).filter(
        KnowledgeDocument.library_id.in_(allowed_ids),
        KnowledgeDocument.deleted_at.is_(None),
        KnowledgeLibrary.deleted_at.is_(None),
        KnowledgeLibrary.status == "active",
    )
    if terms:
        filters = []
        for term in terms[:12]:
            filters.extend((KnowledgeRevision.title.contains(term), KnowledgeRevision.content_text.contains(term)))
        query = query.filter(or_(*filters))
    rows = query.order_by(KnowledgeDocument.id.desc()).limit(200).all()
    ranked: list[dict] = []
    for document, revision in rows:
        haystack = f"{revision.title}\n{revision.content_text}".lower()
        score = sum((3 if term.lower() in revision.title.lower() else 1) * haystack.count(term.lower()) for term in terms)
        if not terms:
            score = 1
        ranked.append({
            "library_id": document.library_id,
            "document_id": document.id,
            "revision_id": revision.id,
            "title": revision.title,
            "content_text": revision.content_text,
            "score": score,
        })
    ranked.sort(key=lambda item: (-item["score"], item["document_id"]))
    return ranked[:profile.retrieval_limit]


def ai_runtime_fingerprints(preset, provider) -> tuple[str, str]:
    def digest(payload: dict) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    return digest({
        "id": preset.id, "name": preset.preset_name, "model": preset.model,
        "system_prompt": preset.system_prompt, "parameters": preset.parameters,
        "provider_id": preset.provider_id, "enabled": preset.is_enabled,
    }), digest({
        "id": provider.id, "type": provider.provider_type, "api_type": provider.api_type,
        "api_base": provider.api_base, "api_key": provider.api_key,
        "headers": provider.extra_headers, "timeout": provider.timeout_sec,
        "enabled": provider.is_enabled,
    })


def _config_snapshot(db, profile: KnowledgeAiProfile) -> dict:
    from app.ai.models import AiPreset, AiProvider

    preset, provider = db.query(AiPreset, AiProvider).join(
        AiProvider, AiProvider.id == AiPreset.provider_id
    ).filter(AiPreset.id == profile.preset_id).one()
    preset_fingerprint, provider_fingerprint = ai_runtime_fingerprints(preset, provider)
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "config_version": profile.config_version,
        "preset_id": profile.preset_id,
        "preset_name": preset.preset_name,
        "preset_model": preset.model,
        "preset_updated_at": preset.updated_at.isoformat() if preset.updated_at else None,
        "provider_id": provider.id,
        "provider_updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
        "preset_fingerprint": preset_fingerprint,
        "provider_fingerprint": provider_fingerprint,
        "format_prompt": profile.format_prompt or "",
        "enhance_prompt": profile.enhance_prompt or "",
        "retrieval_limit": profile.retrieval_limit,
        "context_char_limit": profile.context_char_limit,
        "allow_cross_library": profile.allow_cross_library,
        "require_citations": profile.require_citations,
        "max_document_chars": profile.max_document_chars,
    }


def create_job(
    db,
    identity: dict,
    document_id: int,
    *,
    mode: str,
    profile_id: int,
    base_revision_id: int,
    idempotency_key: str,
) -> KnowledgeAiJob:
    require_ai(identity)
    if mode not in {"format", "enhance"}:
        raise service.ValidationError("invalid knowledge AI mode")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", idempotency_key or ""):
        raise service.ValidationError("invalid knowledge AI idempotency key")
    service._require_platform(identity, "knowledge:write")
    document = service._document(db, identity, document_id, "write", lock_library=True)
    if document.node_type != "document" or document.draft_revision_id != base_revision_id:
        raise service.ConflictError("document draft changed; save and retry AI optimization")
    revision = db.query(KnowledgeRevision).filter(
        KnowledgeRevision.id == base_revision_id,
        KnowledgeRevision.document_id == document.id,
    ).first()
    if not revision:
        raise service.NotFoundError("base revision not found")
    profile = profile_for_target(db, profile_id, document.library_id)
    if len(revision.content_text) > profile.max_document_chars:
        raise service.ValidationError("document exceeds the AI profile character limit")
    actor_id = access.user_id(identity)
    # Serialize quota decisions for this user across different target libraries.
    db.query(ArkUser.id).filter(ArkUser.id == actor_id).with_for_update().first()
    existing = db.query(KnowledgeAiJob).filter(
        KnowledgeAiJob.owner_user_id == actor_id,
        KnowledgeAiJob.idempotency_key == idempotency_key,
    ).first()
    if existing:
        if (
            existing.document_id == document.id
            and existing.base_revision_id == base_revision_id
            and existing.profile_id == profile_id
            and existing.mode == mode
        ):
            return existing
        raise service.ConflictError("idempotency key is already used for another knowledge AI request")
    active_count = db.query(func.count(KnowledgeAiJob.id)).filter(
        KnowledgeAiJob.owner_user_id == actor_id,
        KnowledgeAiJob.status.in_(ACTIVE_STATUSES),
    ).scalar() or 0
    if active_count >= profile.max_concurrent_per_user:
        raise service.ConflictError("too many active knowledge AI jobs")
    start_of_day = bj_now().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = db.query(func.count(KnowledgeAiJob.id)).filter(
        KnowledgeAiJob.owner_user_id == actor_id,
        KnowledgeAiJob.created_at >= start_of_day,
    ).scalar() or 0
    if daily_count >= profile.daily_limit:
        raise service.ConflictError("knowledge AI daily limit reached")

    sources = []
    if mode == "enhance":
        sources = retrieve_sources(
            db,
            identity,
            profile,
            target_library_id=document.library_id,
            title=revision.title,
            content_text=revision.content_text,
        )
        if profile.require_citations and not sources:
            raise service.ValidationError("no authorized published knowledge sources were found")
    job = KnowledgeAiJob(
        document_id=document.id,
        base_revision_id=revision.id,
        owner_user_id=actor_id,
        profile_id=profile.id,
        mode=mode,
        status="queued",
        idempotency_key=idempotency_key,
        config_snapshot=_config_snapshot(db, profile),
    )
    try:
        db.add(job)
        db.flush()
        for position, source in enumerate(sources):
            db.add(KnowledgeAiJobSource(
                job_id=job.id,
                library_id=source["library_id"],
                document_id=source["document_id"],
                revision_id=source["revision_id"],
                title_snapshot=source["title"],
                score=source["score"],
                position=position,
            ))
        service._audit(db, identity, document.library_id, "create_ai_job", "document", document.id, revision.id, {
            "job_id": job.id,
            "mode": mode,
            "profile_id": profile.id,
            "source_count": len(sources),
        })
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise service.ConflictError("duplicate knowledge AI request") from exc
    db.refresh(job)
    return job


def _job(db, identity: dict, job_id: int, *, for_update: bool = False) -> tuple[KnowledgeAiJob, KnowledgeDocument]:
    query = db.query(KnowledgeAiJob).filter(KnowledgeAiJob.id == job_id)
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise service.NotFoundError("knowledge AI job not found")
    document = service._document(db, identity, row.document_id, "write", lock_library=for_update)
    if row.owner_user_id != access.user_id(identity) and not has_ai_permission(identity, "knowledge_ai:admin"):
        raise service.NotFoundError("knowledge AI job not found")
    source_library_ids = {item[0] for item in db.query(
        KnowledgeAiJobSource.library_id
    ).filter(KnowledgeAiJobSource.job_id == row.id).all()}
    if any(not _source_library_is_readable(db, identity, library_id) for library_id in source_library_ids):
        raise service.ForbiddenError("knowledge source access was revoked")
    return row, document


def _serialize_sources(db, job_id: int) -> list[dict]:
    rows = db.query(KnowledgeAiJobSource).filter(
        KnowledgeAiJobSource.job_id == job_id
    ).order_by(KnowledgeAiJobSource.position).all()
    return [{
        "library_id": row.library_id,
        "document_id": row.document_id,
        "revision_id": row.revision_id,
        "title": row.title_snapshot,
        "score": row.score,
    } for row in rows]


def serialize_job(db, row: KnowledgeAiJob) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "base_revision_id": row.base_revision_id,
        "profile_id": row.profile_id,
        "mode": row.mode,
        "status": row.status,
        "result": row.result_json,
        "comparison": row.comparison_json,
        "sources": _serialize_sources(db, row.id),
        "applied_revision_id": row.applied_revision_id,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "applied_at": row.applied_at,
    }


def get_job(db, identity: dict, job_id: int) -> dict:
    require_ai(identity)
    row, _document = _job(db, identity, job_id)
    return serialize_job(db, row)


def list_document_jobs(db, identity: dict, document_id: int) -> list[dict]:
    require_ai(identity)
    service._document(db, identity, document_id, "write")
    query = db.query(KnowledgeAiJob).filter(KnowledgeAiJob.document_id == document_id)
    if not has_ai_permission(identity, "knowledge_ai:admin"):
        query = query.filter(KnowledgeAiJob.owner_user_id == access.user_id(identity))
    result = []
    for row in query.order_by(KnowledgeAiJob.created_at.desc()).limit(30).all():
        source_library_ids = {item[0] for item in db.query(
            KnowledgeAiJobSource.library_id
        ).filter(KnowledgeAiJobSource.job_id == row.id).all()}
        if all(_source_library_is_readable(db, identity, library_id) for library_id in source_library_ids):
            result.append(serialize_job(db, row))
    return result


def _source_library_is_readable(db, identity: dict, library_id: int) -> bool:
    active = db.query(KnowledgeLibrary.id).filter(
        KnowledgeLibrary.id == library_id,
        KnowledgeLibrary.status == "active",
        KnowledgeLibrary.deleted_at.is_(None),
    ).first()
    return bool(active and access.can(db, identity, library_id, "read"))


def cancel_job(db, identity: dict, job_id: int) -> dict:
    require_ai(identity)
    preflight, _ = _job(db, identity, job_id)
    document = service._document(db, identity, preflight.document_id, "write", lock_library=True)
    row = db.query(KnowledgeAiJob).populate_existing().filter(
        KnowledgeAiJob.id == job_id
    ).with_for_update().first()
    if not row or (
        row.owner_user_id != access.user_id(identity)
        and not has_ai_permission(identity, "knowledge_ai:admin")
    ):
        raise service.NotFoundError("knowledge AI job not found")
    if row.status in TERMINAL_STATUSES:
        return serialize_job(db, row)
    row.status = "cancelled"
    row.lease_token = row.claimed_by = None
    row.lease_expires_at = None
    row.finished_at = bj_now()
    service._audit(db, identity, document.library_id, "cancel_ai_job", "document", document.id, row.base_revision_id, {"job_id": row.id})
    db.commit()
    return serialize_job(db, row)


def apply_job(db, identity: dict, job_id: int) -> dict:
    require_ai(identity)
    preflight, _ = _job(db, identity, job_id)
    document = service._document(db, identity, preflight.document_id, "write", lock_library=True)
    row = db.query(KnowledgeAiJob).populate_existing().filter(
        KnowledgeAiJob.id == job_id
    ).with_for_update().first()
    if row.applied_revision_id:
        return {"job_id": row.id, "revision_id": row.applied_revision_id}
    if row.status != "completed" or not row.result_json:
        raise service.ConflictError("knowledge AI job is not ready to apply")
    if document.draft_revision_id != row.base_revision_id:
        raise service.ConflictError("document draft changed; AI result cannot overwrite newer edits")
    revision = service._create_revision(
        db,
        identity,
        document,
        row.result_json["title"],
        row.result_json["content_json"],
    )
    row.status = "applied"
    row.applied_revision_id = revision.id
    row.applied_at = bj_now()
    service._audit(db, identity, document.library_id, "apply_ai_job", "document", document.id, revision.id, {
        "job_id": row.id,
        "mode": row.mode,
        "base_revision_id": row.base_revision_id,
    })
    db.commit()
    return {"job_id": row.id, "revision_id": revision.id, "version_no": revision.version_no}


def preview_retrieval(db, identity: dict, profile_id: int, target_library_id: int, sample_text: str) -> list[dict]:
    require_ai(identity, "knowledge_ai:admin")
    service._require_platform(identity, "knowledge:read")
    service._library(db, identity, target_library_id, "read")
    profile = profile_for_target(db, profile_id, target_library_id, enabled=False)
    return [{key: value for key, value in item.items() if key != "content_text"} | {
        "excerpt": item["content_text"][:300]
    } for item in retrieve_sources(
        db,
        identity,
        profile,
        target_library_id=target_library_id,
        title="检索预览",
        content_text=sample_text,
    )]
