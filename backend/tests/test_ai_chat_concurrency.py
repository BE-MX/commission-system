"""Real overlapping SQLite transactions for turn idempotency and draft claims."""

from threading import Barrier, Lock, Thread

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.ai.models import AiCallLog
from app.ai_chat import service
from app.ai_chat.models import AiChatAttachment, AiChatMessage, AiChatSession
from app.ai_chat.schemas import TurnStreamRequest
from app.auth.models import ArkUser
from app.core.database import Base


def _seed_owner_and_session(db, username="concurrency-owner"):
    owner = ArkUser(
        username=username,
        password_hash="test",
        real_name="Concurrency Owner",
    )
    db.add(owner)
    db.flush()
    owner_id = owner.id
    db.commit()
    conversation = service.create_session(db, owner_id)
    return owner_id, conversation.id


@pytest.fixture
def file_database(tmp_path):
    database_path = tmp_path / "ai-chat-concurrency.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 0.1},
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=100")

    tables = [
        ArkUser.__table__,
        AiCallLog.__table__,
        AiChatSession.__table__,
        AiChatMessage.__table__,
        AiChatAttachment.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    yield engine
    engine.dispose()


def _run_threads(SessionLocal, requests, owner_id, session_id):
    start = Barrier(2)
    lock = Lock()
    results = []
    errors = []

    def worker(request):
        db = SessionLocal()
        try:
            start.wait(timeout=3)
            result = service.begin_turn(db, owner_id, session_id, request)
            with lock:
                results.append(
                    {
                        "user_id": result.user_message.id,
                        "assistant_id": result.assistant_message.id,
                        "reused": result.reused,
                    }
                )
        except BaseException as exc:
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [Thread(target=worker, args=(request,)) for request in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    return results, errors


def test_interleaved_assistants_pair_to_their_explicit_user(db):
    owner_id, session_id = _seed_owner_and_session(db)
    user_one = AiChatMessage(
        session_id=session_id,
        role="user",
        request_id="interleave_req_1",
        content="one",
        status="completed",
    )
    user_two = AiChatMessage(
        session_id=session_id,
        role="user",
        request_id="interleave_req_2",
        content="two",
        status="completed",
    )
    db.add_all([user_one, user_two])
    db.flush()
    assistant_two = AiChatMessage(
        session_id=session_id,
        role="assistant",
        reply_to_message_id=user_two.id,
        content="",
        status="streaming",
    )
    assistant_one = AiChatMessage(
        session_id=session_id,
        role="assistant",
        reply_to_message_id=user_one.id,
        content="",
        status="streaming",
    )
    db.add_all([assistant_two, assistant_one])
    db.commit()

    first = service.begin_turn(
        db,
        owner_id,
        session_id,
        TurnStreamRequest(request_id="interleave_req_1", content="one"),
    )
    second = service.begin_turn(
        db,
        owner_id,
        session_id,
        TurnStreamRequest(request_id="interleave_req_2", content="two"),
    )
    assert first.assistant_message.id == assistant_one.id
    assert second.assistant_message.id == assistant_two.id


def test_overlapping_same_request_has_one_winner(file_database, monkeypatch):
    SessionLocal = sessionmaker(bind=file_database)
    seed_db = SessionLocal()
    owner_id, session_id = _seed_owner_and_session(seed_db, "same-request-owner")
    seed_db.close()
    rendezvous = Barrier(2)
    guard = Lock()
    pending_waiters = 0
    original_existing_turn = service._existing_turn

    def synchronized_existing_turn(db, target_session_id, request_id):
        nonlocal pending_waiters
        existing = original_existing_turn(db, target_session_id, request_id)
        should_wait = False
        if existing is None:
            with guard:
                if pending_waiters < 2:
                    pending_waiters += 1
                    should_wait = True
        if should_wait:
            rendezvous.wait(timeout=3)
        return existing

    monkeypatch.setattr(service, "_existing_turn", synchronized_existing_turn)
    request = TurnStreamRequest(request_id="parallel_same_1", content="same")
    results, errors = _run_threads(
        SessionLocal, [request, request], owner_id, session_id
    )

    assert errors == []
    assert len(results) == 2
    assert {result["user_id"] for result in results} == {results[0]["user_id"]}
    assert {result["assistant_id"] for result in results} == {
        results[0]["assistant_id"]
    }
    assert sorted(result["reused"] for result in results) == [False, True]
    verify_db = SessionLocal()
    assert verify_db.query(AiChatMessage).filter_by(session_id=session_id).count() == 2
    verify_db.close()


def test_overlapping_same_id_with_different_content_conflicts(
    file_database, monkeypatch
):
    SessionLocal = sessionmaker(bind=file_database)
    seed_db = SessionLocal()
    owner_id, session_id = _seed_owner_and_session(seed_db, "conflict-owner")
    seed_db.close()
    rendezvous = Barrier(2)
    guard = Lock()
    pending_waiters = 0
    original_existing_turn = service._existing_turn

    def synchronized_existing_turn(db, target_session_id, request_id):
        nonlocal pending_waiters
        existing = original_existing_turn(db, target_session_id, request_id)
        should_wait = False
        if existing is None:
            with guard:
                if pending_waiters < 2:
                    pending_waiters += 1
                    should_wait = True
        if should_wait:
            rendezvous.wait(timeout=3)
        return existing

    monkeypatch.setattr(service, "_existing_turn", synchronized_existing_turn)
    requests = [
        TurnStreamRequest(request_id="parallel_conflict", content=content)
        for content in ("first", "second")
    ]
    results, errors = _run_threads(
        SessionLocal, requests, owner_id, session_id
    )

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], service.RequestConflictError)
    verify_db = SessionLocal()
    assert verify_db.query(AiChatMessage).filter_by(session_id=session_id).count() == 2
    verify_db.close()


def test_overlapping_turns_have_one_draft_winner(file_database):
    SessionLocal = sessionmaker(bind=file_database)
    seed_db = SessionLocal()
    owner_id, session_id = _seed_owner_and_session(seed_db, "draft-owner")
    draft = AiChatAttachment(
        session_id=session_id,
        original_name="shared.txt",
        mime_type="text/plain",
        file_size=1,
        storage_path="documents/shared.txt",
        attachment_type="document",
        extracted_text="x",
        status="draft",
        created_by=owner_id,
    )
    seed_db.add(draft)
    seed_db.commit()
    draft_id = draft.id
    seed_db.close()
    requests = [
        TurnStreamRequest(
            request_id=f"claim_draft_{index}",
            content=f"claim {index}",
            attachment_ids=[draft_id],
        )
        for index in (1, 2)
    ]
    draft_reads = Barrier(2)

    def synchronize_draft_reads(
        _connection, _cursor, statement, _parameters, _context, _many
    ):
        if statement.lstrip().startswith("SELECT") and (
            "FROM ark_ai_chat_attachments" in statement
        ):
            draft_reads.wait(timeout=3)

    event.listen(file_database, "after_cursor_execute", synchronize_draft_reads)
    try:
        results, errors = _run_threads(
            SessionLocal, requests, owner_id, session_id
        )
    finally:
        event.remove(file_database, "after_cursor_execute", synchronize_draft_reads)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], service.ResourceNotFoundError)
    verify_db = SessionLocal()
    stored = verify_db.get(AiChatAttachment, draft_id)
    assert stored.status == "attached"
    assert stored.message_id == results[0]["user_id"]
    assert verify_db.query(AiChatMessage).filter_by(session_id=session_id).count() == 2
    verify_db.close()
