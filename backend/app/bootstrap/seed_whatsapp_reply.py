"""Prepare independent, disabled reply presets without changing translation."""

import logging

from app.ai.models import AiPreset, AiProvider
from app.core.config import get_settings
from app.core.database import SessionLocal


logger = logging.getLogger("commission.whatsapp_reply")


def seed_reply_presets(db) -> int:
    settings = get_settings()
    names = (settings.WHATSAPP_REPLY_PLANNER_PRESET, settings.WHATSAPP_REPLY_GENERATOR_PRESET)
    if len(set(names)) != 2 or set(names).intersection({settings.WHATSAPP_TRANSLATION_PRESET_NAME, settings.WHATSAPP_TRANSLATION_OUTGOING_PRESET_NAME}):
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
        (names[0], 1400, "WhatsApp 话术：片段复盘与检索词规划（独立预设，核验后手动启用）"),
        (names[1], 1800, "WhatsApp 话术：受知识约束的推荐回复（独立预设，核验后手动启用）"),
    ):
        # A deleted/customized name belongs to the administrator; never resurrect
        # or silently overwrite it during bootstrap.
        if db.query(AiPreset.id).filter(AiPreset.preset_name == name).first():
            continue
        parameters = {key: value for key, value in (base.parameters or {}).items()
                      if key in {"temperature", "top_p", "thinking", "reasoning_effort", "response_format"}}
        parameters["max_tokens"] = max_tokens
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
