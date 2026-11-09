"""Configuration changes must reach the wire without escaping business limits."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.ai import call_service, image_service, provider_service, preset_service
from app.ai.http_client import build_headers, build_chat_url, build_image_url, build_anthropic_body, apply_token_parameter
from app.ai.models import AiProvider, AiPreset
from app.ai.provider_config import (
    validate_provider_options, validate_extra_headers, request_timeout, image_request_timeout,
    public_extra_headers, MASKED_HEADER_VALUE,
)
from app.ai.preset_config import text_request_parameters
from app.ai.schemas import ProviderCreate


@pytest.fixture
def configured(db, monkeypatch):
    provider = AiProvider(name="runtime-settings", provider_type="direct", api_type="openai",
                          api_base="https://provider.test/api", api_key="encrypted", timeout_sec=60,
                          is_enabled=True)
    db.add(provider)
    db.flush()
    preset = AiPreset(preset_name="runtime_settings", provider_id=provider.id, model="future-model",
                      parameters={}, is_enabled=True)
    db.add(preset)
    db.commit()
    for module in (call_service, image_service, provider_service):
        monkeypatch.setattr(module, "decrypt_key", lambda _: "test-secret")
    return provider, preset


def test_text_update_reaches_url_tokens_and_bounded_multimodal_timeout(db, configured, monkeypatch):
    provider, preset = configured
    calls = []
    monkeypatch.setattr(call_service, "post_json", lambda url, **kw: calls.append((url, kw)) or {
        "choices": [{"message": {"content": "ok"}}], "usage": {},
    })
    provider_service.update_provider(db, provider.id, {"runtime_config": {
        "chat_path": "custom/chat", "multimodal_timeout_sec": 37,
        "token_parameter": "max_completion_tokens", "connect_timeout_sec": 4,
    }})
    preset_service.update_preset(db, preset.id, {"parameters": {
        "max_tokens": 100, "transport": {"multimodal_timeout_sec": 25},
    }})
    call_service.chat(db, preset.preset_name, [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}},
    ]}], "test", timeout_sec=12, enforce_total_timeout=True)
    url, kw = calls[-1]
    assert url == "https://provider.test/api/custom/chat"
    assert kw["timeout_sec"] == 12
    assert kw["enforce_total_timeout"] is True
    assert kw["transport"]["connect_timeout_sec"] == 4
    assert kw["body"]["max_completion_tokens"] == 100
    assert "max_tokens" not in kw["body"] and "transport" not in kw["body"]


def test_image_config_is_frozen_hashed_and_used_for_transport(db, configured, monkeypatch):
    provider, preset = configured
    old = image_service.build_image_config_version(preset, provider)
    provider.runtime_config = {"image_generation_path": "render", "image_timeout_sec": 32,
                               "image_max_attempts": 2, "write_timeout_sec": 8}
    preset.parameters = {"transport": {"image_timeout_sec": 22}, "output_format": "png"}
    preset.system_prompt = "Preserve identity"
    db.commit()
    assert old != image_service.build_image_config_version(preset, provider)
    frozen_preset, frozen_provider = image_service._freeze_image_call_config(preset, provider)
    provider.runtime_config["image_timeout_sec"] = 999
    assert frozen_provider.runtime_config["image_timeout_sec"] == 32
    db.expire(provider)
    captured = []
    def send(build_request, timeout, module, label, **kwargs):
        with httpx.Client() as client:
            request = build_request(client)
        import json
        captured.append((request.url, json.loads(request.content), timeout, kwargs))
        return image_service.ImageTransportResult({"data": [{"b64_json": "aW1hZ2U="}]}, 1, None)
    monkeypatch.setattr(image_service, "_send_with_retry", send)
    image_service.generate_image(db, preset.preset_name, "Draw a cup", "test")
    url, body, timeout, kwargs = captured[0]
    assert str(url) == "https://provider.test/api/render"
    assert body["prompt"] == "Preserve identity\n\nDraw a cup"
    assert timeout == 22 and kwargs["options"]["image_max_attempts"] == 2
    assert "transport" not in body


def test_image_retry_disabled_status_and_configured_backoff(monkeypatch):
    original_client = httpx.Client
    calls, sleeps = [], []
    def respond(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"data": []})
    monkeypatch.setattr(image_service.httpx, "Client", lambda **kw: original_client(
        **kw, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(image_service.time, "sleep", sleeps.append)
    build = lambda client: client.build_request("POST", "https://provider.test/render", json={})
    result = image_service._send_with_retry(build, 20, "test", "image", options={
        "image_max_attempts": 2, "image_retry_backoff_sec": 0.25,
        "connect_timeout_sec": 3, "write_timeout_sec": 7,
    })
    assert result.attempts == 2 and sleeps == [0.25]
    assert calls[0].extensions["timeout"] == {"connect": 3, "read": 20, "write": 7, "pool": 20}
    calls.clear()
    with pytest.raises(httpx.HTTPStatusError):
        image_service._send_with_retry(build, 20, "test", "image", options={"image_retry_statuses": []})
    assert len(calls) == 1


def test_headers_preserve_protocol_version_and_use_encrypted_key_slot(configured):
    provider, _ = configured
    provider.api_type = "anthropic"
    provider.extra_headers = {"anthropic-version": "custom-version"}
    headers = build_headers(provider, "secret")
    assert headers["anthropic-version"] == "custom-version" and headers["x-api-key"] == "secret"
    provider.runtime_config = {"auth_header": "X-Token", "auth_scheme": "Token"}
    assert build_headers(provider, "secret")["X-Token"] == "Token secret"


def test_header_secrets_are_hidden_and_existing_values_survive_edit(db, configured):
    provider, _ = configured
    provider.extra_headers = {"Authorization": "legacy-secret", "X-Project": "ark"}
    db.commit()
    visible = public_extra_headers(provider.extra_headers)
    assert visible == {"Authorization": MASKED_HEADER_VALUE, "X-Project": "ark"}
    provider_service.update_provider(db, provider.id, {"extra_headers": visible, "timeout_sec": 80})
    assert provider.extra_headers["Authorization"] == "legacy-secret"
    with pytest.raises(ValueError):
        validate_extra_headers({"Authorization": "new-plaintext-secret"})


def test_anthropic_keeps_business_constraints_without_duplicate_preset():
    body = build_anthropic_body("model", [
        {"role": "system", "content": "Preset"}, {"role": "system", "content": "Business constraint"},
        {"role": "user", "content": "hello"},
    ], system_prompt="Preset")
    assert body["system"] == "Preset\n\nBusiness constraint"
    assert body["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.parametrize("options", [
    {"chat_path": "https://evil.test"}, {"image_edit_path": "../secret"},
    {"image_max_attempts": 10}, {"image_retry_statuses": [504]},
    {"auth_header": "X-Header\r\n"}, {"image_timeout_sec": -1},
    {"image_proxy": "http://user:secret@proxy.test"}, {"unused_typo": 1},
])
def test_invalid_settings_rejected_at_api_boundary(options):
    with pytest.raises(ValueError):
        ProviderCreate(name="test", provider_type="direct", api_base="https://provider.test",
                       runtime_config=options)


def test_limits_and_internal_parameters(configured):
    provider, preset = configured
    provider.runtime_config = {"image_timeout_sec": 999, "multimodal_timeout_sec": 5}
    assert request_timeout(provider, "multimodal") == 5
    assert image_request_timeout(provider, preset, "expo") == 300
    assert text_request_parameters({"transport": {"timeout_sec": 8},
                                    "workflow": {"max_attempts": 1}, "test_mode": "text",
                                    "temperature": 0.2}) == {"temperature": 0.2}


def test_image_test_mode_works_when_not_listed_in_studio(db, configured, monkeypatch):
    _, preset = configured
    preset.parameters = {"studio": {"enabled": False}, "test_mode": "image", "max_reference_images": 1}
    db.commit()
    monkeypatch.setattr(preset_service, "generate_image", lambda **kw: {"content": "image"})
    assert preset_service.test_preset(db, preset.id, "draw")["status"] == "ok"
    result = preset_service.test_preset_with_image(db, preset.id, "edit", b"one", "image/png", b"two", "image/png")
    assert result["status"] == "error" and "上限" in result["response"]


def test_probe_uses_explicit_model_parameters_not_first_image_preset(db, configured, monkeypatch):
    provider, preset = configured
    preset.parameters = {"test_mode": "image"}
    db.commit()
    assert provider_service.test_provider(db, provider.id)["status"] == "error"
    provider.runtime_config = {"test_model": "probe-model", "test_message": "ping", "test_max_tokens": 19,
                               "token_parameter": "max_completion_tokens", "chat_path": "probe"}
    db.commit()
    calls = []
    monkeypatch.setattr(provider_service, "post_json", lambda url, **kw: calls.append((url, kw)) or {
        "choices": [{"message": {"content": "ok"}}],
    })
    assert provider_service.test_provider(db, provider.id)["status"] == "ok"
    assert calls[0][0] == "https://provider.test/api/probe"
    assert calls[0][1]["body"] == {"model": "probe-model", "messages": [{"role": "user", "content": "ping"}],
                                   "max_completion_tokens": 19}


def test_full_image_url_uses_correct_operation():
    assert build_image_url("https://provider.test/v1/images/generations", "edits") == "https://provider.test/v1/images/edits"


def test_target_token_parameter_wins_instead_of_inflating_output(configured):
    provider, _ = configured
    provider.runtime_config = {"token_parameter": "max_completion_tokens"}
    assert apply_token_parameter({"max_tokens": 1000000, "max_completion_tokens": 500}, provider) == {"max_completion_tokens": 500}


def test_configured_auth_header_cannot_hold_plaintext_and_is_masked(db, configured):
    provider, _ = configured
    with pytest.raises(ValueError):
        provider_service.update_provider(db, provider.id, {
            "runtime_config": {"auth_header": "X-Credential"},
            "extra_headers": {"X-Credential": "plain-secret"},
        })
    assert public_extra_headers({"X-Credential": "legacy"}, "X-Credential") == {"X-Credential": MASKED_HEADER_VALUE}
    assert provider.runtime_config is None


@pytest.mark.parametrize("proxy", ["https://proxy.test/?token=secret", "https://proxy.test/#secret", "https://proxy.test/path"])
def test_proxy_endpoint_cannot_contain_hidden_credentials(proxy):
    with pytest.raises(ValueError):
        validate_provider_options({"image_proxy": proxy})


def test_parameter_fallback_shares_configured_attempt_budget(monkeypatch):
    calls = []
    def reject(*args, **kwargs):
        calls.append(kwargs)
        response = httpx.Response(400, json={"error": {"message": "Unknown parameter: input_fidelity", "param": "input_fidelity"}},
                                  request=httpx.Request("POST", "https://provider.test/edit"))
        error = httpx.HTTPStatusError("unsupported", request=response.request, response=response)
        error.provider_attempt_count = 1
        raise error
    monkeypatch.setattr(image_service, "_post_image_edits_once", reject)
    with pytest.raises(httpx.HTTPStatusError):
        image_service._post_image_edits("https://provider.test/edit", {}, {"input_fidelity": "high"}, [], 20, "test",
                                        options={"image_max_attempts": 1})
    assert len(calls) == 1


def test_fallback_then_timeout_counts_both_provider_calls(monkeypatch):
    attempts = []
    def send(*args, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            response = httpx.Response(400, json={"error": {"message": "Unknown parameter: input_fidelity", "param": "input_fidelity"}},
                                      request=httpx.Request("POST", "https://provider.test/edit"))
            error = httpx.HTTPStatusError("unsupported", request=response.request, response=response)
        else:
            error = TimeoutError("upstream timed out")
        error.provider_attempt_count = 1
        raise error
    monkeypatch.setattr(image_service, "_post_image_edits_once", send)
    with pytest.raises(TimeoutError) as caught:
        image_service._post_image_edits("https://provider.test/edit", {}, {"input_fidelity": "high"}, [], 20, "test",
                                        options={"image_max_attempts": 2})
    assert caught.value.provider_attempt_count == 2 and len(attempts) == 2


@pytest.mark.parametrize("module_name", ["app.training.draft_service", "app.expo.ai_pipeline"])
def test_workflow_configuration_stops_business_retry(db, configured, monkeypatch, module_name):
    import importlib
    from app.ai import service as facade
    module = importlib.import_module(module_name)
    _, preset = configured
    preset.parameters = {"workflow": {"max_attempts": 1}}
    db.commit()
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        response = httpx.Response(503, request=httpx.Request("POST", "https://provider.test/chat"))
        raise httpx.HTTPStatusError("busy", request=response.request, response=response)
    monkeypatch.setattr(facade, "chat", fail)
    with pytest.raises(httpx.HTTPStatusError):
        module._chat_with_transient_retry(db, preset.preset_name, [])
    assert len(calls) == 1


def test_frozen_text_config_survives_admin_edit_between_calls(db, configured, monkeypatch):
    from app.ai.text_snapshot import freeze_text_call_config
    from app.knowledge.ai_worker import lease_seconds_for_provider
    provider, preset = configured
    preset.parameters = {"transport": {"timeout_sec": 700}}
    frozen = freeze_text_call_config(preset, provider)
    assert lease_seconds_for_provider(frozen.provider, frozen.preset) >= 760
    calls = []
    monkeypatch.setattr(call_service, "post_json", lambda url, **kw: calls.append((url, kw)) or {
        "choices": [{"message": {"content": "ok"}}],
    })
    for model in ("replacement-a", "replacement-b"):
        preset.model = model
        provider.runtime_config = {"chat_path": "new", "timeout_sec": 1}
        db.commit()
        call_service.chat(db, preset.preset_name, [{"role": "user", "content": "hello"}], "test", trusted_text_snapshot=frozen)
    assert [kw["body"]["model"] for _, kw in calls] == ["future-model", "future-model"]
    assert all(url == "https://provider.test/api/chat/completions" and kw["timeout_sec"] == 700 for url, kw in calls)


@pytest.mark.parametrize("operation", ["generate", "edit"])
def test_chat_image_uses_provider_token_field(db, configured, monkeypatch, operation):
    provider, preset = configured
    provider.runtime_config = {"token_parameter": "max_completion_tokens"}
    preset.parameters = {"api_style": "chat", "max_tokens": 123}
    db.commit()
    bodies = []
    def post(url, headers, payload, *args, **kwargs):
        bodies.append(payload)
        return image_service.ImageTransportResult({"choices": [{"message": {"content": "data:image/png;base64,aW1hZ2U="}}]}, 1, None)
    monkeypatch.setattr(image_service, "_post_chat_image", post)
    if operation == "generate":
        image_service.generate_image(db, preset.preset_name, "draw", "test")
    else:
        image_service.edit_image(db, preset.preset_name, "edit", [{"filename": "a.png", "content": b"image", "content_type": "image/png"}], "test")
    assert bodies[0]["max_completion_tokens"] == 123 and "max_tokens" not in bodies[0]


def test_mysql_migration_can_generate_reviewable_offline_sql():
    import io
    path = Path(__file__).parents[1] / "alembic/versions/254_ai_provider_runtime.py"
    spec = importlib.util.spec_from_file_location("runtime_migration_offline", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    migration.op = Operations(MigrationContext.configure(dialect_name="mysql", opts={"as_sql": True, "output_buffer": output}))
    migration.upgrade()
    assert "ADD COLUMN runtime_config JSON" in output.getvalue()
    assert "JSON_CONTAINS_PATH" in output.getvalue()


def test_migration_preserves_config_and_backfills_only_missing_grok_defaults():
    path = Path(__file__).parents[1] / "alembic/versions/254_ai_provider_runtime.py"
    spec = importlib.util.spec_from_file_location("runtime_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    providers = sa.Table("ark_ai_providers", metadata, sa.Column("id", sa.Integer, primary_key=True))
    presets = sa.Table("ark_ai_presets", metadata, sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("model", sa.String), sa.Column("parameters", sa.JSON))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(providers.insert().values(id=1))
        conn.execute(presets.insert(), [
            {"id": 1, "model": "grok-imagine-image-2.0", "parameters": {"seed": 7}},
            {"id": 2, "model": "grok-imagine-image-2.0", "parameters": {"size_parameter": "size", "max_reference_images": 2}},
            {"id": 3, "model": "other", "parameters": {"seed": 8}},
        ])
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        rows = {row.id: row.parameters for row in conn.execute(sa.select(presets))}
        assert rows[1] == {"seed": 7, "size_parameter": "aspect_ratio", "max_reference_images": 3}
        assert rows[2] == {"size_parameter": "size", "max_reference_images": 2}
        assert rows[3] == {"seed": 8}
        assert "runtime_config" in {col["name"] for col in sa.inspect(conn).get_columns("ark_ai_providers")}
