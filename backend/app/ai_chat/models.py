"""Persistence models for private customer-solution AI conversations."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.ai.models import AiCallLog  # noqa: F401 -- registers isolated FK target
from app.auth.models import ArkUser  # noqa: F401 -- registers isolated FK target
from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


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
    retry_of_message_id = Column(
        BigInteger,
        ForeignKey("ark_ai_chat_messages.id", ondelete="RESTRICT"),
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
        Index("idx_ai_chat_message_session_created", "session_id", "created_at"),
        {"comment": "AI 方案对话消息"},
    )

    session = relationship("AiChatSession", back_populates="messages", lazy="noload")
    attachments = relationship(
        "AiChatAttachment", back_populates="message", lazy="noload"
    )
    retry_of_message = relationship(
        "AiChatMessage",
        remote_side=[id],
        back_populates="retry_messages",
        lazy="noload",
    )
    retry_messages = relationship(
        "AiChatMessage", back_populates="retry_of_message", lazy="noload"
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
        ForeignKey("ark_ai_chat_messages.id", ondelete="RESTRICT"),
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
        "AiChatMessage", back_populates="attachments", lazy="noload"
    )
    creator = relationship("ArkUser", lazy="noload")
