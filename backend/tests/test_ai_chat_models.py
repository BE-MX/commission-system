"""Persistence and schema invariants for the Customer AI Chat domain."""

from datetime import datetime
from importlib import util
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import BigInteger, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.ai_chat.models import AiChatAttachment, AiChatMessage, AiChatSession
from app.ai_chat.schemas import (
    AttachmentResponse,
    MessageResponse,
    SessionCreate,
    SessionResponse,
    TurnStreamRequest,
)
from app.auth.models import ArkPermission, ArkRole
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


def test_ai_chat_tables_and_indexes_match_the_domain_contract():
    assert AiChatSession.__tablename__ == "ark_ai_chat_sessions"
    assert AiChatMessage.__tablename__ == "ark_ai_chat_messages"
    assert AiChatAttachment.__tablename__ == "ark_ai_chat_attachments"

    session_indexes = {index.name for index in AiChatSession.__table__.indexes}
    message_indexes = {index.name for index in AiChatMessage.__table__.indexes}
    attachment_indexes = {index.name for index in AiChatAttachment.__table__.indexes}

    assert "idx_ai_chat_session_owner_updated" in session_indexes
    assert "idx_ai_chat_message_session_created" in message_indexes
    assert {
        "idx_ai_chat_attachment_session_created",
        "idx_ai_chat_attachment_draft_status",
    } <= attachment_indexes


def test_message_idempotency_and_attachment_ownership_constraints():
    message_table = AiChatMessage.__table__
    constraint_names = {
        constraint.name
        for constraint in message_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_ai_chat_message_session_request" in constraint_names
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


def test_foreign_keys_are_restrictive_and_relationships_do_not_implicitly_load():
    expected_targets = {
        "ark_ai_chat_sessions.owner_user_id": "ark_users.id",
        "ark_ai_chat_messages.session_id": "ark_ai_chat_sessions.id",
        "ark_ai_chat_messages.retry_of_message_id": "ark_ai_chat_messages.id",
        "ark_ai_chat_messages.ai_call_log_id": "ark_ai_call_logs.id",
        "ark_ai_chat_attachments.session_id": "ark_ai_chat_sessions.id",
        "ark_ai_chat_attachments.message_id": "ark_ai_chat_messages.id",
        "ark_ai_chat_attachments.created_by": "ark_users.id",
    }

    for qualified_column, target in expected_targets.items():
        table_name, column_name = qualified_column.split(".")
        table = {
            AiChatSession.__tablename__: AiChatSession.__table__,
            AiChatMessage.__tablename__: AiChatMessage.__table__,
            AiChatAttachment.__tablename__: AiChatAttachment.__table__,
        }[table_name]
        foreign_key = next(iter(table.c[column_name].foreign_keys))
        assert foreign_key.target_fullname == target
        assert foreign_key.ondelete == "RESTRICT"

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
    assert MessageResponse.model_validate(message).content == "分析附件"
    attachment_data = AttachmentResponse.model_validate(attachment).model_dump()
    assert attachment_data["original_name"] == "brief.md"
    assert "storage_path" not in attachment_data
    assert "extracted_text" not in attachment_data


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


def test_ai_chat_permissions_are_seeded_idempotently_with_stable_metadata(db):
    db.add(ArkRole(name="admin", label="系统管理员", is_system=True))
    db.commit()

    seed_role_permissions(db)
    seed_role_permissions(db)

    expected = {
        "ai_chat:read": ("ai_chat", "read", "page", "查看 AI 方案对话"),
        "ai_chat:write": (
            "ai_chat",
            "write",
            "action",
            "创建会话、上传附件和发送消息",
        ),
        "ai_chat:admin": (
            "ai_chat",
            "admin",
            "action",
            "管理 AI 方案对话配置与异常",
        ),
    }
    permissions = (
        db.query(ArkPermission)
        .filter(ArkPermission.code.in_(expected))
        .all()
    )
    assert len(permissions) == 3
    assert {
        permission.code: (
            permission.module,
            permission.action,
            permission.kind,
            permission.label,
        )
        for permission in permissions
    } == expected
