import pytest

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



@pytest.mark.parametrize("api_base", ["https://api.teamorouter.cn", "https://custom-provider.test/v2", "https://image.test:8443/v1"])
@pytest.mark.parametrize("style", ["images", "chat"])
def test_new_model_and_provider_are_read_from_configuration(db, api_base, style):
    preset, provider = _configured_model(db, api_base=api_base, api_style=style)
    preset.model = "brand-new-image-model"
    preset.parameters = {"api_style": style, "studio": {"label": "Custom Image"}}
    db.flush()
    assert model_catalog.configured_model_row(db, preset.preset_name)[1] is preset
    assert model_catalog.public_model_options(db) == [
        {"id": preset.preset_name, "label": "Custom Image", "available": True,
         "sizes": ["1024x1024", "1024x1536", "1536x1024"], "qualities": ["low", "medium", "high"],
         "default_size": "1024x1024", "default_quality": "medium"},
    ]
    preset.model = "next-model"
    provider.api_base = "https://another-provider.test/v1"
    db.flush()
    assert model_catalog.configured_model_row(db, preset.preset_name)[1].model == "next-model"
    assert model_catalog.configured_model_row(db, "brand-new-image-model") is None


def test_arbitrary_preset_requires_explicit_studio_enrollment(db):
    preset, _ = _configured_model(db, api_base="https://provider.test")
    preset.preset_name = "private_ocr"
    db.flush()
    assert model_catalog.configured_model_row(db, preset.preset_name) is None
    preset.parameters = {"studio": {"enabled": True}}
    db.flush()
    assert model_catalog.configured_model_row(db, preset.preset_name)[1] is preset
    preset.parameters = {"studio": {"enabled": False}}
    db.flush()
    assert model_catalog.public_model_options(db) == []


def test_same_model_on_two_presets_never_selects_an_arbitrary_provider(db):
    first, provider = _configured_model(db, api_base="https://one.test")
    second = AiPreset(preset_name="design_image_generation_second", provider_id=provider.id,
                      model=first.model, parameters={}, is_enabled=True)
    db.add(second)
    db.flush()
    assert model_catalog.configured_model_row(db, first.model) is None
    assert model_catalog.configured_model_row(db, first.preset_name)[1] is first
    assert model_catalog.configured_model_row(db, second.preset_name)[1] is second
    assert len(model_catalog.public_model_options(db)) == 2


@pytest.mark.parametrize("target,field,value", [
    ("preset", "is_enabled", False), ("provider", "is_enabled", False),
    ("preset", "model", ""), ("provider", "provider_type", "accio_work"),
    ("provider", "api_type", "anthropic"), ("provider", "api_key", None),
    ("preset", "parameters", {"api_style": "unsupported"}),
    ("preset", "parameters", {"max_reference_images": "5"}),
    ("preset", "parameters", {"request_parameters": {"model": "override"}}),
])
def test_unusable_or_unsafe_configuration_is_not_callable(db, target, field, value):
    preset, provider = _configured_model(db, api_base="https://provider.test")
    setattr(preset if target == "preset" else provider, field, value)
    db.flush()
    assert model_catalog.configured_model_row(db, preset.preset_name) is None
    assert model_catalog.public_model_options(db)[0]["available"] is False


@pytest.mark.parametrize("base", ["http://provider.test", "https://user@provider.test", "https://provider.test?key=x", "https://provider.test#x", "https://provider.test:bad"])
def test_malformed_or_insecure_provider_url_is_not_callable(db, base):
    preset, _ = _configured_model(db, api_base=base)
    assert model_catalog.configured_model_row(db, preset.preset_name) is None


def test_deleted_preset_and_provider_are_not_callable(db):
    from app.core.time import beijing_now
    preset, provider = _configured_model(db, api_base="https://provider.test")
    provider.deleted_at = beijing_now()
    db.flush()
    assert model_catalog.configured_model_row(db, preset.preset_name) is None
    preset.deleted_at = beijing_now()
    db.flush()
    assert model_catalog.public_model_options(db) == []


@pytest.mark.parametrize("deleted", [False, True])
def test_unavailable_exact_preset_never_falls_back_to_a_model_alias(db, deleted):
    from app.core.time import beijing_now
    first, provider = _configured_model(db, api_base="https://one.test")
    first.is_enabled = False
    if deleted:
        first.deleted_at = beijing_now()
    second = AiPreset(preset_name="design_image_generation_second", provider_id=provider.id,
                      model=first.preset_name, parameters={}, is_enabled=True)
    db.add(second)
    db.flush()
    assert model_catalog.configured_model_row(db, first.preset_name) is None
    assert model_catalog.configured_model_row(db, second.preset_name)[1] is second
    assert model_catalog.configured_model_row(db, "missing", allow_legacy_model=False) is None
