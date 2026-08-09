"""SQLite simulations for MySQL turn idempotency and attachment locking."""

from sqlalchemy.orm import sessionmaker

from app.ai_chat import service
from app.ai_chat.models import AiChatAttachment, AiChatMessage
from app.ai_chat.schemas import TurnStreamRequest
from app.auth.models import ArkUser


def _seed_owner_and_session(db):
    owner = ArkUser(
        username="concurrency-owner",
        password_hash="test",
        real_name="Concurrency Owner",
    )
    db.add(owner)
    db.commit()
    conversation = service.create_session(db, owner.id)
    return owner.id, conversation.id


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


def test_two_sessions_reuse_the_same_request_without_duplicate_messages(engine, db):
    owner_id, session_id = _seed_owner_and_session(db)
    SessionLocal = sessionmaker(bind=engine)
    first_db = SessionLocal()
    second_db = SessionLocal()
    request = TurnStreamRequest(request_id="parallel_same_1", content="same")
    try:
        first = service.begin_turn(first_db, owner_id, session_id, request)
        second = service.begin_turn(second_db, owner_id, session_id, request)
        assert second.reused is True
        assert second.user_message.id == first.user_message.id
        assert second.assistant_message.id == first.assistant_message.id
        assert (
            second_db.query(AiChatMessage).filter_by(session_id=session_id).count()
            == 2
        )
    finally:
        first_db.close()
        second_db.close()


def test_two_sessions_cannot_claim_the_same_draft_attachment(engine, db):
    # SQLite ignores FOR UPDATE, so two independent Sessions exercise the
    # post-commit contender sequentially. MySQL serializes the contenders on
    # the draft row; after the winner commits, the loser sees status=attached.
    owner_id, session_id = _seed_owner_and_session(db)
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
    db.add(draft)
    db.commit()
    draft_id = draft.id
    SessionLocal = sessionmaker(bind=engine)
    first_db = SessionLocal()
    second_db = SessionLocal()
    try:
        first = service.begin_turn(
            first_db,
            owner_id,
            session_id,
            TurnStreamRequest(
                request_id="claim_draft_1",
                content="first",
                attachment_ids=[draft_id],
            ),
        )
        assert first.user_message.id
        try:
            service.begin_turn(
                second_db,
                owner_id,
                session_id,
                TurnStreamRequest(
                    request_id="claim_draft_2",
                    content="second",
                    attachment_ids=[draft_id],
                ),
            )
        except service.ResourceNotFoundError as exc:
            assert str(exc) == "资源不存在"
        else:
            raise AssertionError("attached draft was claimed twice")
        second_db.refresh(second_db.get(AiChatAttachment, draft_id))
        assert second_db.get(AiChatAttachment, draft_id).message_id == first.user_message.id
    finally:
        first_db.close()
        second_db.close()
