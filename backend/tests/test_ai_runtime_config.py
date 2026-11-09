from types import SimpleNamespace

import pytest

from app.ai import image_service, preset_service
from app.ai.preset_config import text_request_parameters, validate_parameters
from app.ai.http_client import build_anthropic_body
from app.ai.models import AiPreset, AiProvider
from app.customer_image.service import _generation_preset_snapshot
from app.core.config import get_settings


@pytest.mark.parametrize("parameters", [
    [], {"studio": []}, {"studio": {"enabled": "true"}},
    {"api_style": []}, {"download_hosts": ["https://image.test/file"]},
    {"request_parameters": []}, {"request_parameters": {"messages": []}},
    {"request_parameters": {"n": 10}}, {"max_reference_images": True},
])
def test_invalid_parameters_fail_before_persistence(parameters):
    with pytest.raises(ValueError):
        validate_parameters(parameters)


@pytest.mark.parametrize("builder", [image_service._image_params, image_service._generation_params])
def test_image_extension_parameters_and_size_mapping_are_configurable(builder):
    preset = SimpleNamespace(model="future-model", parameters={
        "studio": {"enabled": True, "label": "Future"},
        "download_hosts": ["images.test"], "size_parameter": "aspect_ratio",
        "max_reference_images": 2, "rate_card": {},
        "request_parameters": {"vendor_option": "custom", "seed": 7},
    })
    body = builder(preset, "business prompt", size="1536x1024", quality="high")
    assert body == {"model": "future-model", "prompt": "business prompt",
                    "aspect_ratio": "3:2", "quality": "high", "vendor_option": "custom", "seed": 7}


def test_chat_image_extensions_do_not_leak_management_metadata():
    preset = SimpleNamespace(model="future-model", parameters={
        "api_style": "chat", "studio": {"enabled": True},
        "request_parameters": {"modalities": ["image", "text"]},
    })
    body = image_service._chat_image_payload(preset, "draw", [])
    assert body["model"] == "future-model"
    assert body["modalities"] == ["image", "text"]
    assert "studio" not in body and "api_style" not in body


def test_text_protocols_keep_metadata_local_and_cannot_override_business_input():
    params = {"studio": {"enabled": False}, "rate_card": {}, "model": "wrong",
              "messages": [], "temperature": 0.2, "request_parameters": {"top_p": 0.9}}
    assert text_request_parameters(params) == {"temperature": 0.2, "top_p": 0.9}
    body = build_anthropic_body("actual", [{"role": "user", "content": "hello"}], parameters=params)
    assert body["model"] == "actual"
    assert body["messages"][0]["content"] == "hello"
    assert body["top_p"] == 0.9
    assert "studio" not in body


def test_customer_image_model_uses_current_preset_and_not_a_fixed_name(db):
    provider = AiProvider(name="custom", provider_type="direct", api_type="openai",
                          api_base="https://provider.test/v1", api_key="encrypted", is_enabled=True)
    db.add(provider)
    db.flush()
    preset = AiPreset(preset_name=get_settings().CUSTOMER_IMAGE_PRESET_NAME,
                      provider_id=provider.id, model="future-image", is_enabled=True,
                      parameters={"size": "1024x1024"})
    db.add(preset)
    db.flush()
    assert _generation_preset_snapshot(db)[1] == "future-image"
    preset.model = "future-image-v2"
    db.flush()
    assert _generation_preset_snapshot(db)[1] == "future-image-v2"


def test_invalid_update_preserves_original_parameters(db):
    provider = AiProvider(name="custom", provider_type="direct", api_type="openai",
                          api_base="https://provider.test/v1", is_enabled=True)
    db.add(provider)
    db.flush()
    preset = AiPreset(preset_name="custom", provider_id=provider.id, model="original",
                      parameters={"temperature": 0.5}, is_enabled=True)
    db.add(preset)
    db.flush()
    with pytest.raises(ValueError):
        preset_service.update_preset(db, preset.id, {"model": "changed", "parameters": {"studio": []}})
    assert preset.model == "original"
    assert preset.parameters == {"temperature": 0.5}


def test_studio_test_uses_same_image_paths_even_with_a_custom_preset_name(db, monkeypatch):
    provider = AiProvider(name="custom", provider_type="direct", api_type="openai",
                          api_base="https://provider.test/v1", is_enabled=True)
    db.add(provider)
    db.flush()
    preset = AiPreset(preset_name="marketing_images", provider_id=provider.id, model="future-image",
                      parameters={"studio": {"enabled": True}}, is_enabled=True)
    db.add(preset)
    db.flush()
    calls = []
    def generate(**kwargs):
        calls.append(("generate", kwargs))
        return {"content": "image", "duration_ms": 1}
    def edit(**kwargs):
        calls.append(("edit", kwargs))
        return {"content": "image", "duration_ms": 1}
    monkeypatch.setattr(preset_service, "generate_image", generate)
    monkeypatch.setattr(preset_service, "edit_image", edit)
    assert preset_service.test_preset(db, preset.id, "draw")["status"] == "ok"
    assert preset_service.test_preset_with_image(db, preset.id, "edit", b"png", "image/png")["status"] == "ok"
    assert [kind for kind, _ in calls] == ["generate", "edit"]
    assert all(kwargs["preset_name"] == "marketing_images" for _, kwargs in calls)


def test_anthropic_nested_token_limit_is_the_effective_limit():
    body = build_anthropic_body("actual", [], parameters={"max_tokens": 1024, "request_parameters": {"max_tokens": 128}})
    assert body["max_tokens"] == 128


def test_nested_image_output_format_matches_returned_payload_mime():
    preset = SimpleNamespace(model="future-image", parameters={"output_format": "png", "request_parameters": {"output_format": "jpeg"}})
    request = image_service._generation_params(preset, "draw")
    response = image_service._extract_image_content({"data": [{"b64_json": "encoded"}]}, image_service._configured_output_format(preset))
    assert request["output_format"] == "jpeg"
    assert response == "data:image/jpeg;base64,encoded"


def test_nested_image_options_are_encoded_as_json_in_multipart():
    import httpx
    preset = SimpleNamespace(model="future-image", parameters={"request_parameters": {"vendor_options": {"mode": "a"}}})
    body = image_service._image_params(preset, "draw")
    request = httpx.Request("POST", "https://provider.test", data=body, files={"image": ("test.png", b"png")})
    encoded = request.read()
    assert b'{"mode": "a"}' in encoded
    assert image_service._generation_params(preset, "draw")["vendor_options"] == {"mode": "a"}


def test_custom_chat_quality_is_included_in_model_prompt():
    assert "ultra" in image_service._chat_image_prompt("draw", "2048x2048", "ultra")


def test_ratio_size_mapping_accepts_native_ratio_and_rejects_invalid_config():
    from app.ai.preset_config import validate_image_parameters
    preset = SimpleNamespace(model="future-image", parameters={"size_parameter": "aspect_ratio", "studio": {"sizes": ["16:9"]}})
    validate_image_parameters(preset.parameters, preset.model)
    assert image_service._generation_params(preset, "draw", size="16:9")["aspect_ratio"] == "16:9"
    with pytest.raises(ValueError):
        validate_image_parameters({"size_parameter": "aspect_ratio", "studio": {"sizes": ["auto"]}}, "future-image")
