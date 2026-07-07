from app.ai import image_service
from app.ai.models import AiCallLog, AiPreset, AiProvider


def _create_image_preset(db):
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
        preset_name="expo_wig_composite",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={"max_tokens": 4096, "size": "1024x1024", "quality": "high"},
        is_enabled=True,
    )
    db.add(preset)
    db.flush()
    return preset


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
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

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
    assert captured["timeout"] == 180
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
        "duration_ms": result["duration_ms"],
        "log_id": result["log_id"],
    }


def test_edit_image_keeps_provider_timeout_when_it_exceeds_image_minimum(db, monkeypatch):
    preset = _create_image_preset(db)
    provider = db.get(AiProvider, preset.provider_id)
    provider.timeout_sec = 240
    db.flush()
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": "abc"}]}

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

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

    assert captured["timeout"] == 240


def test_edit_image_timeout_error_mentions_effective_timeout(db, monkeypatch):
    _create_image_preset(db)

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

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
        assert "180 秒" in str(exc)
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
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

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
