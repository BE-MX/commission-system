from app.ai.models import AiPreset, AiProvider
from app.design_image import model_catalog


def _configured_model(db, *, api_base: str, api_style: str | None = None):
    provider = AiProvider(
        name=f"provider-{api_base}",
        provider_type="direct",
        api_base=api_base,
        api_type="openai",
        api_key="encrypted",
        is_enabled=True,
        timeout_sec=300,
    )
    db.add(provider)
    db.flush()
    parameters = {"output_format": "png"}
    if api_style is not None:
        parameters["api_style"] = api_style
    preset = AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters=parameters,
        is_enabled=True,
    )
    db.add(preset)
    db.flush()
    return preset, provider


def test_model_catalog_accepts_only_exact_https_teamrouter_host(db):
    _configured_model(db, api_base="https://api.teamorouter.com")
    assert model_catalog.configured_model_row(db, "gpt-image-2") is not None


def test_model_catalog_rejects_teamrouter_lookalike_host(db):
    _configured_model(db, api_base="https://api.teamorouter.com.evil.test")
    assert model_catalog.configured_model_row(db, "gpt-image-2") is None


def test_model_catalog_rejects_wrong_api_style(db):
    _configured_model(db, api_base="https://api.teamorouter.com", api_style="chat")
    assert model_catalog.configured_model_row(db, "gpt-image-2") is None


def test_model_catalog_rejects_missing_teamrouter_api_key(db):
    _preset, provider = _configured_model(
        db, api_base="https://api.teamorouter.com/v1"
    )
    provider.api_key = None
    db.flush()

    assert model_catalog.configured_model_row(db, "gpt-image-2") is None


def test_model_catalog_rejects_non_api_base_path(db):
    _configured_model(
        db, api_base="https://api.teamorouter.com/v1/chat/completions"
    )

    assert model_catalog.configured_model_row(db, "gpt-image-2") is None


def test_gemini_model_requires_its_exact_preset_and_chat_style(db):
    preset, _provider = _configured_model(
        db, api_base="https://api.teamorouter.com", api_style="chat"
    )
    preset.preset_name = "design_image_generation_nano_banana_pro"
    preset.model = "gemini-3-pro-image"
    db.flush()

    configured = model_catalog.configured_model_row(db, "gemini-3-pro-image")

    assert configured is not None
    assert configured[1] is preset
