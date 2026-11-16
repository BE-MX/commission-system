"""Published model access, generation admission and private session management."""

import hashlib
import json
from datetime import timedelta

from sqlalchemy.orm import noload

from app.ai.chat_config import chat_options
from app.ai.models import AiPreset, AiProvider
from app.ai.preset_config import is_image_preset, is_studio_preset
from app.ai.service import freeze_text_call_config
from app.ai_chat import service
from app.ai_chat.models import AiChatAttachment, AiChatMessage, AiChatSession
from app.auth.models import ArkRole, ArkUser, ArkUserRole
from app.core.config import get_settings
from app.core.time import beijing_now


class WorkspaceError(ValueError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def list_role_options(db):
    return [{"name": name, "label": label} for name, label in db.query(ArkRole.name, ArkRole.label).order_by(ArkRole.id).all()]


def _roles(db, owner_id):
    active = db.query(ArkUser.id).filter(
        ArkUser.id == owner_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)
    ).with_for_update(read=True).first()
    if not active:
        raise WorkspaceError("账号不可用，请重新登录", 403)
    return {name for (name,) in db.query(ArkRole.name).join(
        ArkUserRole, ArkUserRole.role_id == ArkRole.id
    ).filter(ArkUserRole.user_id == owner_id).with_for_update(read=True).all()}


def _available(preset, provider, roles):
    parameters = preset.parameters or {}
    if (preset.deleted_at is not None or not preset.is_enabled or not (preset.model or "").strip()
            or provider.deleted_at is not None or not provider.is_enabled
            or provider.provider_type != "direct" or provider.api_type not in {"openai", "anthropic"}
            or not isinstance(parameters, dict)
            or is_image_preset(preset) or is_studio_preset(preset)
            or "api_style" in parameters
            or preset.preset_name in {"expo_wig_composite", "customer_image_generation", "swatch_image_generation"}):
        return False
    try:
        options = chat_options(preset)
    except ValueError:
        return False  # Invalid management metadata must never publish a model.
    return options["enabled"] and (not options["allowed_roles"]
        or "super_admin" in roles or bool(roles.intersection(options["allowed_roles"])))


def public_model(snapshot):
    if not snapshot:
        return None
    return {key: snapshot[key] for key in ("preset_id", "label", "model", "vision")}


def _version(preset, provider):
    # Store only a digest. Prompts, endpoints, keys and parameters remain private.
    data = [preset.preset_name, preset.model, preset.system_prompt, preset.parameters,
            provider.id, provider.api_base, provider.api_type, provider.api_key,
            provider.extra_headers, provider.runtime_config, provider.timeout_sec]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _snapshot(preset, provider):
    options = chat_options(preset)
    return {"preset_id": preset.id, "preset_name": preset.preset_name,
            "label": options["label"], "model": preset.model, "vision": options["vision"],
            "config_version": _version(preset, provider)}


def list_models(db, owner_id):
    roles = _roles(db, owner_id)
    rows = db.query(AiPreset, AiProvider).join(AiProvider, AiProvider.id == AiPreset.provider_id).order_by(AiPreset.id).all()
    rows.sort(key=lambda pair: pair[0].preset_name != service.PRESET_NAME)
    return [public_model(_snapshot(p, provider)) for p, provider in rows if _available(p, provider, roles)]


def usage(db, owner_id):
    now = beijing_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.query(AiChatMessage.id).join(AiChatSession).filter(
        AiChatSession.owner_user_id == owner_id, AiChatMessage.role == "assistant",
        AiChatMessage.created_at >= start, AiChatMessage.created_at < start + timedelta(days=1),
    ).count()
    limit = get_settings().AI_CHAT_DAILY_TURN_LIMIT
    return {"used": count, "limit": limit, "remaining": max(0, limit - count)}


def get_config(db, owner_id, *, include_diagnostic=False):
    models = list_models(db, owner_id)
    if models:
        result = {"configured": True, "message": None, "model": models[0]["model"]}
    else:
        result = service.get_config(db, include_diagnostic=include_diagnostic)
        result["configured"] = False
        result["model"] = None
        result["message"] = "暂无可用的聊天模型，请联系管理员"
    return {**result, "models": models, "default_preset_id": models[0]["preset_id"] if models else None,
            "usage": usage(db, owner_id)}


def _resolve_pair(db, owner_id, preset_id=None):
    roles = _roles(db, owner_id)
    if preset_id is None:
        models = list_models(db, owner_id)
        if not models:
            raise WorkspaceError("暂无可用的聊天模型，请联系管理员", 503)
        preset_id = models[0]["preset_id"]
    pair = db.query(AiPreset, AiProvider).join(AiProvider, AiProvider.id == AiPreset.provider_id).filter(
        AiPreset.id == preset_id
    ).populate_existing().with_for_update(read=True).first()
    if not pair or not _available(*pair, roles):
        raise WorkspaceError("所选模型已不可用或无权使用，请重新选择", 403)
    return pair


def resolve_model(db, owner_id, preset_id=None):
    return _snapshot(*_resolve_pair(db, owner_id, preset_id))


def validate_generation(db, owner_id, snapshot):
    preset, provider = _resolve_pair(db, owner_id, snapshot["preset_id"])
    current = _snapshot(preset, provider)
    if current["config_version"] != snapshot["config_version"]:
        raise WorkspaceError("模型配置已更新，请重新生成")
    return freeze_text_call_config(preset, provider)


def _lock_user(db, owner_id):
    # Consistent user -> session lock order serializes quota across all devices/sessions.
    user = db.query(ArkUser).options(noload("*")).filter(
        ArkUser.id == owner_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)
    ).with_for_update().first()
    if not user:
        raise WorkspaceError("账号不可用，请重新登录", 403)


def _lock_session(db, owner_id, session_id):
    _lock_user(db, owner_id)
    session = db.query(AiChatSession).filter(
        AiChatSession.id == session_id, AiChatSession.owner_user_id == owner_id,
        AiChatSession.deleted_at.is_(None),
    ).populate_existing().with_for_update().first()
    if not session:
        raise service.ResourceNotFoundError("资源不存在")
    return session


def _admit(db, owner_id, session_id):
    if db.query(AiChatMessage.id).filter_by(session_id=session_id, status="streaming").first():
        raise WorkspaceError("本会话仍在生成，请等待结束或停止后刷新")
    if usage(db, owner_id)["remaining"] <= 0:
        raise WorkspaceError("今日对话次数已用完，北京时间零点恢复", 429)


def _check_images(db, session_id, snapshot, attachment_ids=()):
    if snapshot["vision"]:
        return
    # Reject explicitly rather than silently dropping images from history on a model switch.
    query = db.query(AiChatAttachment.id).filter(
        AiChatAttachment.session_id == session_id, AiChatAttachment.attachment_type == "image",
        (AiChatAttachment.status == "attached") | AiChatAttachment.id.in_(attachment_ids),
    )
    if query.first():
        raise WorkspaceError("本会话包含图片，请选择支持图片的模型，或新建纯文字对话", 400)


def begin_turn(db, owner_id, session_id, request):
    try:
        session = _lock_session(db, owner_id, session_id)
        existing = service._existing_turn(db, session_id, request.request_id)
        if existing:
            return service.begin_turn(db, owner_id, session_id, request)
        _admit(db, owner_id, session_id)
        snapshot = resolve_model(db, owner_id, request.preset_id or session.selected_preset_id)
        _check_images(db, session_id, snapshot, request.attachment_ids)
        return service.begin_turn(db, owner_id, session_id, request, model_snapshot=snapshot)
    except Exception:
        db.rollback()
        raise


def begin_retry(db, owner_id, assistant_id, request):
    try:
        _lock_user(db, owner_id)
        original = service.get_message(db, assistant_id, owner_id)
        session = _lock_session(db, owner_id, original.session_id)
        existing = db.query(AiChatMessage).filter_by(session_id=session.id, request_id=request.request_id).first()
        if existing:
            return service.begin_retry(db, owner_id, assistant_id, request)
        _admit(db, owner_id, session.id)
        snapshot = resolve_model(db, owner_id, request.preset_id or session.selected_preset_id)
        _check_images(db, session.id, snapshot)
        return service.begin_retry(db, owner_id, assistant_id, request, model_snapshot=snapshot)
    except Exception:
        db.rollback()
        raise


def rename_session(db, owner_id, session_id, title):
    row = _lock_session(db, owner_id, session_id)
    row.title = title
    row.updated_at = beijing_now()
    db.commit()
    return row


def delete_session(db, owner_id, session_id):
    row = _lock_session(db, owner_id, session_id)
    if db.query(AiChatMessage.id).filter_by(session_id=session_id, status="streaming").first():
        raise WorkspaceError("请先停止生成，刷新后再删除会话")
    row.deleted_at = row.updated_at = beijing_now()
    db.commit()
