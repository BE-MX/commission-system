import ast
from pathlib import Path

import pytest

from app.ai import image_service
from app.ai import service as ai_service
from app.ai.models import AiCallLog, AiPreset, AiProvider


@pytest.fixture(autouse=True)
def _no_image_proxy(monkeypatch):
    # 隔离真实 .env 的 AI_IMAGE_PROXY（展会云机有配）：假 Client 只收 timeout 参数
    class _S:
        AI_IMAGE_PROXY = ""
    monkeypatch.setattr(image_service, "get_settings", lambda: _S())


def _create_image_preset(db, *, preset_name="expo_wig_composite", parameters=None):
    provider = AiProvider(
        name="Image Provider",
        provider_type="direct",
        api_base="https://example.test",
        api_type="openai",
        api_key="encrypted",
        is_enabled=True,
        timeout_sec=30,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name=preset_name,
        provider_id=provider.id,
        model="gpt-image-2",
        parameters=parameters or {"max_tokens": 4096, "size": "1024x1024", "quality": "high"},
        is_enabled=True,
    )
    db.add(preset)
    db.flush()
    return preset


def test_image_functions_are_exported_from_service_facade():
    assert ai_service.generate_image is image_service.generate_image
    assert ai_service.edit_image is image_service.edit_image
    assert ai_service.build_image_config_version is image_service.build_image_config_version
    assert "from app.ai.service import" in ai_service.__doc__
    assert "directly import submodules" not in ai_service.__doc__


def test_generate_image_posts_whitelisted_json_and_records_metadata(db, monkeypatch):
    _create_image_preset(
        db,
        preset_name="design_image_generation",
        parameters={
            "output_format": "webp", "output_compression": 85,
            "size": "1024x1024", "quality": "medium", "input_fidelity": "high",
            "stream": True, "partial_images": 2,
            "api_key": "must-not-pass", "provider": "must-not-pass",
            "model": "must-not-pass", "max_tokens": 4096,
        },
    )
    captured = {}
    raw_b64 = "cHJpdmF0ZS1pbWFnZQ=="

    class FakeResponse:
        headers = {"request-id": "fallback", "x-request-id": "req-primary"}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [{"b64_json": raw_b64}],
                "usage": {
                    "input_tokens": 3, "output_tokens": 7, "total_tokens": 10,
                    "input_tokens_details": {"text_tokens": 3, "image_tokens": 0},
                    "output_tokens_details": {"image_tokens": 7},
                },
                "message": (
                    f"keep-before ![image](data:image/png;base64,{raw_b64}) keep-after "
                    "https://user:pass@cdn.test/a.png?sig=secret#fragment"
                ),
                "Authorization": "Bearer leaked", "api_key": "leaked-key", "token": "leaked-token",
            }

    class FakeClient:
        def __init__(self, timeout, **kwargs):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def build_request(self, method, url, **kwargs):
            return url, kwargs

        def send(self, request, stream=False):
            assert stream is True
            return self.post(request[0], **request[1])

        def post(self, url, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return FakeResponse()

    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(image_service.httpx, "Client", FakeClient)

    result = image_service.generate_image(
        db=db, preset_name="design_image_generation", prompt="draw a product",
        caller_module="design_image", caller_user_id=9, size="1536x1024", quality="high",
    )

    assert captured["url"] == "https://example.test/v1/images/generations"
    assert captured["json"] == {
        "model": "gpt-image-2", "prompt": "draw a product", "output_format": "webp",
        "output_compression": 85, "size": "1536x1024", "quality": "high",
    }
    usage_detail = {
        "input_tokens": 3, "output_tokens": 7, "total_tokens": 10,
        "input_tokens_details": {"text_tokens": 3, "image_tokens": 0},
        "output_tokens_details": {"image_tokens": 7},
    }
    assert result == {
        "content": f"data:image/webp;base64,{raw_b64}", "tokens_used": 10,
        "usage_detail": usage_detail, "duration_ms": result["duration_ms"],
        "log_id": result["log_id"], "provider_attempt_count": 1, "request_id": "req-primary",
    }
    log = db.get(AiCallLog, result["log_id"])
    assert log.usage_detail == usage_detail
    for secret in (raw_b64, "Bearer leaked", "leaked-key", "leaked-token"):
        assert secret not in log.response_snapshot
    assert "sig=secret" not in log.response_snapshot
    assert "user:pass" not in log.response_snapshot
    assert "keep-before" in log.response_snapshot and "keep-after" in log.response_snapshot


@pytest.mark.parametrize(
    ("payload", "output_format", "expected"),
    [
        ({"data": [{"b64_json": "abc"}]}, "jpeg", "data:image/jpeg;base64,abc"),
        ({"data": [{"url": "https://cdn.test/a.png?sig=secret"}]}, "png", "https://cdn.test/a.png?sig=secret"),
        ({"data": "data:image/webp;base64,abc"}, "png", "data:image/webp;base64,abc"),
        ({"b64_json": "abc"}, None, "data:image/png;base64,abc"),
        ({"url": "https://cdn.test/a.png"}, None, "https://cdn.test/a.png"),
    ],
)
def test_extract_image_content_supports_provider_shapes(payload, output_format, expected):
    assert image_service._extract_image_content(payload, output_format) == expected


def test_response_snapshot_strips_signed_url_query_and_sensitive_values():
    snapshot = image_service.serialize_response_snapshot({
        "url": "https://cdn.test/private/a.png?X-Amz-Signature=secret&token=also-secret",
        "Authorization": "Bearer secret", "api_key": "secret-key",
        "nested": {"access_token": "secret-token", "data": "data:image/png;base64,abc"},
    })
    assert "https://cdn.test/private/a.png" in snapshot
    for secret in ("Signature", "Bearer secret", "secret-key", "secret-token", "data:image"):
        assert secret not in snapshot


def test_response_snapshot_recursively_redacts_long_bare_base64():
    raw_b64 = "QUJD" * 200
    snapshot = image_service.serialize_response_snapshot({
        "data": raw_b64,
        "nested": ["ordinary text", {"payload": raw_b64}],
    })
    assert raw_b64 not in snapshot
    assert snapshot.count(f"[omitted base64-like value, {len(raw_b64)} chars]") == 2
    assert "ordinary text" in snapshot


def test_response_snapshot_redacts_embedded_data_urls_and_sanitizes_embedded_urls():
    raw_b64 = "QUJD" * 200
    snapshot = image_service.serialize_response_snapshot({
        "message": (
            f"before ![result](data:image/png;base64,{raw_b64}) after "
            "download https://user:pass@cdn.test/private/a.png?sig=secret#preview end"
        ),
        "blocks": [{
            "text": f"keep-left data:image/webp;base64,{raw_b64} keep-right",
            "href": "https://apiKey:secret@cdn.test/b.png?token=leaked#frag",
        }],
    })
    assert raw_b64 not in snapshot
    for secret in ("sig=secret", "token=leaked", "user:pass", "apiKey:secret", "#preview", "#frag"):
        assert secret not in snapshot
    for text in ("before", "after", "download", "end", "keep-left", "keep-right"):
        assert text in snapshot
    assert "https://cdn.test/private/a.png" in snapshot
    assert "https://cdn.test/b.png" in snapshot


def test_response_snapshot_normalizes_sensitive_key_spellings():
    snapshot = image_service.serialize_response_snapshot({
        "apiKey": "api-secret",
        "client_secret": "client-one",
        "clientSecret": "client-two",
        "password": "password-secret",
        "nested": [{"access-token": "access-secret"}],
    })
    for secret in ("api-secret", "client-one", "client-two", "password-secret", "access-secret"):
        assert secret not in snapshot
    assert snapshot.count("[redacted]") == 5


def test_response_snapshot_sanitizes_complex_embedded_url_boundaries():
    snapshot = image_service.serialize_response_snapshot({
        "text": (
            "ipv6 https://user:pass@[2001:db8::1]:8443/a(b).png?sig=secret#preview, next; "
            "markdown [download](https://cdn.test/x(a).png?token=leaked#frag). done; "
            "sentence https://cdn.test/plain.png?key=secret; after"
        ),
    })
    for secret in ("user:pass", "sig=secret", "token=leaked", "key=secret", "#preview", "#frag"):
        assert secret not in snapshot
    assert "https://[2001:db8::1]:8443/a(b).png, next" in snapshot
    assert "[download](https://cdn.test/x(a).png). done" in snapshot
    assert "https://cdn.test/plain.png; after" in snapshot


def test_business_modules_import_image_calls_from_service_facade():
    app_root = Path(__file__).parents[1] / "app"
    violations = []
    for path in app_root.rglob("*.py"):
        relative = path.relative_to(app_root)
        if relative.parts[0] == "ai":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(
            isinstance(node, ast.ImportFrom) and node.module == "app.ai.image_service"
            for node in ast.walk(tree)
        ):
            violations.append(relative.as_posix())
    assert violations == []


def test_generate_image_parse_failure_keeps_transport_attempt_count(db, monkeypatch):
    _create_image_preset(db, preset_name="design_image_generation")
    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(
        image_service,
        "_send_with_retry",
        lambda *args, **kwargs: image_service.ImageTransportResult({}, 2, "req-empty"),
    )

    with pytest.raises(ValueError) as caught:
        image_service.generate_image(
            db=db, preset_name="design_image_generation", prompt="draw",
            caller_module="design_image",
        )

    assert caught.value.provider_attempt_count == 2
    assert caught.value.log_id
    assert db.get(AiCallLog, caught.value.log_id).status == "error"


def test_image_config_fingerprint_is_stable_and_hides_key_material(db):
    preset = _create_image_preset(db, preset_name="design_image_generation")
    provider = db.get(AiProvider, preset.provider_id)
    provider.extra_headers = {"X-Secret-Route": "private-hop"}
    first = image_service.build_image_config_version(preset, provider)
    second = image_service.build_image_config_version(preset, provider)

    assert first == second
    assert len(first) == 64
    assert provider.api_key not in str(first)
    assert "private-hop" not in first


@pytest.mark.parametrize(
    "change",
    ["api_base", "api_key", "extra_headers", "timeout", "model", "output_format"],
)
def test_expected_config_fingerprint_detects_changes_without_timestamp_change(
    db, monkeypatch, change
):
    preset = _create_image_preset(db, preset_name="design_image_generation")
    db.commit()
    provider = db.get(AiProvider, preset.provider_id)
    expected = {
        "provider_id": provider.id,
        "fingerprint": image_service.build_image_config_version(preset, provider),
    }
    provider_updated_at = provider.updated_at
    preset_updated_at = preset.updated_at
    if change == "api_base":
        provider.api_base = "https://changed.example.test"
    elif change == "api_key":
        provider.api_key = "different-encrypted-value"
    elif change == "extra_headers":
        provider.extra_headers = {"X-Route": "changed"}
    elif change == "timeout":
        provider.timeout_sec += 1
    elif change == "model":
        preset.model = "gpt-image-changed"
    else:
        preset.parameters = {**(preset.parameters or {}), "output_format": "webp"}
    provider.updated_at = provider_updated_at
    preset.updated_at = preset_updated_at
    db.commit()
    sent = []
    monkeypatch.setattr(image_service, "_send_with_retry", lambda *args: sent.append(1))

    with pytest.raises(ValueError, match="configuration changed"):
        image_service.generate_image(
            db=db, preset_name=preset.preset_name, prompt="draw",
            caller_module="design_image", expected_config_version=expected,
        )
    assert sent == []


def test_expected_config_fingerprint_allows_unchanged_call(db, monkeypatch):
    preset = _create_image_preset(db, preset_name="design_image_generation")
    provider = db.get(AiProvider, preset.provider_id)
    expected = {
        "provider_id": provider.id,
        "fingerprint": image_service.build_image_config_version(preset, provider),
    }
    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(
        image_service, "_send_with_retry",
        lambda *args, **kwargs: image_service.ImageTransportResult(
            {"data": [{"b64_json": "abc"}]}, 1, "request-id"
        ),
    )

    result = image_service.generate_image(
        db=db, preset_name=preset.preset_name, prompt="draw",
        caller_module="design_image", expected_config_version=expected,
    )
    assert result["content"] == "data:image/png;base64,abc"


@pytest.mark.parametrize("mode", ["generate", "edit"])
def test_image_call_uses_validated_snapshot_after_pending_log_commit(
    db, monkeypatch, mode
):
    preset = _create_image_preset(
        db, preset_name="design_image_generation",
        parameters={"output_format": "png"},
    )
    provider = db.get(AiProvider, preset.provider_id)
    provider.api_base = "https://old.example.test"
    provider.api_key = "old-encrypted-key"
    provider.extra_headers = {"X-Route": "old"}
    provider.timeout_sec = 301
    preset.model = "old-image-model"
    db.commit()
    expected = {
        "provider_id": provider.id,
        "fingerprint": image_service.build_image_config_version(preset, provider),
    }
    captured = {}
    real_commit = db.commit
    commits = {"count": 0}

    def racing_commit():
        commits["count"] += 1
        if commits["count"] == 1:
            provider.api_base = "https://new.example.test"
            provider.api_key = "new-encrypted-key"
            provider.extra_headers = {"X-Route": "new"}
            provider.timeout_sec = 601
            preset.model = "new-image-model"
            preset.parameters = {"output_format": "webp", "api_style": "chat"}
        return real_commit()

    def fake_build_headers(config, api_key):
        captured["provider"] = {
            "api_base": config.api_base,
            "api_key": config.api_key,
            "extra_headers": config.extra_headers,
            "timeout_sec": config.timeout_sec,
        }
        captured["decrypted"] = api_key
        return {}

    def fake_send(build_request, timeout_sec, *args):
        class Client:
            def build_request(self, method, url, **kwargs):
                captured.update(method=method, url=url, request_kwargs=kwargs)
                return object()
        build_request(Client())
        captured["timeout_sec"] = timeout_sec
        return image_service.ImageTransportResult(
            {"data": [{"b64_json": "abc"}]}, 1, "request-id"
        )

    monkeypatch.setattr(db, "commit", racing_commit)
    monkeypatch.setattr(
        image_service, "decrypt_key",
        lambda value: captured.setdefault("encrypted", value) or "decrypted-old",
    )
    monkeypatch.setattr(image_service, "build_headers", fake_build_headers)
    monkeypatch.setattr(image_service, "_send_with_retry", fake_send)

    kwargs = {
        "db": db, "preset_name": preset.preset_name, "prompt": "draw",
        "caller_module": "design_image", "expected_config_version": expected,
    }
    if mode == "edit":
        result = image_service.edit_image(
            **kwargs,
            images=[{"filename": "a.png", "content": b"a", "content_type": "image/png"}],
        )
    else:
        result = image_service.generate_image(**kwargs)

    assert captured["provider"] == {
        "api_base": "https://old.example.test",
        "api_key": "old-encrypted-key",
        "extra_headers": {"X-Route": "old"},
        "timeout_sec": 301,
    }
    assert captured["encrypted"] == "old-encrypted-key"
    assert captured["timeout_sec"] == 301
    assert captured["url"].startswith("https://old.example.test/")
    assert captured["request_kwargs"].get("json", captured["request_kwargs"].get("data"))[
        "model"
    ] == "old-image-model"
    assert result["content"] == "data:image/png;base64,abc"
    assert db.get(AiCallLog, result["log_id"]).model == "old-image-model"


@pytest.mark.parametrize(
    "result",
    [
        {"usage": "bad"},
        {"usage": []},
        {"usage": 7},
        {"usage": "bad", "data": [{"usage": {"total_tokens": 9}}]},
        {"data": ["not-a-dict"]},
        {"data": [{"usage": "bad"}]},
    ],
)
def test_usage_extractors_treat_non_dict_payloads_as_empty(result):
    assert image_service._extract_usage(result) == {}
    assert image_service._extract_usage_detail(result) == {}


def test_error_log_second_commit_failure_warns_logger_and_console(
    db, monkeypatch, caplog, capsys
):
    _create_image_preset(db, preset_name="design_image_generation")
    real_commit = db.commit
    commits = {"count": 0}

    def commit():
        commits["count"] += 1
        if commits["count"] == 2:
            raise RuntimeError("audit database unavailable")
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(
        image_service, "_send_with_retry",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider failed")),
    )
    caplog.set_level("WARNING")
    with pytest.raises(RuntimeError, match="provider failed"):
        image_service.generate_image(
            db=db, preset_name="design_image_generation", prompt="draw",
            caller_module="design_image",
        )
    assert "error-state commit failed" in caplog.text
    assert "error-state commit failed" in capsys.readouterr().out


def test_edit_image_parse_failure_keeps_transport_attempt_count(db, monkeypatch):
    _create_image_preset(db)
    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(
        image_service,
        "_post_image_edits",
        lambda *args, **kwargs: image_service.ImageTransportResult({}, 3, "req-empty"),
    )

    with pytest.raises(ValueError) as caught:
        image_service.edit_image(
            db=db, preset_name="expo_wig_composite", prompt="edit",
            images=[{"filename": "a.png", "content": b"a", "content_type": "image/png"}],
            caller_module="expo",
        )

    assert caught.value.provider_attempt_count == 3
    assert caught.value.log_id
    assert db.get(AiCallLog, caught.value.log_id).status == "error"


def test_image_transport_rejects_oversized_content_length_before_json(monkeypatch):
    json_calls = []

    class FakeResponse:
        headers = {"Content-Length": str(40 * 1024 * 1024)}
        def close(self):
            return None
        def raise_for_status(self):
            return None
        def json(self):
            json_calls.append(1)
            return {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def build_request(self, *args, **kwargs):
            return object()
        def send(self, request, stream=False):
            assert stream is True
            return FakeResponse()

    monkeypatch.setattr(image_service.httpx, "Client", FakeClient)
    with pytest.raises(ValueError, match="too large"):
        image_service._send_with_retry(
            lambda client: client.build_request("POST", "https://example.test"),
            300, "design_image", "generation"
        )
    assert json_calls == []


def test_edit_image_posts_openai_compatible_image_edit_request(db, monkeypatch):
    _create_image_preset(db)

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [{"b64_json": "abc"}],
                "usage": {"input_tokens": 3, "output_tokens": 7, "total_tokens": 10},
            }

    class FakeClient:
        def __init__(self, timeout, **kwargs):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def build_request(self, method, url, **kwargs):
            return url, kwargs

        def send(self, request, stream=False):
            assert stream is True
            return self.post(request[0], **request[1])

        def post(self, url, headers, data, files):
            captured.update(
                {
                    "url": url,
                    "headers": headers,
                    "data": data,
                    "files": files,
                }
            )
            return FakeResponse()

    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(image_service.httpx, "Client", FakeClient)

    result = image_service.edit_image(
        db=db,
        preset_name="expo_wig_composite",
        prompt="replace hair",
        images=[
            {"filename": "customer.png", "content": b"one", "content_type": "image/png"},
            {"filename": "wig.jpeg", "content": b"two", "content_type": "image/jpeg"},
        ],
        caller_module="ai_preset_test",
    )

    assert captured["url"] == "https://example.test/v1/images/edits"
    # 生图有效超时=read 分量（connect/write 已收紧为快速失败，2026-07-16）
    assert captured["timeout"].read == image_service.MIN_IMAGE_EDIT_TIMEOUT_SEC
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert "Content-Type" not in captured["headers"]
    assert captured["data"] == {
        "model": "gpt-image-2",
        "prompt": "replace hair",
        "size": "1024x1024",
        "quality": "high",
    }
    assert [item[0] for item in captured["files"]] == ["image", "image"]
    assert result == {
        "content": "data:image/png;base64,abc",
        "tokens_used": 10,
        "usage_detail": {"input_tokens": 3, "output_tokens": 7, "total_tokens": 10},
        "duration_ms": result["duration_ms"],
        "log_id": result["log_id"],
        "provider_attempt_count": 1,
        "request_id": None,
    }


def test_edit_image_keeps_provider_timeout_when_it_exceeds_image_minimum(db, monkeypatch):
    preset = _create_image_preset(db)
    provider = db.get(AiProvider, preset.provider_id)
    provider.timeout_sec = image_service.MIN_IMAGE_EDIT_TIMEOUT_SEC + 60
    db.flush()
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": "abc"}]}

    class FakeClient:
        def __init__(self, timeout, **kwargs):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def build_request(self, method, url, **kwargs):
            return url, kwargs

        def send(self, request, stream=False):
            assert stream is True
            return self.post(request[0], **request[1])

        def post(self, url, headers, data, files):
            return FakeResponse()

    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(image_service.httpx, "Client", FakeClient)

    image_service.edit_image(
        db=db,
        preset_name="expo_wig_composite",
        prompt="replace hair",
        images=[{"filename": "customer.png", "content": b"one", "content_type": "image/png"}],
        caller_module="ai_preset_test",
    )

    assert captured["timeout"].read == image_service.MIN_IMAGE_EDIT_TIMEOUT_SEC + 60


def test_edit_image_timeout_error_mentions_effective_timeout(db, monkeypatch):
    _create_image_preset(db)

    class FakeClient:
        def __init__(self, timeout, **kwargs):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def build_request(self, method, url, **kwargs):
            return url, kwargs

        def send(self, request, stream=False):
            assert stream is True
            return self.post(request[0], **request[1])

        def post(self, url, headers, data, files):
            raise image_service.httpx.ReadTimeout("timed out")

    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(image_service.httpx, "Client", FakeClient)

    try:
        image_service.edit_image(
            db=db,
            preset_name="expo_wig_composite",
            prompt="replace hair",
            images=[{"filename": "customer.png", "content": b"one", "content_type": "image/png"}],
            caller_module="ai_preset_test",
        )
    except TimeoutError as exc:
        assert f"{image_service.MIN_IMAGE_EDIT_TIMEOUT_SEC} 秒" in str(exc)
        assert "图片生成超时" in str(exc)
    else:
        raise AssertionError("expected TimeoutError")


def test_edit_image_omits_large_base64_from_response_snapshot(db, monkeypatch):
    _create_image_preset(db)
    large_b64 = "a" * 90000

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [{"b64_json": large_b64, "revised_prompt": "ok"}],
                "usage": {"input_tokens": 3, "output_tokens": 7, "total_tokens": 10},
            }

    class FakeClient:
        def __init__(self, timeout, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def build_request(self, method, url, **kwargs):
            return url, kwargs

        def send(self, request, stream=False):
            assert stream is True
            return self.post(request[0], **request[1])

        def post(self, url, headers, data, files):
            return FakeResponse()

    monkeypatch.setattr(image_service, "decrypt_key", lambda value: "sk-test")
    monkeypatch.setattr(image_service.httpx, "Client", FakeClient)

    result = image_service.edit_image(
        db=db,
        preset_name="expo_wig_composite",
        prompt="replace hair",
        images=[{"filename": "customer.png", "content": b"one", "content_type": "image/png"}],
        caller_module="ai_preset_test",
    )

    log = db.get(AiCallLog, result["log_id"])
    assert result["content"] == f"data:image/png;base64,{large_b64}"
    assert large_b64 not in log.response_snapshot
    assert "[omitted base64 image" in log.response_snapshot
    assert len(log.response_snapshot) < 5000
