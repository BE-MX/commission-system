"""Persistence and schema invariants for the Customer AI Chat domain."""

from datetime import datetime
from importlib import util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.models import AiCallLog
from app.ai_chat.models import AiChatAttachment, AiChatMessage, AiChatSession
from app.ai_chat.schemas import (
    AttachmentResponse,
    MessageResponse,
    SessionCreate,
    SessionResponse,
    TurnStreamRequest,
)
from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.auth.service import seed_role_permissions
from app.core.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migration_module():
    path = BACKEND_ROOT / "alembic" / "versions" / "100_ai_chat_mvp.py"
    spec = util.spec_from_file_location("migration_100_ai_chat_mvp", path)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render_mysql_upgrade_ddl() -> str:
    migration = _migration_module()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="mysql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration.upgrade()
    return output.getvalue()


def _constraint_names(table, constraint_type):
    return {
        item.name for item in table.constraints if isinstance(item, constraint_type)
    }


@pytest.fixture
def fk_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    from app.core.database import Base

    tables = [model.__table__ for model in (
        ArkUser, AiCallLog, AiChatSession, AiChatMessage, AiChatAttachment
    )]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.execute(
            ArkUser.__table__.insert().values(
                id=1, username="owner", password_hash="hash", real_name="Owner"
            )
        )
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    engine.dispose()


def _message(message_id, session_id, **values):
    fields = {"role": "user", "content": "消息", "status": "completed"}
    fields.update(values)
    return AiChatMessage(id=message_id, session_id=session_id, **fields)


def _attachment(attachment_id, session_id, message_id):
    return AiChatAttachment(
        id=attachment_id,
        session_id=session_id,
        message_id=message_id,
        original_name=f"{attachment_id}.md",
        mime_type="text/markdown",
        file_size=10,
        storage_path=f"documents/{attachment_id}.md",
        attachment_type="document",
        status="attached",
        created_by=1,
    )


def _seed_two_sessions_and_message(db):
    db.add_all([
        AiChatSession(id=10, owner_user_id=1, title="会话一"),
        AiChatSession(id=20, owner_user_id=1, title="会话二"),
        _message(100, 10),
    ])
    db.commit()


def test_ai_chat_tables_and_indexes_match_the_domain_contract():
    assert AiChatSession.__tablename__ == "ark_ai_chat_sessions"
    assert AiChatMessage.__tablename__ == "ark_ai_chat_messages"
    assert AiChatAttachment.__tablename__ == "ark_ai_chat_attachments"

    session_indexes = {index.name for index in AiChatSession.__table__.indexes}
    message_indexes = {index.name for index in AiChatMessage.__table__.indexes}
    attachment_indexes = {index.name for index in AiChatAttachment.__table__.indexes}

    assert "idx_ai_chat_session_owner_updated" in session_indexes
    assert "idx_ai_chat_message_session_created" in message_indexes
    assert "idx_ai_chat_message_reply_to" in message_indexes
    assert {
        "idx_ai_chat_attachment_session_created",
        "idx_ai_chat_attachment_draft_status",
    } <= attachment_indexes


def test_message_idempotency_and_attachment_ownership_constraints():
    message_table = AiChatMessage.__table__
    assert "uq_ai_chat_message_session_request" in _constraint_names(
        message_table, UniqueConstraint
    )
    assert AiChatAttachment.__table__.c.message_id.nullable is True
    assert isinstance(AiChatSession.__table__.c.id.type, BigInteger)
    assert isinstance(AiChatMessage.__table__.c.id.type, BigInteger)
    assert isinstance(AiChatAttachment.__table__.c.id.type, BigInteger)

    mysql_dialect = mysql.dialect()
    for column in (
        AiChatSession.__table__.c.owner_user_id,
        AiChatAttachment.__table__.c.created_by,
    ):
        assert column.type.dialect_impl(mysql_dialect).unsigned is True


def test_cross_session_attachment_is_rejected_but_same_session_binding_succeeds(
    fk_db,
):
    _seed_two_sessions_and_message(fk_db)
    fk_db.add(_attachment(200, 10, 100))
    fk_db.commit()
    fk_db.add(_attachment(201, 20, 100))
    with pytest.raises(IntegrityError):
        fk_db.commit()


def test_domain_constraints_are_named_and_cover_reference_and_enum_invariants():
    message_table = AiChatMessage.__table__
    attachment_table = AiChatAttachment.__table__
    assert "uq_ai_chat_message_session_id" in _constraint_names(
        message_table, UniqueConstraint
    )
    assert "fk_ai_chat_message_retry_session" in _constraint_names(
        message_table, ForeignKeyConstraint
    )
    assert "fk_ai_chat_message_reply_session" in _constraint_names(
        message_table, ForeignKeyConstraint
    )
    assert "fk_ai_chat_attachment_message_session" in _constraint_names(
        attachment_table, ForeignKeyConstraint
    )
    checks = _constraint_names(message_table, CheckConstraint) | _constraint_names(
        attachment_table, CheckConstraint
    )
    assert checks == {
        "ck_ai_chat_message_role",
        "ck_ai_chat_message_status",
        "ck_ai_chat_attachment_type",
        "ck_ai_chat_attachment_status",
    }


def test_foreign_keys_are_restrictive_and_relationships_do_not_implicitly_load():
    expected_targets = {
        "ark_ai_chat_sessions.owner_user_id": {"ark_users.id"},
        "ark_ai_chat_messages.session_id": {
            "ark_ai_chat_sessions.id",
            "ark_ai_chat_messages.session_id",
        },
        "ark_ai_chat_messages.retry_of_message_id": {"ark_ai_chat_messages.id"},
        "ark_ai_chat_messages.reply_to_message_id": {"ark_ai_chat_messages.id"},
        "ark_ai_chat_messages.ai_call_log_id": {"ark_ai_call_logs.id"},
        "ark_ai_chat_attachments.session_id": {
            "ark_ai_chat_sessions.id",
            "ark_ai_chat_messages.session_id",
        },
        "ark_ai_chat_attachments.message_id": {"ark_ai_chat_messages.id"},
        "ark_ai_chat_attachments.created_by": {"ark_users.id"},
    }

    for qualified_column, target in expected_targets.items():
        table_name, column_name = qualified_column.split(".")
        table = {
            AiChatSession.__tablename__: AiChatSession.__table__,
            AiChatMessage.__tablename__: AiChatMessage.__table__,
            AiChatAttachment.__tablename__: AiChatAttachment.__table__,
        }[table_name]
        foreign_keys = table.c[column_name].foreign_keys
        assert {foreign_key.target_fullname for foreign_key in foreign_keys} == target
        assert {foreign_key.ondelete for foreign_key in foreign_keys} == {"RESTRICT"}

    for mapper in (
        AiChatSession.__mapper__,
        AiChatMessage.__mapper__,
        AiChatAttachment.__mapper__,
    ):
        assert mapper.relationships
        assert all(relationship.lazy == "noload" for relationship in mapper.relationships)


def test_session_create_accepts_an_optional_title_and_forbids_extra_fields():
    assert SessionCreate().title is None
    assert SessionCreate(title="方案讨论").title == "方案讨论"

    with pytest.raises(ValidationError):
        SessionCreate(title="x" * 201)
    with pytest.raises(ValidationError):
        SessionCreate(title="方案讨论", unexpected=True)


def test_ai_chat_settings_have_positive_bounded_defaults():
    settings = Settings(_env_file=None)

    assert settings.AI_CHAT_STORAGE_ROOT == r"D:\WORKSOURCE\ai-chat"
    assert settings.AI_CHAT_MAX_UPLOAD_BYTES == 4 * 1024 * 1024
    assert settings.AI_CHAT_MAX_ATTACHMENTS == 5
    assert settings.AI_CHAT_MAX_ATTACHMENT_CHARS == 60_000
    assert settings.AI_CHAT_MAX_TURN_ATTACHMENT_CHARS == 120_000

    max_length = next(
        item.max_length
        for item in TurnStreamRequest.model_fields["attachment_ids"].metadata
        if hasattr(item, "max_length")
    )
    assert max_length == settings.AI_CHAT_MAX_ATTACHMENTS


@pytest.mark.parametrize(
    "field_name",
    [
        "AI_CHAT_MAX_UPLOAD_BYTES",
        "AI_CHAT_MAX_ATTACHMENTS",
        "AI_CHAT_MAX_ATTACHMENT_CHARS",
        "AI_CHAT_MAX_TURN_ATTACHMENT_CHARS",
    ],
)
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_ai_chat_numeric_settings_must_be_positive(field_name, invalid_value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field_name: invalid_value})


@pytest.mark.parametrize(
    "payload",
    [
        {"request_id": "turn-0001", "content": "", "attachment_ids": []},
        {
            "request_id": "turn-0001",
            "content": "分析",
            "attachment_ids": [1, 2, 3, 4, 5, 6],
        },
    ],
)
def test_turn_request_rejects_blank_turn_and_more_than_five_attachments(payload):
    with pytest.raises(ValidationError):
        TurnStreamRequest(**payload)


@pytest.mark.parametrize(
    "request_id",
    [
        "short",
        "x" * 65,
        "contains space",
        "contains.dot",
        "中文请求标识",
    ],
)
def test_turn_request_validates_request_id(request_id):
    with pytest.raises(ValidationError):
        TurnStreamRequest(request_id=request_id, content="分析")


@pytest.mark.parametrize("attachment_ids", [[0], [-1], [1, 1]])
def test_turn_request_requires_unique_positive_attachment_ids(attachment_ids):
    with pytest.raises(ValidationError):
        TurnStreamRequest(
            request_id="turn-0001",
            content="分析",
            attachment_ids=attachment_ids,
        )


def test_turn_request_forbids_extra_fields_and_accepts_attachment_only_turns():
    request = TurnStreamRequest(request_id="turn_0001", attachment_ids=[1, 2])
    assert request.content == ""

    with pytest.raises(ValidationError):
        TurnStreamRequest(
            request_id="turn-0001",
            content="分析",
            unexpected=True,
        )


def test_response_schemas_serialize_models_without_private_attachment_content():
    now = datetime(2026, 8, 9, 10, 30)
    session = AiChatSession(
        id=1,
        owner_user_id=7,
        title="客户方案",
        created_at=now,
        updated_at=now,
    )
    message = AiChatMessage(
        id=2,
        session_id=1,
        role="user",
        request_id="turn-0001",
        content="分析附件",
        status="completed",
        created_at=now,
        updated_at=now,
    )
    attachment = AiChatAttachment(
        id=3,
        session_id=1,
        message_id=2,
        original_name="brief.md",
        mime_type="text/markdown",
        file_size=128,
        storage_path="documents/private-file.md",
        attachment_type="document",
        extracted_text="confidential source text",
        status="attached",
        created_by=7,
        created_at=now,
    )

    assert SessionResponse.model_validate(session).id == 1
    message_data = MessageResponse.model_validate(message).model_dump()
    assert message_data["content"] == "分析附件"
    assert "ai_call_log_id" not in message_data
    assert "reply_to_message_id" not in message_data
    attachment_data = AttachmentResponse.model_validate(attachment).model_dump()
    assert attachment_data["original_name"] == "brief.md"
    assert "storage_path" not in attachment_data
    assert "extracted_text" not in attachment_data


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("role", "system"), ("status", "queued")],
)
def test_message_response_rejects_unknown_domain_values(field_name, invalid_value):
    now = datetime(2026, 8, 9, 10, 30)
    payload = {
        "id": 1,
        "session_id": 1,
        "role": "assistant",
        "request_id": None,
        "content": "answer",
        "status": "completed",
        "created_at": now,
        "updated_at": now,
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        MessageResponse.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [("attachment_type", "archive"), ("status", "deleted")],
)
def test_attachment_response_rejects_unknown_domain_values(field_name, invalid_value):
    payload = {
        "id": 1,
        "session_id": 1,
        "message_id": None,
        "original_name": "brief.md",
        "mime_type": "text/markdown",
        "file_size": 10,
        "attachment_type": "document",
        "status": "draft",
        "created_by": 1,
        "created_at": datetime(2026, 8, 9, 10, 30),
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        AttachmentResponse.model_validate(payload)


def test_ai_chat_migration_has_one_forward_revision_and_complete_reverse_downgrade(
    monkeypatch,
):
    migration = _migration_module()
    calls = []
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **kwargs: calls.append(("drop_index", name, kwargs["table_name"])),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda name: calls.append(("drop_table", name)),
    )

    migration.downgrade()

    assert migration.revision == "100_ai_chat_mvp"
    assert migration.down_revision == "099_sales_automation"
    assert len(migration.revision) <= 32
    assert [call for call in calls if call[0] == "drop_table"] == [
        ("drop_table", "ark_ai_chat_attachments"),
        ("drop_table", "ark_ai_chat_messages"),
        ("drop_table", "ark_ai_chat_sessions"),
    ]


def test_message_content_text_has_no_invalid_mysql_default():
    ddl = _render_mysql_upgrade_ddl()
    message_table_ddl = ddl.split("CREATE TABLE ark_ai_chat_messages", 1)[1]
    message_table_ddl = message_table_ddl.split(";", 1)[0]
    content_line = next(line for line in message_table_ddl.splitlines() if "content TEXT" in line)

    assert "DEFAULT" not in content_line.upper()


def test_mysql_ddl_contains_named_reference_and_enum_constraints():
    ddl = _render_mysql_upgrade_ddl()

    for constraint_name in (
        "uq_ai_chat_message_session_id",
        "fk_ai_chat_message_retry_session",
        "fk_ai_chat_message_reply_session",
        "fk_ai_chat_attachment_message_session",
        "ck_ai_chat_message_role",
        "ck_ai_chat_message_status",
        "ck_ai_chat_attachment_type",
        "ck_ai_chat_attachment_status",
    ):
        assert f"CONSTRAINT {constraint_name}" in ddl


def test_ai_chat_permissions_are_seeded_idempotently_with_stable_metadata(db):
    db.add(ArkRole(name="admin", label="系统管理员", is_system=True))
    db.commit()

    seed_role_permissions(db)
    seed_role_permissions(db)

    expected = {
        "ai_chat:read": ("ai_chat", "read", "page", "查看 AI 方案对话"),
        "ai_chat:write": ("ai_chat", "write", "action", "创建会话、上传附件和发送消息"),
        "ai_chat:admin": ("ai_chat", "admin", "action", "管理 AI 方案对话配置与异常"),
    }
    permissions = db.query(ArkPermission).filter(
        ArkPermission.code.in_(expected)
    ).all()
    assert len(permissions) == 3
    assert {
        permission.code: (permission.module, permission.action, permission.kind, permission.label)
        for permission in permissions
    } == expected
