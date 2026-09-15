"""Trusted, in-process text configuration snapshots for external site calls."""

from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import select
from app.ai.models import AiPreset, AiProvider

TEXT_PARAMETERS = {"max_tokens", "temperature", "top_p", "stop", "frequency_penalty", "presence_penalty"}


@dataclass(frozen=True)
class TextChatSnapshot:
    preset: SimpleNamespace = field(repr=False)
    provider: SimpleNamespace = field(repr=False)


def prepare_text_chat(db, preset_name: str, max_output_tokens: int) -> TextChatSnapshot:
    """Take current reads inside the caller's short admission transaction.

    Only trusted server code can construct/pass this object, never HTTP input.
    Copies survive ORM expiration and admin edits after admission commits.
    """
    preset = db.execute(select(AiPreset).where(
        AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None),
        AiPreset.is_enabled.is_(True),
    ).with_for_update(read=True).execution_options(populate_existing=True)).scalar_one_or_none()
    if preset is None:
        raise ValueError("text preset unavailable")
    provider = db.execute(select(AiProvider).where(
        AiProvider.id == preset.provider_id, AiProvider.deleted_at.is_(None),
        AiProvider.is_enabled.is_(True), AiProvider.provider_type == "direct",
    ).with_for_update(read=True).execution_options(populate_existing=True)).scalar_one_or_none()
    if provider is None or provider.api_type not in {"openai", "anthropic"}:
        raise ValueError("text provider unavailable")
    parameters = deepcopy(preset.parameters or {})
    if not isinstance(parameters, dict) or set(parameters) - TEXT_PARAMETERS:
        raise ValueError("preset has unsupported text parameters")
    configured = parameters.get("max_tokens", max_output_tokens)
    if type(configured) is not int or configured <= 0 or max_output_tokens <= 0:
        raise ValueError("invalid output limit")
    parameters["max_tokens"] = min(configured, max_output_tokens)
    return TextChatSnapshot(
        preset=SimpleNamespace(id=preset.id, preset_name=preset.preset_name, model=preset.model,
                               system_prompt=preset.system_prompt, parameters=parameters),
        provider=SimpleNamespace(**{key: deepcopy(getattr(provider, key)) for key in (
            "id", "name", "provider_type", "api_type", "api_base", "api_key", "extra_headers", "timeout_sec",
        )}),
    )
