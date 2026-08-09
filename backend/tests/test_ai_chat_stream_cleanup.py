"""Disconnect and terminal cleanup must survive hostile upstream close methods."""

from app.ai.models import AiPreset, AiProvider
from app.ai_chat import router, service
from app.ai_chat.models import AiChatMessage
from app.ai_chat.schemas import TurnStreamRequest
from app.auth.models import ArkUser


def _turn(db, username):
    owner = ArkUser(username=username, password_hash="test", real_name=username)
    db.add(owner)
    db.flush()
    provider = AiProvider(
        name=f"provider-{username}",
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
            is_enabled=True,
        )
    )
    db.commit()
    conversation = service.create_session(db, owner.id)
    turn = service.begin_turn(
        db,
        owner.id,
        conversation.id,
        TurnStreamRequest(
            request_id=f"cleanup_{username.replace('-', '_')}", content="question"
        ),
    )
    return owner.id, conversation.id, turn.assistant_message.id


class CloseRaises:
    def __init__(self, terminal=False):
        self.events = iter(
            [
                {"type": "delta", "text": "partial"},
                *([{"type": "done"}] if terminal else []),
            ]
        )
        self.close_calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.events)

    def close(self):
        self.close_calls += 1
        raise RuntimeError("hostile upstream close")


def _spy_close(db, monkeypatch):
    original_close = db.close
    calls = []

    def close():
        calls.append(True)
        original_close()

    monkeypatch.setattr(db, "close", close)
    return calls


def test_disconnect_saves_stopped_before_close_failure(db, monkeypatch):
    owner_id, session_id, assistant_id = _turn(db, "disconnect-close")
    upstream = CloseRaises()
    monkeypatch.setattr(router, "chat_stream", lambda *_args, **_kwargs: upstream)
    close_calls = _spy_close(db, monkeypatch)
    assistant = db.get(AiChatMessage, assistant_id)
    events = router.stream_assistant_events(
        db, owner_id, session_id, assistant, reused=False
    )
    next(events)
    next(events)
    next(events)
    events.close()

    saved = db.get(AiChatMessage, assistant_id)
    assert saved.status == "stopped"
    assert saved.content == "partial"
    assert upstream.close_calls >= 1
    assert close_calls


def test_normal_terminal_ignores_close_failure_and_closes_db(db, monkeypatch):
    owner_id, session_id, assistant_id = _turn(db, "terminal-close")
    upstream = CloseRaises(terminal=True)
    monkeypatch.setattr(router, "chat_stream", lambda *_args, **_kwargs: upstream)
    close_calls = _spy_close(db, monkeypatch)
    assistant = db.get(AiChatMessage, assistant_id)

    events = list(
        router.stream_assistant_events(
            db, owner_id, session_id, assistant, reused=False
        )
    )

    assert any(b"event: done" in event for event in events)
    assert db.get(AiChatMessage, assistant_id).status == "completed"
    assert upstream.close_calls >= 1
    assert close_calls
