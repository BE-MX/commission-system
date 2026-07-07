from app.ai import preset_service
from app.ai.models import AiPreset, AiProvider


class UpstreamError(RuntimeError):
    pass


def _create_vision_preset(db):
    provider = AiProvider(
        name="Vision Provider",
        provider_type="direct",
        api_base="https://example.test",
        api_type="anthropic",
        api_key="encrypted",
        is_enabled=True,
        timeout_sec=60,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name="expo_face_analysis",
        provider_id=provider.id,
        model="claude-sonnet-4-6",
        system_prompt="Return JSON only.",
        parameters={"max_tokens": 2048},
        description="Face analysis",
        is_enabled=True,
    )
    db.add(preset)
    db.flush()
    return preset


def _create_image_preset(db):
    provider = AiProvider(
        name="Image Provider",
        provider_type="direct",
        api_base="https://example.test",
        api_type="openai",
        api_key="encrypted",
        is_enabled=True,
        timeout_sec=60,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name="expo_wig_composite",
        provider_id=provider.id,
        model="gpt-image-2",
        system_prompt=None,
        parameters={"max_tokens": 4096},
        description="Wig composite",
        is_enabled=True,
    )
    db.add(preset)
    db.flush()
    return preset


def test_preset_test_uses_shared_chat_service(db, monkeypatch):
    preset = _create_vision_preset(db)
    calls = []

    def fake_chat(db, preset_name, messages, caller_module, caller_user_id=None):
        calls.append(
            {
                "preset_name": preset_name,
                "messages": messages,
                "caller_module": caller_module,
                "caller_user_id": caller_user_id,
            }
        )
        return {"content": '{"face_shape":"oval"}', "tokens_used": 12, "duration_ms": 34}

    monkeypatch.setattr(preset_service, "chat", fake_chat)

    result = preset_service.test_preset(db, preset.id, "analyze this")

    assert calls == [
        {
            "preset_name": "expo_face_analysis",
            "messages": [{"role": "user", "content": "analyze this"}],
            "caller_module": "ai_preset_test",
            "caller_user_id": None,
        }
    ]
    assert result == {
        "status": "ok",
        "response": '{"face_shape":"oval"}',
        "tokens_used": 12,
        "duration_ms": 34,
    }


def test_preset_image_test_sends_multimodal_message(db, monkeypatch):
    preset = _create_vision_preset(db)
    calls = []

    def fake_chat(db, preset_name, messages, caller_module, caller_user_id=None):
        calls.append(
            {
                "preset_name": preset_name,
                "messages": messages,
                "caller_module": caller_module,
                "caller_user_id": caller_user_id,
            }
        )
        return {"content": '{"confidence":0.9}', "tokens_used": 18, "duration_ms": 56}

    monkeypatch.setattr(preset_service, "chat", fake_chat)

    result = preset_service.test_preset_with_image(
        db,
        preset.id,
        "analyze this face",
        b"fake-image-bytes",
        "image/png",
    )

    message = calls[0]["messages"][0]
    assert calls[0]["preset_name"] == "expo_face_analysis"
    assert calls[0]["caller_module"] == "ai_preset_test"
    assert message["role"] == "user"
    assert message["content"][0] == {"type": "text", "text": "analyze this face"}
    assert message["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,ZmFrZS1pbWFnZS1ieXRlcw=="},
    }
    assert result == {
        "status": "ok",
        "response": '{"confidence":0.9}',
        "tokens_used": 18,
        "duration_ms": 56,
    }


def test_preset_test_returns_error_result_on_upstream_failure(db, monkeypatch):
    preset = _create_vision_preset(db)

    def fake_chat(db, preset_name, messages, caller_module, caller_user_id=None):
        raise UpstreamError("HTTP 502 Bad Gateway")

    monkeypatch.setattr(preset_service, "chat", fake_chat)

    result = preset_service.test_preset(db, preset.id, "analyze this")

    assert result["status"] == "error"
    assert result["tokens_used"] is None
    assert result["duration_ms"] >= 0
    assert "HTTP 502 Bad Gateway" in result["response"]


def test_composite_image_test_uses_image_edit_service(db, monkeypatch):
    preset = _create_image_preset(db)
    calls = []

    def fake_edit_image(db, preset_name, prompt, images, caller_module, caller_user_id=None):
        calls.append(
            {
                "preset_name": preset_name,
                "prompt": prompt,
                "images": images,
                "caller_module": caller_module,
                "caller_user_id": caller_user_id,
            }
        )
        return {
            "content": "data:image/png;base64,abc",
            "tokens_used": 42,
            "duration_ms": 123,
        }

    monkeypatch.setattr(preset_service, "edit_image", fake_edit_image)

    result = preset_service.test_preset_with_image(
        db,
        preset.id,
        "replace hair",
        b"customer-image",
        "image/png",
        reference_image_bytes=b"wig-image",
        reference_content_type="image/jpeg",
    )

    assert calls == [
        {
            "preset_name": "expo_wig_composite",
            "prompt": "replace hair",
            "images": [
                {
                    "filename": "customer_image.png",
                    "content": b"customer-image",
                    "content_type": "image/png",
                },
                {
                    "filename": "wig_reference.jpeg",
                    "content": b"wig-image",
                    "content_type": "image/jpeg",
                },
            ],
            "caller_module": "ai_preset_test",
            "caller_user_id": None,
        }
    ]
    assert result == {
        "status": "ok",
        "response": "data:image/png;base64,abc",
        "tokens_used": 42,
        "duration_ms": 123,
    }


def test_composite_image_test_requires_reference_image(db):
    preset = _create_image_preset(db)

    result = preset_service.test_preset_with_image(
        db,
        preset.id,
        "replace hair",
        b"customer-image",
        "image/png",
    )

    assert result["status"] == "error"
    assert "假发参考图" in result["response"]
