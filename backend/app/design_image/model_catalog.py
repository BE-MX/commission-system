"""Server-owned image model choices for Design Image Studio.

Each choice maps to an independent AI preset so provider credentials, request
style, parameters, and pricing remain configuration-owned.  The browser only
sends a catalog model ID; it can never choose an arbitrary preset or provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.ai.models import AiPreset, AiProvider


ImageModelId = Literal[
    "gpt-image-2",
    "grok-image-2",
    "gemini-3-pro-image",
    "gemini-3.1-flash-image",
]

DEFAULT_IMAGE_MODEL_ID: ImageModelId = "gpt-image-2"
TEAMROUTER_HOST = "api.teamorouter.com"


@dataclass(frozen=True, slots=True)
class ImageModelOption:
    id: ImageModelId
    label: str
    preset_name: str
    api_style: Literal["images", "chat"]


IMAGE_MODEL_OPTIONS: tuple[ImageModelOption, ...] = (
    ImageModelOption(
        id="gpt-image-2",
        label="GPT Image 2",
        preset_name="design_image_generation",
        api_style="images",
    ),
    ImageModelOption(
        id="grok-image-2",
        label="Grok Image 2",
        preset_name="design_image_generation_grok_image_2",
        api_style="images",
    ),
    ImageModelOption(
        id="gemini-3-pro-image",
        label="Nano Banana Pro",
        preset_name="design_image_generation_nano_banana_pro",
        api_style="chat",
    ),
    ImageModelOption(
        id="gemini-3.1-flash-image",
        label="Nano Banana 2",
        preset_name="design_image_generation_nano_banana_2",
        api_style="chat",
    ),
)
_OPTION_BY_ID = {option.id: option for option in IMAGE_MODEL_OPTIONS}


def get_model_option(model_id: str) -> ImageModelOption | None:
    return _OPTION_BY_ID.get(model_id)


def _is_teamrouter_provider(provider: AiProvider) -> bool:
    try:
        parsed = urlsplit(provider.api_base)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port if parsed.port is not None else 443
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and host == TEAMROUTER_HOST
        and port == 443
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") in {"", "/v1"}
        and not parsed.query
        and not parsed.fragment
        and provider.provider_type == "direct"
        and (provider.api_type or "openai") == "openai"
        and bool(provider.api_key)
        and bool(provider.is_enabled)
        and provider.deleted_at is None
    )


def _matches_option(
    option: ImageModelOption,
    preset: AiPreset,
    provider: AiProvider,
) -> bool:
    if preset.parameters is not None and not isinstance(preset.parameters, dict):
        return False
    parameters = preset.parameters if isinstance(preset.parameters, dict) else {}
    configured_style = str(parameters.get("api_style", "")).strip().lower()
    style_matches = (
        configured_style == "chat"
        if option.api_style == "chat"
        else configured_style in {"", "images"}
    )
    return (
        preset.preset_name == option.preset_name
        and preset.model == option.id
        and bool(preset.is_enabled)
        and preset.deleted_at is None
        and style_matches
        and _is_teamrouter_provider(provider)
    )


def configured_model_rows(
    db: Session,
) -> dict[ImageModelId, tuple[AiPreset, AiProvider]]:
    preset_names = [option.preset_name for option in IMAGE_MODEL_OPTIONS]
    rows = (
        db.query(AiPreset, AiProvider)
        .join(AiProvider, AiProvider.id == AiPreset.provider_id)
        .filter(AiPreset.preset_name.in_(preset_names))
        .all()
    )
    configured: dict[ImageModelId, tuple[AiPreset, AiProvider]] = {}
    for preset, provider in rows:
        option = next(
            (
                candidate
                for candidate in IMAGE_MODEL_OPTIONS
                if candidate.preset_name == preset.preset_name
            ),
            None,
        )
        if option is not None and _matches_option(option, preset, provider):
            configured[option.id] = (preset, provider)
    return configured


def public_model_options(db: Session) -> list[dict]:
    configured = configured_model_rows(db)
    return [
        {
            "id": option.id,
            "label": option.label,
            "available": option.id in configured,
        }
        for option in IMAGE_MODEL_OPTIONS
    ]


def configured_model_row(
    db: Session,
    model_id: str,
) -> tuple[ImageModelOption, AiPreset, AiProvider] | None:
    option = get_model_option(model_id)
    if option is None:
        return None
    row = configured_model_rows(db).get(option.id)
    if row is None:
        return None
    preset, provider = row
    return option, preset, provider
