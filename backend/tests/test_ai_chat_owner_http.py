"""HTTP owner-boundary checks that must fail before upload or turn mutation."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ai_chat import file_service, router, service
from app.ai_chat.models import AiChatMessage
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db


def _user(db, username):
    row = ArkUser(username=username, password_hash="test", real_name=username)
    db.add(row)
    db.commit()
    return row


def _client(engine, user_id):
    app = FastAPI()
    app.include_router(router.router, prefix="/api/ai-chat")
    SessionLocal = sessionmaker(bind=engine)

    def override_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(user_id),
        "permissions": ["ai_chat:write"],
        "roles": [],
    }
    return TestClient(app)


@pytest.mark.parametrize("operation", ["upload", "turn"])
def test_cross_owner_upload_and_turn_are_uniform_404(
    engine, db, monkeypatch, operation
):
    owner = _user(db, f"http-owner-{operation}")
    stranger = _user(db, f"http-stranger-{operation}")
    conversation = service.create_session(db, owner.id)
    storage_called = False

    def forbidden_store(*_args):
        nonlocal storage_called
        storage_called = True
        raise AssertionError("foreign upload reached private storage")

    monkeypatch.setattr(file_service, "normalize_and_store", forbidden_store)
    client = _client(engine, stranger.id)
    if operation == "upload":
        response = client.post(
            f"/api/ai-chat/sessions/{conversation.id}/attachments",
            files={"file": ("brief.txt", b"secret", "text/plain")},
        )
    else:
        response = client.post(
            f"/api/ai-chat/sessions/{conversation.id}/turns/stream",
            json={"request_id": "cross_owner_turn", "content": "secret"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "资源不存在"
    assert storage_called is False
    assert db.query(AiChatMessage).filter_by(session_id=conversation.id).count() == 0
