"""Administrative configuration for knowledge AI optimization."""

from __future__ import annotations

from app.ai.models import AiPreset, AiProvider
from app.ai.service import chat
from app.knowledge import access, service
from app.knowledge.models import (
    KnowledgeAiProfile,
    KnowledgeAiProfileLog,
    KnowledgeAiProfileSource,
    KnowledgeAiProfileTarget,
    KnowledgeLibrary,
)
from app.knowledge.service import ForbiddenError, NotFoundError, ValidationError


def _require_admin(identity: dict) -> None:
    if not access.is_super_admin(identity) and "knowledge_ai:admin" not in set(identity.get("permissions", [])):
        raise ForbiddenError("missing permission: knowledge_ai:admin")


def _profile(db, profile_id: int, *, for_update: bool = False) -> KnowledgeAiProfile:
    query = db.query(KnowledgeAiProfile).filter(
        KnowledgeAiProfile.id == profile_id,
        KnowledgeAiProfile.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    row = query.first()
    if not row:
        raise NotFoundError("knowledge AI profile not found")
    return row


def _valid_libraries(db, library_ids: list[int]) -> set[int]:
    if not library_ids:
        return set()
    rows = db.query(KnowledgeLibrary.id).filter(
        KnowledgeLibrary.id.in_(library_ids),
        KnowledgeLibrary.status == "active",
        KnowledgeLibrary.deleted_at.is_(None),
    ).all()
    return {row[0] for row in rows}


def _validate_links(db, data: dict) -> AiPreset:
    preset = db.query(AiPreset).join(AiProvider, AiProvider.id == AiPreset.provider_id).filter(
        AiPreset.id == data["preset_id"],
        AiPreset.deleted_at.is_(None),
        AiPreset.is_enabled.is_(True),
        AiProvider.deleted_at.is_(None),
        AiProvider.is_enabled.is_(True),
        AiProvider.provider_type == "direct",
    ).first()
    if not preset:
        raise ValidationError("preset must be an enabled direct text preset")
    library_ids = set(data["source_library_ids"]) | set(data["target_library_ids"])
    if _valid_libraries(db, list(library_ids)) != library_ids:
        raise ValidationError("knowledge AI profile contains missing or inactive libraries")
    return preset


def _replace_links(db, profile_id: int, data: dict) -> None:
    db.query(KnowledgeAiProfileSource).filter(
        KnowledgeAiProfileSource.profile_id == profile_id
    ).delete(synchronize_session=False)
    db.query(KnowledgeAiProfileTarget).filter(
        KnowledgeAiProfileTarget.profile_id == profile_id
    ).delete(synchronize_session=False)
    for library_id in data["source_library_ids"]:
        db.add(KnowledgeAiProfileSource(profile_id=profile_id, library_id=library_id))
    for library_id in data["target_library_ids"]:
        db.add(KnowledgeAiProfileTarget(profile_id=profile_id, library_id=library_id))


def _log(db, identity: dict, row: KnowledgeAiProfile, action: str, data: dict) -> None:
    db.add(KnowledgeAiProfileLog(
        profile_id=row.id,
        actor_user_id=access.user_id(identity),
        action=action,
        config_version=row.config_version,
        detail={
            "name": row.name,
            "preset_id": row.preset_id,
            "source_library_ids": data.get("source_library_ids", []),
            "target_library_ids": data.get("target_library_ids", []),
            "is_enabled": row.is_enabled,
        },
    ))


def _serialize(db, row: KnowledgeAiProfile) -> dict:
    source_ids = [item[0] for item in db.query(KnowledgeAiProfileSource.library_id).filter(
        KnowledgeAiProfileSource.profile_id == row.id
    ).order_by(KnowledgeAiProfileSource.library_id).all()]
    target_ids = [item[0] for item in db.query(KnowledgeAiProfileTarget.library_id).filter(
        KnowledgeAiProfileTarget.profile_id == row.id
    ).order_by(KnowledgeAiProfileTarget.library_id).all()]
    preset = db.query(AiPreset).filter(AiPreset.id == row.preset_id).first()
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "preset_id": row.preset_id,
        "preset_name": preset.preset_name if preset else None,
        "format_prompt": row.format_prompt,
        "enhance_prompt": row.enhance_prompt,
        "source_library_ids": source_ids,
        "target_library_ids": target_ids,
        "retrieval_limit": row.retrieval_limit,
        "context_char_limit": row.context_char_limit,
        "allow_cross_library": row.allow_cross_library,
        "require_citations": row.require_citations,
        "max_document_chars": row.max_document_chars,
        "daily_limit": row.daily_limit,
        "max_concurrent_per_user": row.max_concurrent_per_user,
        "config_version": row.config_version,
        "is_enabled": row.is_enabled,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def create_profile(db, identity: dict, data: dict) -> dict:
    _require_admin(identity)
    _validate_links(db, data)
    row = KnowledgeAiProfile(
        **{key: value for key, value in data.items() if key not in {"source_library_ids", "target_library_ids"}},
        created_by=access.user_id(identity),
        config_version=1,
    )
    db.add(row)
    db.flush()
    _replace_links(db, row.id, data)
    _log(db, identity, row, "create", data)
    db.commit()
    db.refresh(row)
    return _serialize(db, row)


def update_profile(db, identity: dict, profile_id: int, data: dict) -> dict:
    _require_admin(identity)
    _validate_links(db, data)
    row = _profile(db, profile_id, for_update=True)
    for key, value in data.items():
        if key not in {"source_library_ids", "target_library_ids"}:
            setattr(row, key, value)
    row.config_version += 1
    _replace_links(db, row.id, data)
    _log(db, identity, row, "update", data)
    db.commit()
    db.refresh(row)
    return _serialize(db, row)


def delete_profile(db, identity: dict, profile_id: int) -> dict:
    _require_admin(identity)
    row = _profile(db, profile_id, for_update=True)
    from app.knowledge.models import bj_now

    row.deleted_at = bj_now()
    row.is_enabled = False
    row.config_version += 1
    _log(db, identity, row, "delete", {})
    db.commit()
    return {"id": row.id}


def list_profiles(db, identity: dict, *, target_library_id: int | None = None) -> list[dict]:
    is_admin = access.is_super_admin(identity) or "knowledge_ai:admin" in set(identity.get("permissions", []))
    if not is_admin and "knowledge_ai:write" not in set(identity.get("permissions", [])):
        raise ForbiddenError("missing permission: knowledge_ai:write")
    if not is_admin:
        if not target_library_id:
            raise ValidationError("target_library_id is required")
        service._require_platform(identity, "knowledge:read")
        service._library(db, identity, target_library_id, "read")
    query = db.query(KnowledgeAiProfile).filter(KnowledgeAiProfile.deleted_at.is_(None))
    if not is_admin:
        query = query.filter(KnowledgeAiProfile.is_enabled.is_(True))
    if target_library_id:
        query = query.join(
            KnowledgeAiProfileTarget,
            KnowledgeAiProfileTarget.profile_id == KnowledgeAiProfile.id,
        ).filter(KnowledgeAiProfileTarget.library_id == target_library_id)
    serialized = [_serialize(db, row) for row in query.order_by(KnowledgeAiProfile.name).all()]
    if is_admin:
        return serialized
    allowed_fields = {"id", "name", "description", "config_version", "is_enabled"}
    return [
        {key: value for key, value in item.items() if key in allowed_fields}
        for item in serialized
    ]


def list_preset_candidates(db, identity: dict) -> list[dict]:
    _require_admin(identity)
    rows = db.query(AiPreset, AiProvider).join(
        AiProvider, AiProvider.id == AiPreset.provider_id
    ).filter(
        AiPreset.deleted_at.is_(None),
        AiPreset.is_enabled.is_(True),
        AiProvider.deleted_at.is_(None),
        AiProvider.is_enabled.is_(True),
        AiProvider.provider_type == "direct",
    ).order_by(AiPreset.preset_name).all()
    return [{
        "id": preset.id,
        "preset_name": preset.preset_name,
        "model": preset.model,
        "provider_name": provider.name,
    } for preset, provider in rows]


def list_library_candidates(db, identity: dict) -> list[dict]:
    _require_admin(identity)
    rows = db.query(KnowledgeLibrary).filter(
        KnowledgeLibrary.deleted_at.is_(None),
        KnowledgeLibrary.status == "active",
    ).order_by(KnowledgeLibrary.name).all()
    return [{
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "description": row.description,
    } for row in rows]


def list_profile_logs(db, identity: dict, profile_id: int) -> list[dict]:
    _require_admin(identity)
    _profile(db, profile_id)
    rows = db.query(KnowledgeAiProfileLog).filter(
        KnowledgeAiProfileLog.profile_id == profile_id
    ).order_by(KnowledgeAiProfileLog.created_at.desc()).limit(100).all()
    return [{
        "id": row.id,
        "action": row.action,
        "actor_user_id": row.actor_user_id,
        "config_version": row.config_version,
        "detail": row.detail,
        "created_at": row.created_at,
    } for row in rows]


def test_profile_connection(
    db, identity: dict, profile_id: int, target_library_id: int, sample_text: str
) -> dict:
    """Exercise the frozen text preset without sending any knowledge sources."""
    _require_admin(identity)
    row = _profile(db, profile_id)
    target_exists = db.query(KnowledgeAiProfileTarget.id).filter(
        KnowledgeAiProfileTarget.profile_id == row.id,
        KnowledgeAiProfileTarget.library_id == target_library_id,
    ).first()
    if not target_exists:
        raise ValidationError("profile does not apply to the selected target library")
    preset = db.query(AiPreset).filter(AiPreset.id == row.preset_id).first()
    if not preset:
        raise ValidationError("profile preset is missing")
    result = chat(
        db,
        preset_name=preset.preset_name,
        messages=[{
            "role": "user",
            "content": (
                "这是知识库 AI 优化配置连通测试。不要补充外部事实；"
                "请用一句话确认能处理以下示例文本：\n" + sample_text
            ),
        }],
        caller_module="knowledge_ai_profile_test",
        caller_user_id=access.user_id(identity),
        snapshot_mode="metadata",
    )
    return {
        "status": "ok",
        "response": result["content"][:2000],
        "duration_ms": result["duration_ms"],
        "tokens_used": result.get("tokens_used"),
    }
