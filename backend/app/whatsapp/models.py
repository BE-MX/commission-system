"""WhatsApp Connector local projection models."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.core.database import Base
from app.auth import models as _auth_models  # noqa: F401 - register ark_users for FK resolution


class WhatsAppAccount(Base):
    """Bound WhatsApp account visible to Ark."""

    __tablename__ = "ark_whatsapp_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_uid = Column(String(80), nullable=False, unique=True)
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    phone_number = Column(String(50), nullable=True)
    display_name = Column(String(120), nullable=True)
    status = Column(String(30), nullable=False, default="binding")
    connector_status = Column(String(60), nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_wa_account_user_status", "ark_user_id", "status"),
        Index("idx_wa_account_phone", "phone_number"),
    )


class WhatsAppBindSession(Base):
    """QR binding session issued by the external connector."""

    __tablename__ = "ark_whatsapp_bind_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bind_session_uid = Column(String(80), nullable=False, unique=True)
    account_uid = Column(String(80), nullable=True)
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    qr_code_url = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_wa_bind_user_status", "ark_user_id", "status"),
    )


class WhatsAppConversation(Base):
    """Conversation projection pulled from the connector."""

    __tablename__ = "ark_whatsapp_conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_uid = Column(String(120), nullable=False, unique=True)
    account_uid = Column(String(80), nullable=False)
    chat_id = Column(String(160), nullable=False)
    contact_phone = Column(String(80), nullable=True)
    contact_name = Column(String(160), nullable=True)
    is_group = Column(Boolean, nullable=False, default=False)
    last_message_at = Column(DateTime, nullable=True)
    last_message_preview = Column(String(500), nullable=True)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("account_uid", "chat_id", name="uk_wa_conv_account_chat"),
        Index("idx_wa_conv_account_time", "account_uid", "last_message_at"),
    )


class WhatsAppMessage(Base):
    """Message projection pulled from the connector."""

    __tablename__ = "ark_whatsapp_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_uid = Column(String(160), nullable=False, unique=True)
    account_uid = Column(String(80), nullable=False)
    conversation_uid = Column(String(120), nullable=True)
    external_message_id = Column(String(180), nullable=False)
    direction = Column(String(20), nullable=False)
    sender_wa_id = Column(String(180), nullable=True)
    sender_phone = Column(String(80), nullable=True)
    sender_name = Column(String(160), nullable=True)
    content_type = Column(String(40), nullable=False, default="text")
    content_text = Column(Text, nullable=True)
    content_preview = Column(String(500), nullable=True)
    sent_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    raw_payload_hash = Column(String(80), nullable=True)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("account_uid", "external_message_id", name="uk_wa_msg_account_external"),
        Index("idx_wa_msg_account_time", "account_uid", "sent_at"),
        Index("idx_wa_msg_conversation_time", "conversation_uid", "sent_at"),
    )


class WhatsAppAttachment(Base):
    """Attachment metadata; binary files stay in connector/object storage."""

    __tablename__ = "ark_whatsapp_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_uid = Column(String(160), nullable=False)
    file_name = Column(String(255), nullable=True)
    mime_type = Column(String(120), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    storage_url = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_wa_attach_message", "message_uid"),
    )


class WhatsAppPullCursor(Base):
    """Incremental cursor per account/resource."""

    __tablename__ = "ark_whatsapp_pull_cursors"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_uid = Column(String(80), nullable=False)
    resource = Column(String(40), nullable=False)
    cursor_value = Column(String(500), nullable=True)
    last_pulled_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("account_uid", "resource", name="uk_wa_cursor_account_resource"),
    )


class WhatsAppAuditLog(Base):
    """Operational audit for binding, sync and revoke actions."""

    __tablename__ = "ark_whatsapp_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_uid = Column(String(80), nullable=True)
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True)
    action = Column(String(60), nullable=False)
    result = Column(String(30), nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_wa_audit_account_time", "account_uid", "created_at"),
    )
