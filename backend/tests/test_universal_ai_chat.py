"""General workspace admission and model isolation on disposable SQLite only."""

import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ai.chat_config import validate_chat_options
from app.ai.models import AiPreset, AiProvider
from app.ai.preset_config import text_request_parameters
from app.ai_chat import router, service, workspace_service as workspace
from app.ai_chat.models import AiChatAttachment, AiChatMessage
from app.ai_chat.schemas import RetryStreamRequest, TurnStreamRequest
from app.auth.dependencies import get_current_user
from app.auth.models import ArkRole, ArkUser, ArkUserRole, ArkPermission, ArkRolePermission
from app.core.config import get_settings
from app.core.database import get_db


@pytest.fixture
def owner(db):
    user = ArkUser(username="chat-user", password_hash="test", real_name="Chat User")
    db.add(user)
    role = ArkRole(name='chat_writer', label='Chat writer')
    permission = ArkPermission(code='ai_chat:write', module='ai_chat', action='write', label='Write')
    db.add_all([role, permission])
    db.flush()
    db.add_all([ArkUserRole(user_id=user.id, role_id=role.id), ArkRolePermission(role_id=role.id, permission_id=permission.id)])
    db.commit()
    return user


def model(db, name="general", *, roles=None, vision=False, enabled=True, api_type="openai"):
    provider = AiProvider(name=name, provider_type="direct", api_type=api_type,
                          api_base="https://provider.invalid/v1", api_key="private-key", is_enabled=True)
    db.add(provider)
    db.flush()
    preset = AiPreset(preset_name=name, provider_id=provider.id, model=f"{name}-model", is_enabled=True,
                      system_prompt="private-prompt", parameters={"max_tokens": 123,
                      "chat": {"enabled": enabled, "label": name, "vision": vision, "allowed_roles": roles or []}})
    db.add(preset)
    db.commit()
    return preset, provider


def request(preset_id, key="first_request"):
    return TurnStreamRequest(request_id=key, content="hello", preset_id=preset_id)


def client(engine, user_id, permissions=("ai_chat:read", "ai_chat:write")):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/ai-chat")
    factory = sessionmaker(bind=engine)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: {"sub": str(user_id), "roles": [], "permissions": list(permissions)}
    return TestClient(app)


def test_catalog_only_publishes_allowed_text_models_without_private_configuration(db, owner):
    first, _ = model(db)
    hidden, _ = model(db, "hidden", enabled=False)
    restricted, _ = model(db, "restricted", roles=["designer"])
    image, _ = model(db, "image")
    image.parameters = {**image.parameters, "test_mode": "image"}
    db.commit()
    items = workspace.list_models(db, owner.id)
    assert [item["preset_id"] for item in items] == [first.id]
    payload = json.dumps(items)
    for secret in ("private-key", "private-prompt", "provider.invalid", "allowed_roles", "parameters"):
        assert secret not in payload
    for unavailable in (hidden, restricted, image):
        with pytest.raises(workspace.WorkspaceError):
            workspace.resolve_model(db, owner.id, unavailable.id)


def test_role_change_and_disabled_provider_take_effect_on_next_generation(db, owner):
    preset, provider = model(db, roles=["designer"])
    role = ArkRole(name="designer", label="设计师")
    db.add(role)
    db.flush()
    link = ArkUserRole(user_id=owner.id, role_id=role.id)
    db.add(link)
    db.commit()
    snapshot = workspace.resolve_model(db, owner.id, preset.id)
    db.delete(link)
    db.commit()
    with pytest.raises(workspace.WorkspaceError):
        workspace.validate_generation(db, owner.id, snapshot)
    preset.parameters = {"chat": {"enabled": True}}
    provider.is_enabled = False
    db.commit()
    assert not workspace.list_models(db, owner.id)


def test_model_selection_snapshot_replay_and_changed_request_conflict(db, owner):
    first, _ = model(db)
    second, _ = model(db, "second", api_type="anthropic")
    session = service.create_session(db, owner.id)
    turn = workspace.begin_turn(db, owner.id, session.id, request(first.id))
    assert turn.assistant_message.model_snapshot["model"] == "general-model"
    assert session.selected_preset_id == first.id
    replay = workspace.begin_turn(db, owner.id, session.id, request(first.id))
    assert replay.reused and replay.assistant_message.id == turn.assistant_message.id
    assert workspace.usage(db, owner.id)["used"] == 1
    with pytest.raises(service.RequestConflictError):
        workspace.begin_turn(db, owner.id, session.id, request(second.id))
    service.finish_turn(db, owner.id, turn.assistant_message.id, "first answer")
    next_turn = workspace.begin_turn(db, owner.id, session.id, request(second.id, "second_request"))
    assert next_turn.assistant_message.model_snapshot["model"] == "second-model"
    assert session.selected_preset_id == second.id
    assert turn.assistant_message.model_snapshot["model"] == "general-model"


def test_config_change_between_admission_and_stream_fails_explicitly(db, owner):
    preset, _ = model(db)
    snapshot = workspace.resolve_model(db, owner.id, preset.id)
    preset.model = "replacement"
    db.commit()
    with pytest.raises(workspace.WorkspaceError, match="配置已更新"):
        workspace.validate_generation(db, owner.id, snapshot)


def test_regeneration_keeps_history_but_sends_only_latest_answer(db, owner):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    turn = workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    service.finish_turn(db, owner.id, turn.assistant_message.id, "old answer")
    regen = workspace.begin_retry(db, owner.id, turn.assistant_message.id,
                                 RetryStreamRequest(request_id="regenerate_1", preset_id=preset.id))
    service.finish_turn(db, owner.id, regen.assistant_message.id, "new answer")
    context = service.build_context(db, owner.id, session.id)
    assert [message["content"] for message in context] == ["hello", "new answer"]
    assert db.get(AiChatMessage, turn.assistant_message.id).content == "old answer"
    workspace.begin_turn(db, owner.id, session.id, request(preset.id, "second_request"))
    with pytest.raises(service.RequestConflictError):
        service.begin_retry(db, owner.id, turn.assistant_message.id, RetryStreamRequest(request_id="too_old_retry"))


def test_busy_conversation_rejects_other_generation_without_reserving_quota(db, owner):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    with pytest.raises(workspace.WorkspaceError, match="仍在生成"):
        workspace.begin_turn(db, owner.id, session.id, request(preset.id, "second_request"))
    assert workspace.usage(db, owner.id)["used"] == 1


def test_image_model_switch_rejects_without_silently_losing_image_context(db, owner):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    image = AiChatAttachment(session_id=session.id, original_name="image.png", mime_type="image/png",
                             file_size=1, storage_path="private/test.png", attachment_type="image",
                             status="draft", created_by=owner.id)
    db.add(image)
    db.commit()
    body = request(preset.id)
    body.attachment_ids = [image.id]
    with pytest.raises(workspace.WorkspaceError, match="包含图片"):
        workspace.begin_turn(db, owner.id, session.id, body)
    assert db.query(AiChatMessage).count() == 0


def test_deleted_session_hides_every_resource_and_preserves_usage(db, owner):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    turn = workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    with pytest.raises(workspace.WorkspaceError, match="停止生成"):
        workspace.delete_session(db, owner.id, session.id)
    db.rollback()
    service.finish_turn(db, owner.id, turn.assistant_message.id, "answer")
    attachment = AiChatAttachment(session_id=session.id, original_name="a.txt", mime_type="text/plain",
                                  file_size=1, storage_path="private/test.txt", attachment_type="document",
                                  status="draft", created_by=owner.id)
    db.add(attachment)
    db.commit()
    ids = session.id, turn.assistant_message.id, attachment.id
    workspace.delete_session(db, owner.id, session.id)
    for accessor, resource_id in zip((service.get_session, service.get_message, service.get_attachment), ids):
        with pytest.raises(service.ResourceNotFoundError):
            accessor(db, resource_id, owner.id)
    assert not service.list_sessions(db, owner.id).items
    assert workspace.usage(db, owner.id)["used"] == 1


def test_quota_uses_beijing_midnight_and_replay_is_free(db, owner, monkeypatch):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    monkeypatch.setattr(get_settings(), "AI_CHAT_DAILY_TURN_LIMIT", 1)
    now = datetime(2026, 11, 16, 23, 59, 59)
    monkeypatch.setattr(workspace, "beijing_now", lambda: now)
    monkeypatch.setattr(service, "beijing_now", lambda: now)
    turn = workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    service.finish_turn(db, owner.id, turn.assistant_message.id, "done")
    assert workspace.begin_turn(db, owner.id, session.id, request(preset.id)).reused
    with pytest.raises(workspace.WorkspaceError, match="次数已用完"):
        workspace.begin_turn(db, owner.id, session.id, request(preset.id, "second_request"))
    now += timedelta(seconds=1)
    assert workspace.usage(db, owner.id)["remaining"] == 1


@pytest.mark.parametrize("api_type", ["openai", "anthropic"])
def test_http_stream_uses_selected_model_and_persists_reasoning(engine, db, owner, monkeypatch, api_type):
    preset, _ = model(db, api_type=api_type)
    session = service.create_session(db, owner.id)
    calls = []
    def stream(_db, preset_name, messages, **kwargs):
        calls.append((preset_name, messages))
        yield {"type": "reasoning", "text": "visible reasoning"}
        yield {"type": "delta", "text": "answer"}
        yield {"type": "done"}
    monkeypatch.setattr(router, "chat_stream", stream)
    http = client(engine, owner.id)
    response = http.post(f"/api/ai-chat/sessions/{session.id}/turns/stream", json=request(preset.id).model_dump())
    assert response.status_code == 200, response.text
    assert "event: reasoning" in response.text and "event: done" in response.text
    assert calls[0][0] == preset.preset_name
    detail = http.get(f"/api/ai-chat/sessions/{session.id}").json()["data"]
    assistant = detail["messages"][-1]
    assert assistant["model"]["model"] == preset.model
    assert assistant["reasoning_content"] == "visible reasoning"
    assert "private-key" not in json.dumps(detail) and "config_version" not in json.dumps(detail)
    assert all(message["content"] != "visible reasoning" for message in service.build_context(db, owner.id, session.id))


def test_http_rename_delete_and_model_injection_enforce_boundaries(engine, db, owner):
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    stranger = ArkUser(username="other", password_hash="test", real_name="Other")
    db.add(stranger)
    db.commit()
    other = client(engine, stranger.id)
    path = f"/api/ai-chat/sessions/{session.id}"
    assert other.patch(path, json={"title": "stolen"}).status_code == 404
    assert other.delete(path).status_code == 404
    readonly = client(engine, owner.id, ("ai_chat:read",))
    assert readonly.patch(path, json={"title": "new"}).status_code == 403
    http = client(engine, owner.id)
    assert http.patch(path, json={"title": "renamed"}).json()["data"]["title"] == "renamed"
    body = {**request(preset.id).model_dump(), "api_base": "https://evil.invalid", "model": "unauthorized"}
    assert http.post(path + "/turns/stream", json=body).status_code == 422
    assert http.delete(path).status_code == 200
    assert http.get(path).status_code == 404


def test_chat_metadata_never_reaches_provider_and_invalid_roles_are_rejected():
    assert text_request_parameters({"chat": {"enabled": True, "allowed_roles": ["admin"]}, "temperature": 0.4}) == {"temperature": 0.4}
    for value in ({"enabled": "yes"}, {"vision": 1}, {"allowed_roles": "admin"}, {"unknown": True}):
        with pytest.raises(ValueError):
            validate_chat_options(value)


def test_publishing_chat_does_not_break_existing_trusted_text_consumers(db):
    from app.ai.text_snapshot import prepare_text_chat
    preset, _ = model(db)
    snapshot = prepare_text_chat(db, preset.preset_name, 1000)
    assert snapshot.preset.parameters == {"max_tokens": 123}


@pytest.mark.parametrize("image_options", [
    {"studio": {"enabled": True}}, {"api_style": "images"}, {"api_style": "chat"},
])
def test_text_test_mode_cannot_publish_an_image_preset(db, owner, image_options):
    preset, _ = model(db)
    preset.parameters = {**preset.parameters, **image_options, "test_mode": "text"}
    db.commit()
    assert workspace.list_models(db, owner.id) == []
    with pytest.raises(workspace.WorkspaceError):
        workspace.resolve_model(db, owner.id, preset.id)


@pytest.mark.parametrize("host_offset", [-8, 0, 9])
def test_quota_reset_and_soft_delete_use_beijing_time_on_other_hosts(db, owner, monkeypatch, host_offset):
    from datetime import timezone
    from app.core import time as clock
    now = datetime(2026, 11, 16, 15, 59, 59, tzinfo=timezone.utc)
    class HostClock(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.astimezone(timezone(timedelta(hours=host_offset))).replace(tzinfo=None)
            return now.astimezone(tz)
    monkeypatch.setattr(clock, "datetime", HostClock)
    preset, _ = model(db)
    session = service.create_session(db, owner.id)
    turn = workspace.begin_turn(db, owner.id, session.id, request(preset.id))
    service.finish_turn(db, owner.id, turn.assistant_message.id, "answer")
    assert workspace.usage(db, owner.id)["used"] == 1
    now += timedelta(seconds=1)
    assert workspace.usage(db, owner.id)["used"] == 0
    workspace.delete_session(db, owner.id, session.id)
    db.refresh(session)
    assert session.deleted_at == datetime(2026, 11, 17, 0, 0)
