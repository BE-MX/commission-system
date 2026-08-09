"""HTTP and SSE contract tests for Customer AI Chat."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ai_chat import file_service, router, service
from app.ai_chat.file_service import StoredAttachment
from app.ai_chat.models import AiChatMessage, AiChatSession
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db


def _seed_user(db, username="router-owner"):
    user = ArkUser(username=username, password_hash="test", real_name=username)
    db.add(user)
    db.commit()
    return user


def _app(engine, claims):
    testing_app = FastAPI()
    testing_app.include_router(router.router, prefix="/api/ai-chat")
    SessionLocal = sessionmaker(bind=engine)

    def override_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    testing_app.dependency_overrides[get_db] = override_db
    testing_app.dependency_overrides[get_current_user] = lambda: claims
    return testing_app


def _claims(user_id, *permissions):
    return {
        "sub": str(user_id),
        "permissions": list(permissions),
        "roles": [],
    }


def _stored(storage_path="documents/test.txt"):
    return StoredAttachment(
        storage_path=storage_path,
        original_name="brief.txt",
        mime_type="text/plain",
        file_size=5,
        attachment_type="document",
        extracted_text="hello",
        truncated=False,
        width=None,
        height=None,
        sha256="abc",
    )


def _configured(db):
    from app.ai.models import AiPreset, AiProvider

    provider = AiProvider(
        name="router-provider",
        provider_type="direct",
        api_type="anthropic",
        api_base="https://example.invalid",
        is_enabled=True,
        timeout_sec=30,
    )
    db.add(provider)
    db.flush()
    db.add(
        AiPreset(
            preset_name="customer_ai_chat",
            provider_id=provider.id,
            model="claude-fable-5",
            system_prompt="safe system prompt",
            is_enabled=True,
        )
    )
    db.commit()


def test_config_requires_read_permission_and_uses_ok_envelope(engine, db):
    owner = _seed_user(db)
    denied = TestClient(_app(engine, _claims(owner.id, "ai_chat:write")))
    assert denied.get("/api/ai-chat/config").status_code == 403

    allowed = TestClient(_app(engine, _claims(owner.id, "ai_chat:read")))
    response = allowed.get("/api/ai-chat/config")
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert response.json()["data"]["configured"] is False


def test_mutations_require_write_and_owner_resource_is_404(engine, db):
    owner = _seed_user(db, "router-mutation-owner")
    stranger = _seed_user(db, "router-mutation-stranger")
    conversation = service.create_session(db, owner.id)
    read_only = TestClient(_app(engine, _claims(owner.id, "ai_chat:read")))
    assert read_only.post("/api/ai-chat/sessions", json={}).status_code == 403

    stranger_client = TestClient(
        _app(engine, _claims(stranger.id, "ai_chat:read", "ai_chat:write"))
    )
    response = stranger_client.get(f"/api/ai-chat/sessions/{conversation.id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "资源不存在"


def test_upload_and_private_content_never_expose_storage_path(
    engine, db, monkeypatch
):
    owner = _seed_user(db, "router-upload")
    conversation = service.create_session(db, owner.id)
    monkeypatch.setattr(file_service, "normalize_and_store", lambda *_args: _stored())
    monkeypatch.setattr(file_service, "read_private_file", lambda _path: b"hello")
    client = TestClient(
        _app(engine, _claims(owner.id, "ai_chat:read", "ai_chat:write"))
    )

    uploaded = client.post(
        f"/api/ai-chat/sessions/{conversation.id}/attachments",
        files={"file": ("brief.txt", b"hello", "text/plain")},
    )
    assert uploaded.status_code == 200
    assert "storage_path" not in uploaded.text
    attachment_id = uploaded.json()["data"]["id"]

    content = client.get(f"/api/ai-chat/attachments/{attachment_id}/content")
    assert content.status_code == 200
    assert content.content == b"hello"
    assert "filename*=UTF-8''brief.txt" in content.headers["content-disposition"]


def test_stream_emits_meta_delta_done_without_ok_envelope(
    engine, db, monkeypatch
):
    owner = _seed_user(db, "router-stream")
    conversation = service.create_session(db, owner.id)
    _configured(db)

    def fake_stream(*_args, **_kwargs):
        yield {"type": "meta", "log_id": 91, "model": "claude-fable-5"}
        yield {"type": "delta", "text": "你好"}
        yield {"type": "done", "total_tokens": 7, "duration_ms": 12}

    monkeypatch.setattr(router, "chat_stream", fake_stream)
    client = TestClient(
        _app(engine, _claims(owner.id, "ai_chat:read", "ai_chat:write"))
    )
    response = client.post(
        f"/api/ai-chat/sessions/{conversation.id}/turns/stream",
        json={"request_id": "router_req_001", "content": "say hello"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: meta" in response.text
    assert '"session_id":' in response.text
    assert "event: delta\ndata: {\"text\":\"你好\"}" in response.text
    assert "event: done" in response.text
    assert '"code":200' not in response.text
    assistant = db.query(AiChatMessage).filter_by(role="assistant").one()
    db.refresh(assistant)
    assert assistant.status == "completed"
    assert assistant.content == "你好"
    assert assistant.ai_call_log_id == 91


def test_repeated_stream_request_replays_saved_content_without_model_call(
    engine, db, monkeypatch
):
    owner = _seed_user(db, "router-repeat")
    conversation = service.create_session(db, owner.id)
    _configured(db)
    calls = 0

    def fake_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        yield {"type": "delta", "text": "saved"}
        yield {"type": "done", "total_tokens": 1}

    monkeypatch.setattr(router, "chat_stream", fake_stream)
    client = TestClient(_app(engine, _claims(owner.id, "ai_chat:write")))
    payload = {"request_id": "router_repeat_1", "content": "question"}
    first = client.post(
        f"/api/ai-chat/sessions/{conversation.id}/turns/stream", json=payload
    )
    second = client.post(
        f"/api/ai-chat/sessions/{conversation.id}/turns/stream", json=payload
    )

    assert first.status_code == second.status_code == 200
    assert calls == 1
    assert "saved" in second.text
    assert "event: done" in second.text


def test_unconfigured_and_provider_failure_emit_actionable_sanitized_error(
    engine, db, monkeypatch
):
    owner = _seed_user(db, "router-error")
    conversation = service.create_session(db, owner.id)
    client = TestClient(_app(engine, _claims(owner.id, "ai_chat:write")))
    response = client.post(
        f"/api/ai-chat/sessions/{conversation.id}/turns/stream",
        json={"request_id": "router_error_1", "content": "question"},
    )
    assert "event: error" in response.text
    assert "方案对话服务尚未配置，请联系管理员" in response.text

    _configured(db)

    def broken_stream(*_args, **_kwargs):
        raise RuntimeError("secret-key raw upstream body")
        yield

    monkeypatch.setattr(router, "chat_stream", broken_stream)
    response = client.post(
        f"/api/ai-chat/sessions/{conversation.id}/turns/stream",
        json={"request_id": "router_error_2", "content": "question"},
    )
    assert "event: error" in response.text
    assert "secret-key" not in response.text
    assert "raw upstream body" not in response.text


def test_closing_sse_generator_closes_upstream_and_saves_stopped_partial(db, monkeypatch):
    owner = _seed_user(db, "router-stop")
    conversation = service.create_session(db, owner.id)
    _configured(db)
    turn = service.begin_turn(
        db,
        owner.id,
        conversation.id,
        router.TurnStreamRequest(request_id="router_stop_01", content="question"),
    )
    closed = False

    class Upstream:
        def __iter__(self):
            return self

        def __next__(self):
            return {"type": "delta", "text": "partial"}

        def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr(router, "chat_stream", lambda *_args, **_kwargs: Upstream())
    events = router.stream_assistant_events(
        db,
        owner.id,
        conversation.id,
        turn.assistant_message,
        reused=False,
    )
    next(events)
    next(events)
    events.close()

    saved = db.get(AiChatMessage, turn.assistant_message.id)
    assert closed is True
    assert saved.status == "stopped"
    assert saved.content == "partial"


def test_retry_endpoint_appends_assistant_without_copying_user(engine, db, monkeypatch):
    owner = _seed_user(db, "router-retry")
    conversation = service.create_session(db, owner.id)
    _configured(db)
    user = AiChatMessage(
        session_id=conversation.id,
        role="user",
        request_id="original_router",
        content="question",
        status="completed",
    )
    failed = AiChatMessage(
        session_id=conversation.id,
        role="assistant",
        content="partial",
        status="failed",
    )
    db.add_all([user, failed])
    db.commit()
    monkeypatch.setattr(
        router,
        "chat_stream",
        lambda *_args, **_kwargs: iter(
            ({"type": "delta", "text": "retry"}, {"type": "done"})
        ),
    )
    client = TestClient(_app(engine, _claims(owner.id, "ai_chat:write")))
    response = client.post(
        f"/api/ai-chat/messages/{failed.id}/retry/stream",
        json={"request_id": "router_retry_1"},
    )
    assert response.status_code == 200
    assert db.query(AiChatMessage).filter_by(role="user").count() == 1
    retry = (
        db.query(AiChatMessage)
        .filter(AiChatMessage.retry_of_message_id == failed.id)
        .one()
    )
    assert retry.content == "retry"
    assert retry.status == "completed"


def test_duplicate_retry_while_streaming_does_not_call_model(engine, db, monkeypatch):
    owner = _seed_user(db, "router-retry-idempotent")
    conversation = service.create_session(db, owner.id)
    _configured(db)
    original = AiChatMessage(
        session_id=conversation.id,
        role="assistant",
        content="partial",
        status="failed",
    )
    db.add(original)
    db.commit()
    request = router.RetryStreamRequest(request_id="retry_inflight_1")
    service.begin_retry(db, owner.id, original.id, request)
    calls = 0

    def fake_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        yield {"type": "done"}

    monkeypatch.setattr(router, "chat_stream", fake_stream)
    client = TestClient(_app(engine, _claims(owner.id, "ai_chat:write")))
    response = client.post(
        f"/api/ai-chat/messages/{original.id}/retry/stream",
        json={"request_id": "retry_inflight_1"},
    )

    assert response.status_code == 200
    assert calls == 0
    assert "request_in_progress" in response.text
