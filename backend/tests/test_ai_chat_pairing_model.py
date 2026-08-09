"""Real SQLite FK checks for explicit assistant-to-user pairing."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.models import AiCallLog
from app.ai_chat.models import AiChatAttachment, AiChatMessage, AiChatSession
from app.auth.models import ArkUser
from app.core.database import Base


@pytest.fixture
def pairing_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        ArkUser.__table__,
        AiCallLog.__table__,
        AiChatSession.__table__,
        AiChatMessage.__table__,
        AiChatAttachment.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.execute(
            ArkUser.__table__.insert().values(
                id=1,
                username="pair-owner",
                password_hash="hash",
                real_name="Pair Owner",
            )
        )
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    engine.dispose()


def _seed_sessions_and_user(db):
    db.add_all(
        [
            AiChatSession(id=10, owner_user_id=1, title="会话一"),
            AiChatSession(id=20, owner_user_id=1, title="会话二"),
            AiChatMessage(
                id=100,
                session_id=10,
                role="user",
                content="消息",
                status="completed",
            ),
            AiChatMessage(
                id=200,
                session_id=20,
                role="user",
                content="另一会话消息",
                status="completed",
            ),
        ]
    )
    db.commit()


def test_reply_to_user_must_stay_in_the_same_session(pairing_db):
    _seed_sessions_and_user(pairing_db)
    pairing_db.add(
        AiChatMessage(
            id=101,
            session_id=10,
            role="assistant",
            reply_to_message_id=100,
            content="",
            status="streaming",
        )
    )
    pairing_db.commit()
    pairing_db.add(
        AiChatMessage(
            id=102,
            session_id=20,
            role="assistant",
            reply_to_message_id=100,
            content="",
            status="streaming",
        )
    )
    with pytest.raises(IntegrityError):
        pairing_db.commit()


def test_retry_and_reply_targets_are_both_session_scoped(pairing_db):
    _seed_sessions_and_user(pairing_db)
    original = AiChatMessage(
        id=101,
        session_id=10,
        role="assistant",
        reply_to_message_id=100,
        content="partial",
        status="failed",
    )
    pairing_db.add(original)
    pairing_db.commit()
    pairing_db.add(
        AiChatMessage(
            id=102,
            session_id=20,
            role="assistant",
            reply_to_message_id=200,
            retry_of_message_id=original.id,
            content="",
            status="streaming",
        )
    )
    with pytest.raises(IntegrityError):
        pairing_db.commit()
