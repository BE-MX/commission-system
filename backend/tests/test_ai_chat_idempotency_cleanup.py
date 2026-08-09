"""Regression tests for request identity and recoverable draft deletion."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.ai_chat import file_service, router, service
from app.ai_chat.models import AiChatAttachment, AiChatMessage
from app.ai_chat.schemas import RetryStreamRequest, TurnStreamRequest
from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.core.database import get_db


def _owner_and_session(db, username):
    owner = ArkUser(username=username, password_hash="test", real_name=username)
    db.add(owner)
    db.commit()
    conversation = service.create_session(db, owner.id)
    return owner, conversation


def _draft(db, owner_id, session_id, name):
    row = AiChatAttachment(
        session_id=session_id,
        original_name=name,
        mime_type="text/plain",
        file_size=1,
        storage_path=f"documents/{name}",
        attachment_type="document",
        extracted_text="x",
        status="draft",
        created_by=owner_id,
    )
    db.add(row)
    db.commit()
    return row


def _client(engine, owner_id):
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
        "sub": str(owner_id),
        "permissions": ["ai_chat:write"],
        "roles": [],
    }
    return TestClient(app)


def test_same_request_reuses_only_equivalent_normalized_content(db):
    owner, conversation = _owner_and_session(db, "identity-content")
    first = service.begin_turn(
        db,
        owner.id,
        conversation.id,
        TurnStreamRequest(request_id="identity_content", content="  same text  "),
    )
    repeated = service.begin_turn(
        db,
        owner.id,
        conversation.id,
        TurnStreamRequest(request_id="identity_content", content="same text"),
    )
    assert repeated.reused is True
    assert repeated.user_message.id == first.user_message.id

    with pytest.raises(service.RequestConflictError):
        service.begin_turn(
            db,
            owner.id,
            conversation.id,
            TurnStreamRequest(request_id="identity_content", content="different"),
        )


def test_same_request_with_different_attachment_set_conflicts(db):
    owner, conversation = _owner_and_session(db, "identity-attachments")
    first_draft = _draft(db, owner.id, conversation.id, "first.txt")
    second_draft = _draft(db, owner.id, conversation.id, "second.txt")
    service.begin_turn(
        db,
        owner.id,
        conversation.id,
        TurnStreamRequest(
            request_id="identity_attach",
            content="analyze",
            attachment_ids=[first_draft.id],
        ),
    )

    with pytest.raises(service.RequestConflictError):
        service.begin_turn(
            db,
            owner.id,
            conversation.id,
            TurnStreamRequest(
                request_id="identity_attach",
                content="analyze",
                attachment_ids=[second_draft.id],
            ),
        )


def test_turn_request_identity_conflict_is_http_409(engine, db):
    owner, conversation = _owner_and_session(db, "identity-http")
    service.begin_turn(
        db,
        owner.id,
        conversation.id,
        TurnStreamRequest(request_id="identity_http_1", content="original"),
    )
    response = _client(engine, owner.id).post(
        f"/api/ai-chat/sessions/{conversation.id}/turns/stream",
        json={"request_id": "identity_http_1", "content": "changed"},
    )
    assert response.status_code == 409
    assert "请求标识" in response.json()["detail"]


def test_retry_request_id_cannot_move_to_another_original(db):
    owner, conversation = _owner_and_session(db, "identity-retry")
    user = AiChatMessage(
        session_id=conversation.id,
        role="user",
        request_id="identity_retry_user",
        content="question",
        status="completed",
    )
    db.add(user)
    db.flush()
    originals = [
        AiChatMessage(
            session_id=conversation.id,
            role="assistant",
            reply_to_message_id=user.id,
            content="partial",
            status="failed",
        )
        for _ in range(2)
    ]
    db.add_all(originals)
    db.commit()
    request = RetryStreamRequest(request_id="identity_retry_1")
    service.begin_retry(db, owner.id, originals[0].id, request)

    with pytest.raises(service.RequestConflictError):
        service.begin_retry(db, owner.id, originals[1].id, request)
    assert (
        db.query(AiChatMessage)
        .filter(AiChatMessage.request_id == request.request_id)
        .count()
        == 1
    )


def test_file_delete_failure_keeps_draft_record(db, monkeypatch):
    owner, conversation = _owner_and_session(db, "delete-file-failure")
    draft = _draft(db, owner.id, conversation.id, "keep.txt")

    def fail_delete(_path):
        raise file_service.FileStorageError("disk unavailable")

    monkeypatch.setattr(file_service, "delete_private_file", fail_delete)
    with pytest.raises(file_service.FileStorageError):
        service.delete_draft_attachment(db, owner.id, draft.id)
    assert db.get(AiChatAttachment, draft.id) is not None


def test_db_delete_failure_can_be_retried_after_file_is_gone(db, monkeypatch):
    owner, conversation = _owner_and_session(db, "delete-db-failure")
    draft = _draft(db, owner.id, conversation.id, "retry.txt")
    deleted_paths = []
    monkeypatch.setattr(file_service, "delete_private_file", deleted_paths.append)
    original_commit = db.commit
    attempts = 0

    def fail_commit_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("db commit failed")
        return original_commit()

    monkeypatch.setattr(db, "commit", fail_commit_once)
    with pytest.raises(RuntimeError, match="db commit failed"):
        service.delete_draft_attachment(db, owner.id, draft.id)
    assert db.get(AiChatAttachment, draft.id) is not None

    service.delete_draft_attachment(db, owner.id, draft.id)
    assert db.get(AiChatAttachment, draft.id) is None
    assert deleted_paths == ["documents/retry.txt", "documents/retry.txt"]
