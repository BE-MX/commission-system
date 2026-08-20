"""Deterministic provenance for one customer-copilot evaluation cohort."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.agent_runtime import service as runtime_service
from app.agent_runtime.evaluation_cases import COPILOT_EVALUATION_CASES, COPILOT_EVALUATION_SUITE
from app.ai.models import AiPreset, AiProvider


def copilot_contract(db: Session) -> dict:
    profile = runtime_service.get_active_profile(db, "customer_order_copilot")
    settings = runtime_service.get_settings()
    preset = db.query(AiPreset).filter(
        AiPreset.preset_name == profile.model_preset,
        AiPreset.deleted_at.is_(None),
        AiPreset.is_enabled.is_(True),
    ).one_or_none()
    provider = db.get(AiProvider, preset.provider_id) if preset is not None else None
    ready = bool(
        preset is not None
        and provider is not None
        and provider.is_enabled
        and provider.deleted_at is None
        and provider.provider_type == "direct"
        and provider.api_type == "openai"
    )
    payload = {
        "suite": COPILOT_EVALUATION_SUITE,
        "cases": COPILOT_EVALUATION_CASES,
        "profile": {
            "id": profile.id,
            "version": profile.version,
            "runtime": profile.runtime,
            "prompt_hash": profile.prompt_hash,
            "actual_prompt_hash": hashlib.sha256(profile.system_prompt.encode("utf-8")).hexdigest(),
            "skills": profile.skill_manifest or [],
            "tools": profile.tool_allowlist or [],
            "limits": profile.limits_json or {},
            "policy": profile.policy_json or {},
            "output_schema": profile.output_schema or {},
        },
        "control_plane_limits": {
            "max_steps_per_run": settings.AGENT_RUNTIME_MAX_STEPS_PER_RUN,
            "run_timeout_seconds": settings.AGENT_RUNTIME_RUN_TIMEOUT_SECONDS,
            "daily_token_budget": settings.AGENT_RUNTIME_DAILY_TOKEN_BUDGET,
        },
        "preset": ({
            "id": preset.id,
            "name": preset.preset_name,
            "model": preset.model,
            "parameters": preset.parameters or {},
            "provider": {
                "id": provider.id,
                "type": provider.provider_type,
                "api_type": provider.api_type,
                "api_base": provider.api_base,
                "timeout_sec": provider.timeout_sec,
                "extra_headers": provider.extra_headers or {},
            } if provider is not None else None,
        } if preset is not None else None),
    }
    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")).hexdigest()
    return {
        "hash": digest,
        "ready": ready,
        "profile_id": profile.id,
        "profile_version": profile.version,
        "model": preset.model if preset is not None else None,
    }
