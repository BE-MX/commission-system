"""Persistence models for private customer-solution AI conversations."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import foreign, relationship, remote

from app.ai.models import AiCallLog  # noqa: F401 -- registers isolated FK target
from app.auth.models import ArkUser  # noqa: F401 -- registers isolated FK target
from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
MESSAGE_ROLES = ("user", "assistant")
MESSAGE_STATUSES = ("completed", "streaming", "stopped", "failed")
ATTACHMENT_TYPES = ("image", "document")
ATTACHMENT_STATUSES = ("draft", "attached", "failed")


def _in_constraint(column_name: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column_name} IN ({allowed})"


class AiChatSession(Base):
    __tablename__ = "ark_ai_chat_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="会话所有者",
    )
    title = Column(String(200), nullable=False, comment="会话标题")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间",
    )

    __table_args__ = (
        Index("idx_ai_chat_session_owner_updated", "owner_user_id", "updated_at"),
        {"comment": "AI 方案对话会话"},
    )

    owner = relationship("ArkUser", lazy="noload")
    messages = relationship("AiChatMessage", back_populates="session", lazy="noload")
    attachments = relationship(
        "AiChatAttachment", back_populates="session", lazy="noload"
    )


class AiChatMessage(Base):
    __tablename__ = "ark_ai_chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        BigInteger,
        ForeignKey("ark_ai_chat_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="所属会话",
    )
    role = Column(String(16), nullable=False, comment="消息角色")
    request_id = Column(String(64), nullable=True, comment="会话内客户端幂等键")
    content = Column(Text, nullable=False, default="", comment="Markdown 消息正文")
    status = Column(
        String(16), nullable=False, default="completed", comment="消息状态"
    )
    error_message = Column(Text, nullable=True, comment="可行动失败信息")
    reply_to_message_id = Column(
        BigInteger,
        nullable=True,
        comment="触发此助手消息的用户消息",
    )
    retry_of_message_id = Column(
        BigInteger,
        nullable=True,
        comment="被重试的消息",
    )
    ai_call_log_id = Column(
        BigInteger,
        ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"),
        nullable=True,
        comment="共享 AI 调用日志",
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "request_id",
            name="uq_ai_chat_message_session_request",
        ),
        UniqueConstraint(
            "session_id",
            "id",
            name="uq_ai_chat_message_session_id",
        ),
        ForeignKeyConstraint(
            ["session_id", "reply_to_message_id"],
            ["ark_ai_chat_messages.session_id", "ark_ai_chat_messages.id"],
            name="fk_ai_chat_message_reply_session",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "retry_of_message_id"],
            ["ark_ai_chat_messages.session_id", "ark_ai_chat_messages.id"],
            name="fk_ai_chat_message_retry_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _in_constraint("role", MESSAGE_ROLES),
            name="ck_ai_chat_message_role",
        ),
        CheckConstraint(
            _in_constraint("status", MESSAGE_STATUSES),
            name="ck_ai_chat_message_status",
        ),
        Index("idx_ai_chat_message_session_created", "session_id", "created_at"),
        Index("idx_ai_chat_message_reply_to", "session_id", "reply_to_message_id"),
        {"comment": "AI 方案对话消息"},
    )

    session = relationship("AiChatSession", back_populates="messages", lazy="noload")
    attachments = relationship(
        "AiChatAttachment",
        primaryjoin=lambda: and_(
            AiChatMessage.session_id == AiChatAttachment.session_id,
            AiChatMessage.id == foreign(AiChatAttachment.message_id),
        ),
        back_populates="message",
        lazy="noload",
    )
    retry_of_message = relationship(
        "AiChatMessage",
        primaryjoin=lambda: and_(
            AiChatMessage.session_id == remote(AiChatMessage.session_id),
            foreign(AiChatMessage.retry_of_message_id) == remote(AiChatMessage.id),
        ),
        foreign_keys=[retry_of_message_id],
        remote_side=[session_id, id],
        lazy="noload",
        overlaps="messages,session",
    )
    reply_to_message = relationship(
        "AiChatMessage",
        primaryjoin=lambda: and_(
            AiChatMessage.session_id == remote(AiChatMessage.session_id),
            foreign(AiChatMessage.reply_to_message_id) == remote(AiChatMessage.id),
        ),
        foreign_keys=[reply_to_message_id],
        remote_side=[session_id, id],
        lazy="noload",
        overlaps="messages,session",
    )
    ai_call_log = relationship("AiCallLog", lazy="noload")


class AiChatAttachment(Base):
    __tablename__ = "ark_ai_chat_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        BigInteger,
        ForeignKey("ark_ai_chat_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="所属会话",
    )
    message_id = Column(
        BigInteger,
        nullable=True,
        comment="发送后绑定的用户消息",
    )
    original_name = Column(String(255), nullable=False, comment="原始文件名")
    mime_type = Column(String(128), nullable=False, comment="MIME 类型")
    file_size = Column(BigInteger, nullable=False, comment="文件字节数")
    storage_path = Column(String(512), nullable=False, comment="私有根目录下相对路径")
    attachment_type = Column(
        String(16), nullable=False, comment="附件类型 image/document"
    )
    extracted_text = Column(Text, nullable=True, comment="文档抽取正文")
    status = Column(String(16), nullable=False, default="draft", comment="附件状态")
    created_by = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="上传人",
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "message_id"],
            ["ark_ai_chat_messages.session_id", "ark_ai_chat_messages.id"],
            name="fk_ai_chat_attachment_message_session",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _in_constraint("attachment_type", ATTACHMENT_TYPES),
            name="ck_ai_chat_attachment_type",
        ),
        CheckConstraint(
            _in_constraint("status", ATTACHMENT_STATUSES),
            name="ck_ai_chat_attachment_status",
        ),
        Index(
            "idx_ai_chat_attachment_session_created", "session_id", "created_at"
        ),
        Index("idx_ai_chat_attachment_draft_status", "status", "created_at"),
        {"comment": "AI 方案对话私有附件"},
    )

    session = relationship(
        "AiChatSession", back_populates="attachments", lazy="noload"
    )
    message = relationship(
        "AiChatMessage",
        primaryjoin=lambda: and_(
            AiChatMessage.session_id == AiChatAttachment.session_id,
            AiChatMessage.id == foreign(AiChatAttachment.message_id),
        ),
        back_populates="attachments",
        lazy="noload",
    )
    creator = relationship("ArkUser", lazy="noload")
