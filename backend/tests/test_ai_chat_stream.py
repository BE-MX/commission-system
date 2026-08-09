import json

import httpx
import pytest

from app.ai import service, stream_service
from app.ai.call_service import chat_stream, parse_provider_stream
from app.ai.models import AiCallLog, AiPreset, AiProvider


def _sse(data):
    return f"data: {json.dumps(data, ensure_ascii=False)}"


def _configured_preset(db, api_type="openai"):
    provider = AiProvider(
        name=f"{api_type} stream provider",
        provider_type="direct",
        api_base="https://provider.example/v1",
        api_type=api_type,
        api_key="encrypted-key",
        is_enabled=True,
        timeout_sec=17,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name=f"stream_{api_type}",
        provider_id=provider.id,
        model="stream-model",
        system_prompt="Be useful.",
        parameters={"max_tokens": 64},
        is_enabled=True,
    )
    db.add(preset)
    db.commit()
    return preset, provider


def test_parse_anthropic_stream_collects_text_usage_and_ignores_comments():
    lines = [
        ": keepalive",
        "",
        _sse({
            "type": "message_start",
            "message": {"model": "claude-test", "usage": {"input_tokens": 12}},
        }),
        _sse({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "客户"}}),
        _sse({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "方案"}}),
        _sse({"type": "message_delta", "usage": {"output_tokens": 8}}),
        _sse({"type": "message_stop"}),
    ]

    events = list(parse_provider_stream("anthropic", lines))

    assert events == [
        {"type": "meta", "model": "claude-test"},
        {"type": "delta", "text": "客户"},
        {"type": "delta", "text": "方案"},
        {"type": "done", "input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    ]


def test_parse_openai_stream_collects_delta_usage_and_done():
    lines = [
        _sse({"model": "gpt-test", "choices": [{"delta": {"role": "assistant"}}]}),
        _sse({"choices": [{"delta": {"content": "完"}}]}),
        _sse({"choices": [{"delta": {"content": "成"}}]}),
        _sse({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}),
        "data: [DONE]",
        _sse({"choices": [{"delta": {"content": "ignored"}}]}),
    ]

    events = list(parse_provider_stream("openai", lines))

    assert events == [
        {"type": "meta", "model": "gpt-test"},
        {"type": "delta", "text": "完"},
        {"type": "delta", "text": "成"},
        {"type": "done", "input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    ]


def test_parse_provider_errors_are_neutral_and_malformed_or_empty_streams_fail_safely():
    expected = [{"type": "error", "code": "provider_error", "message": "上游模型返回错误"}]
    assert list(parse_provider_stream("anthropic", [_sse({"type": "error", "error": {"message": "secret"}})])) == expected
    assert list(parse_provider_stream("openai", [_sse({"error": {"message": "secret"}})])) == expected
    assert list(parse_provider_stream("openai", ["data: {broken"])) == [
        {"type": "error", "code": "invalid_stream", "message": "上游流响应格式无效"}
    ]
    assert list(parse_provider_stream("openai", ["", ": ping", "data: "])) == [
        {"type": "error", "code": "stream_incomplete", "message": "上游流响应未正常结束"}
    ]


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        yield from self.chunks

    def close(self):
        self.closed = True


def _install_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    created = []
    client_cls = httpx.Client

    def client_factory(**kwargs):
        client = client_cls(transport=transport, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(stream_service.httpx, "Client", client_factory)
    monkeypatch.setattr(stream_service, "decrypt_key", lambda _: "api-secret")
    return created


def test_chat_stream_preserves_split_utf8_and_finalizes_success(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")
    raw = (
        _sse({"choices": [{"delta": {"content": "客户方案"}}]})
        + "\n\n"
        + _sse({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}})
        + "\n\ndata: [DONE]\n\n"
    ).encode("utf-8")
    split_at = raw.index("客".encode("utf-8")) + 1
    byte_stream = _ChunkStream([raw[:split_at], raw[split_at:]])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=byte_stream)

    created = _install_transport(monkeypatch, handler)

    events = list(chat_stream(db, preset.preset_name, [{"role": "user", "content": "你好"}], "ai_chat", 9))

    assert events[0]["type"] == "meta"
    assert events[0]["model"] == "stream-model"
    assert isinstance(events[0]["log_id"], int)
    assert [event for event in events if event["type"] == "delta"] == [{"type": "delta", "text": "客户方案"}]
    assert events[-1] == {"type": "done", "input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    assert json.loads(requests[0].content)["stream"] is True
    assert requests[0].headers["authorization"] == "Bearer api-secret"
    assert byte_stream.closed is True
    assert created[0].is_closed is True
    log = db.query(AiCallLog).filter_by(id=events[0]["log_id"]).one()
    assert log.status == "success"
    assert (log.tokens_prompt, log.tokens_completion, log.tokens_used) == (4, 2, 6)
    assert "客户方案" in log.response_snapshot
    assert "api-secret" not in (log.response_snapshot or "")


def test_chat_stream_provider_error_is_logged_without_leaking_payload(db, monkeypatch):
    preset, _ = _configured_preset(db, "anthropic")
    payload = (_sse({"type": "error", "error": {"message": "api-secret leaked"}}) + "\n\n").encode()
    byte_stream = _ChunkStream([payload])

    def handler(_request):
        return httpx.Response(200, stream=byte_stream)

    created = _install_transport(monkeypatch, handler)

    events = list(chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat"))

    assert events[-1] == {"type": "error", "code": "provider_error", "message": "上游模型返回错误"}
    log = db.query(AiCallLog).filter_by(id=events[0]["log_id"]).one()
    assert log.status == "error"
    assert log.error_code == "provider_error"
    assert "api-secret" not in (log.error_message or "")
    assert byte_stream.closed is True
    assert created[0].is_closed is True


def test_chat_stream_close_marks_consumer_stopped_and_closes_upstream(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")
    payload = (
        _sse({"choices": [{"delta": {"content": "partial"}}]}) + "\n\n"
        + _sse({"choices": [{"delta": {"content": "never consumed"}}]}) + "\n\n"
    ).encode()
    byte_stream = _ChunkStream([payload])

    def handler(_request):
        return httpx.Response(200, stream=byte_stream)

    created = _install_transport(monkeypatch, handler)
    stream = chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat")
    meta = next(stream)
    assert next(stream) == {"type": "delta", "text": "partial"}

    stream.close()

    log = db.query(AiCallLog).filter_by(id=meta["log_id"]).one()
    assert log.status == "error"
    assert log.error_code == "consumer_stopped"
    assert log.usage_detail["termination"] == "stopped"
    assert "cancel" not in json.dumps(log.usage_detail).lower()
    assert byte_stream.closed is True
    assert created[0].is_closed is True


def test_closing_after_done_does_not_overwrite_success(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")
    payload = (
        _sse({"choices": [{"delta": {"content": "complete"}}]})
        + "\n\ndata: [DONE]\n\n"
    ).encode()

    def handler(_request):
        return httpx.Response(200, stream=_ChunkStream([payload]))

    _install_transport(monkeypatch, handler)
    stream = chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat")
    meta = next(stream)
    assert next(stream)["type"] == "delta"
    assert next(stream)["type"] == "done"

    stream.close()

    log = db.query(AiCallLog).filter_by(id=meta["log_id"]).one()
    assert log.status == "success"
    assert log.error_code is None


def test_setup_failure_after_pending_log_is_finalized_without_secret(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")

    def fail_decrypt(_encrypted):
        raise RuntimeError("api-secret must not leak")

    monkeypatch.setattr(stream_service, "decrypt_key", fail_decrypt)

    events = list(chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat"))

    assert events == [
        {"type": "error", "code": "upstream_request_failed", "message": "上游模型连接失败"}
    ]
    log = db.query(AiCallLog).filter_by(preset_name=preset.preset_name).one()
    assert log.status == "error"
    assert log.error_code == "upstream_request_failed"
    assert "api-secret" not in (log.error_message or "")


def test_chat_stream_rejects_missing_or_disabled_preset(db):
    with pytest.raises(ValueError, match="不存在"):
        list(chat_stream(db, "missing", [], "ai_chat"))

    preset, _ = _configured_preset(db, "openai")
    preset.is_enabled = False
    db.commit()

    with pytest.raises(ValueError, match="已被禁用"):
        list(chat_stream(db, preset.preset_name, [], "ai_chat"))


def test_chat_stream_rejects_non_direct_or_disabled_provider(db):
    preset, provider = _configured_preset(db, "openai")
    provider.provider_type = "accio_work"
    db.commit()
    with pytest.raises(ValueError, match="accio_work"):
        list(chat_stream(db, preset.preset_name, [], "ai_chat"))

    provider.provider_type = "direct"
    provider.is_enabled = False
    db.commit()
    with pytest.raises(ValueError, match="当前不可用"):
        list(chat_stream(db, preset.preset_name, [], "ai_chat"))


def test_http_status_error_finalizes_log_and_closes_client_and_response(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")
    byte_stream = _ChunkStream([b'{"error":{"message":"api-secret"}}'])

    def handler(_request):
        return httpx.Response(429, stream=byte_stream)

    created = _install_transport(monkeypatch, handler)

    events = list(chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat"))

    assert events == [
        {"type": "error", "code": "upstream_http_error", "message": "上游模型请求失败 (HTTP 429)"}
    ]
    log = db.query(AiCallLog).filter_by(preset_name=preset.preset_name).one()
    assert log.status == "error"
    assert log.error_code == "upstream_http_error"
    assert "api-secret" not in (log.error_message or "")
    assert byte_stream.closed is True
    assert created[0].is_closed is True


def test_openai_stream_uses_provider_url_and_timeout(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")
    payload = b'data: [DONE]\n\n'
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=_ChunkStream([payload]))

    created = _install_transport(monkeypatch, handler)

    list(chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat"))

    assert str(requests[0].url) == "https://provider.example/v1/chat/completions"
    assert created[0].timeout.connect == 17


def test_anthropic_stream_uses_key_and_stream_body_and_redacts_response(db, monkeypatch):
    preset, _ = _configured_preset(db, "anthropic")
    payload = (
        _sse({"type": "message_start", "message": {"model": "stream-model", "usage": {"input_tokens": 3}}})
        + "\n\n"
        + _sse({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer api-secret"}})
        + "\n\n"
        + _sse({"type": "message_delta", "usage": {"output_tokens": 2}})
        + "\n\n"
        + _sse({"type": "message_stop"})
        + "\n\n"
    ).encode()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=_ChunkStream([payload]))

    _install_transport(monkeypatch, handler)

    events = list(chat_stream(db, preset.preset_name, [{"role": "user", "content": "hi"}], "ai_chat"))

    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://provider.example/v1/messages"
    assert request.headers["x-api-key"] == "api-secret"
    assert body["stream"] is True
    assert body["max_tokens"] == 64
    assert body["system"] == "Be useful."
    assert events[-1]["type"] == "done"
    log = db.query(AiCallLog).filter_by(preset_name=preset.preset_name).one()
    assert "api-secret" not in log.response_snapshot
    assert "[REDACTED]" in log.response_snapshot


def test_prompt_snapshot_is_structural_and_contains_no_message_content(db, monkeypatch):
    preset, _ = _configured_preset(db, "openai")
    short_image = "data:image/png;base64,QUJD"
    long_image = "data:image/png;base64," + "A" * 1024
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "user body with api-secret"},
            {"type": "image_url", "image_url": {"url": short_image}},
            {"type": "image_url", "image_url": {"url": long_image}},
        ],
    }]

    def handler(_request):
        return httpx.Response(200, stream=_ChunkStream([b"data: [DONE]\n\n"]))

    _install_transport(monkeypatch, handler)

    list(chat_stream(db, preset.preset_name, messages, "ai_chat"))

    log = db.query(AiCallLog).filter_by(preset_name=preset.preset_name).one()
    snapshot = json.loads(log.prompt_snapshot)
    assert snapshot["message_count"] == 2
    assert snapshot["roles"] == ["system", "user"]
    assert snapshot["has_image"] is True
    assert snapshot["messages"][1]["content_type"] == "blocks"
    assert snapshot["messages"][1]["block_types"] == ["text", "image_url", "image_url"]
    for secret in ("Be useful.", "user body", "api-secret", "QUJD", "A" * 20):
        assert secret not in log.prompt_snapshot


def test_service_facade_exports_streaming_api():
    assert service.chat_stream is chat_stream
    assert service.parse_provider_stream is parse_provider_stream
