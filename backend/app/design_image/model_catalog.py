"""Database-owned Studio choices; clients select an approved preset, not a provider."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiProvider
from app.ai.preset_config import is_studio_preset, validate_image_parameters, image_api_style, studio_generation_options

DEFAULT_IMAGE_MODEL_ID = "design_image_generation"


@dataclass(frozen=True, slots=True)
class ImageModelOption:
    id: str
    label: str
    preset_name: str
    api_style: str


def _is_allowed_provider(provider: AiProvider) -> bool:
    try:
        parsed = urlsplit(provider.api_base or "")
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and bool(parsed.hostname)
        and (port is None or 1 <= port <= 65535)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and provider.provider_type == "direct"
        and (provider.api_type or "openai") == "openai"
        and bool(provider.api_key or any(
            key.lower() in {"authorization", "api-key", "x-api-key"} and value
            for key, value in (provider.extra_headers or {}).items()
        ))
        and bool(provider.is_enabled)
        and provider.deleted_at is None
    )


def _rows(db: Session):
    return (
        db.query(AiPreset, AiProvider)
        .join(AiProvider, AiProvider.id == AiPreset.provider_id)
        .filter(AiPreset.deleted_at.is_(None))
        .order_by(AiPreset.id)
        .all()
    )


def _available(preset, provider) -> bool:
    parameters = preset.parameters or {}
    try:
        validate_image_parameters(parameters, preset.model)
    except ValueError:
        return False
    return (
        is_studio_preset(preset)
        and bool(preset.is_enabled)
        and bool((preset.model or "").strip())
        and isinstance(parameters, dict)
        and image_api_style(parameters) in {"images", "chat"}
        and parameters.get("n", 1) == 1
        and not parameters.get("stream", False)
        and _is_allowed_provider(provider)
    )


def _option(preset) -> ImageModelOption:
    parameters = preset.parameters or {}
    studio = parameters.get("studio") or {}
    label = studio.get("label")
    if not isinstance(label, str) or not label.strip():
        label = preset.model or preset.preset_name
    return ImageModelOption(preset.preset_name, label, preset.preset_name,
                            image_api_style(parameters))


def configured_model_rows(db: Session) -> dict[str, tuple[AiPreset, AiProvider]]:
    return {preset.preset_name: (preset, provider) for preset, provider in _rows(db)
            if _available(preset, provider)}


def public_model_options(db: Session) -> list[dict]:
    return [
        {"id": preset.preset_name, "label": _option(preset).label,
         "available": _available(preset, provider),
         **(studio_generation_options(preset.parameters) if _available(preset, provider) else {})}
        for preset, provider in _rows(db) if is_studio_preset(preset)
    ]


def configured_model_row(db: Session, model_id: str, *, allow_legacy_model: bool = True):
    configured = configured_model_rows(db)
    row = configured.get(model_id)
    if row is None and (not allow_legacy_model or db.query(AiPreset).filter(
        AiPreset.preset_name == model_id
    ).first() is not None):
        return None
    if row is None:
        # Persisted old confirmations contain model names. Never choose arbitrarily
        # when multiple approved presets now use the same model.
        matches = [item for item in configured.values() if item[0].model == model_id]
        row = matches[0] if len(matches) == 1 else None
    if row is None:
        return None
    preset, provider = row
    return _option(preset), preset, provider
