"""Reuse a known enabled text preset; never guess from an image-only provider."""

import logging

from app.ai.models import AiPreset, AiProvider
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


def auto_init_fx_settlement_preset() -> None:
    try:
        with SessionLocal() as db:
            if db.query(AiPreset).filter(AiPreset.preset_name == "fx_settlement_advisor", AiPreset.deleted_at.is_(None)).first():
                return
            source = None
            for name in ("order_intelligence_brief", "whatsapp_text_translation", "insight_daily_organize"):
                source = db.query(AiPreset).join(AiProvider, AiProvider.id == AiPreset.provider_id).filter(
                    AiPreset.preset_name == name, AiPreset.is_enabled.is_(True), AiPreset.deleted_at.is_(None),
                    AiProvider.provider_type == "direct", AiProvider.is_enabled.is_(True), AiProvider.deleted_at.is_(None),
                ).first()
                if source:
                    break
            if source is None:
                logger.warning("FX AI preset not created: no known enabled text preset")
                print("[FX] AI preset not created: configure a text provider in AI settings", flush=True)
                return
            parameters = {key: value for key, value in (source.parameters or {}).items() if key in {"temperature", "top_p"}}
            parameters["max_tokens"] = 2400
            db.add(AiPreset(
                preset_name="fx_settlement_advisor", provider_id=source.provider_id, model=source.model,
                system_prompt="", parameters=parameters, is_enabled=True,
                description="结汇决策：基于行情和现金流约束选择并解释可行方案",
            ))
            db.commit()
    except Exception as exc:
        logger.warning("FX AI preset initialization failed: %s", type(exc).__name__)
        print(f"[FX] AI preset initialization failed: {type(exc).__name__}", flush=True)
