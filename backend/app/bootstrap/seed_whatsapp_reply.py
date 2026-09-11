"""Prepare independent, disabled reply presets without changing translation."""

import logging

from app.ai.models import AiPreset, AiProvider
from app.core.config import get_settings
from app.core.database import SessionLocal


logger = logging.getLogger("commission.whatsapp_reply")


def reply_parameters(base_parameters, max_tokens, api_type="openai") -> dict:
    parameters = {key: value for key, value in (base_parameters or {}).items()
                  if key in {"temperature", "top_p", "thinking", "reasoning_effort"}}
    parameters["max_tokens"] = max_tokens
    if api_type == "openai":
        # Schema is supplied per phase. Never inherit a translation-only schema
        # or rely solely on prompt wording to suppress Markdown fences.
        parameters["response_format"] = {"type": "json_object"}
    return parameters


def seed_reply_presets(db) -> int:
    settings = get_settings()
    names = (settings.WHATSAPP_REPLY_GENERATOR_PRESET,)
    if set(names).intersection({settings.WHATSAPP_TRANSLATION_PRESET_NAME, settings.WHATSAPP_TRANSLATION_OUTGOING_PRESET_NAME}):
        raise ValueError("reply presets must be independent")
    base = db.query(AiPreset).join(AiProvider, AiPreset.provider_id == AiProvider.id).filter(
        AiPreset.preset_name == settings.WHATSAPP_TRANSLATION_PRESET_NAME,
        AiPreset.deleted_at.is_(None), AiPreset.is_enabled.is_(True),
        AiProvider.deleted_at.is_(None), AiProvider.is_enabled.is_(True),
        AiProvider.provider_type == "direct",
    ).first()
    if base is None:
        return 0
    created = 0
    for name, max_tokens, description in (
        (names[0], 3200, "WhatsApp 话术：完整对话生成与可选复盘（独立预设，核验后手动启用）"),
    ):
        # A deleted/customized name belongs to the administrator; never resurrect
        # or silently overwrite it during bootstrap.
        if db.query(AiPreset.id).filter(AiPreset.preset_name == name).first():
            continue
        provider = db.get(AiProvider, base.provider_id)
        parameters = reply_parameters(base.parameters, max_tokens, provider.api_type)
        db.add(AiPreset(
            preset_name=name, provider_id=base.provider_id, model=base.model,
            parameters=parameters, system_prompt="", description=description, is_enabled=False,
        ))
        created += 1
    db.commit()
    return created


def auto_init_reply_presets():
    try:
        with SessionLocal() as db:
            created = seed_reply_presets(db)
            if created:
                logger.info("prepared disabled reply presets count=%d", created)
    except Exception as exc:
        logger.warning("reply preset preparation failed error_type=%s", type(exc).__name__)
        print(f"[WhatsApp reply] preset preparation failed error_type={type(exc).__name__}", flush=True)
