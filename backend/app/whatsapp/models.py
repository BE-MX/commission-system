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

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    account_uid = Column(String(80), nullable=False, unique=True, comment="连接器账号唯一标识")
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="绑定的方舟用户ID")
    phone_number = Column(String(50), nullable=True, comment="WhatsApp 手机号")
    display_name = Column(String(120), nullable=True, comment="WhatsApp 显示名称")
    status = Column(String(30), nullable=False, default="binding", comment="绑定状态 binding/active/revoked")
    connector_status = Column(String(60), nullable=True, comment="连接器侧状态原文")
    last_sync_at = Column(DateTime, nullable=True, comment="最近同步时间")
    last_message_at = Column(DateTime, nullable=True, comment="最近消息时间")
    last_error = Column(Text, nullable=True, comment="最近同步错误信息")
    raw_payload = Column(JSON, nullable=True, comment="连接器原始载荷")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_wa_account_user_status", "ark_user_id", "status"),
        Index("idx_wa_account_phone", "phone_number"),
        {"comment": "WhatsApp 已绑定账号表"},
    )


class WhatsAppBindSession(Base):
    """QR binding session issued by the external connector."""

    __tablename__ = "ark_whatsapp_bind_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    bind_session_uid = Column(String(80), nullable=False, unique=True, comment="绑定会话唯一标识")
    account_uid = Column(String(80), nullable=True, comment="绑定成功后关联的账号标识")
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False, comment="发起绑定的方舟用户ID")
    status = Column(String(30), nullable=False, default="pending", comment="会话状态 pending/scanning/bound/expired/failed")
    qr_code_url = Column(Text, nullable=True, comment="绑定二维码URL")
    expires_at = Column(DateTime, nullable=True, comment="会话过期时间")
    last_payload = Column(JSON, nullable=True, comment="连接器最近回调载荷")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_wa_bind_user_status", "ark_user_id", "status"),
        {"comment": "WhatsApp 扫码绑定会话表"},
    )


class WhatsAppConversation(Base):
    """Conversation projection pulled from the connector."""

    __tablename__ = "ark_whatsapp_conversations"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    conversation_uid = Column(String(120), nullable=False, unique=True, comment="会话唯一标识")
    account_uid = Column(String(80), nullable=False, comment="所属账号标识")
    chat_id = Column(String(160), nullable=False, comment="连接器会话ID")
    contact_phone = Column(String(80), nullable=True, comment="联系人手机号")
    contact_name = Column(String(160), nullable=True, comment="联系人名称")
    is_group = Column(Boolean, nullable=False, default=False, comment="是否群聊")
    last_message_at = Column(DateTime, nullable=True, comment="最近消息时间")
    last_message_preview = Column(String(500), nullable=True, comment="最近消息预览")
    raw_payload = Column(JSON, nullable=True, comment="连接器原始载荷")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        UniqueConstraint("account_uid", "chat_id", name="uk_wa_conv_account_chat"),
        Index("idx_wa_conv_account_time", "account_uid", "last_message_at"),
        {"comment": "WhatsApp 会话投影表"},
    )


class WhatsAppMessage(Base):
    """Message projection pulled from the connector."""

    __tablename__ = "ark_whatsapp_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    message_uid = Column(String(160), nullable=False, unique=True, comment="消息唯一标识")
    account_uid = Column(String(80), nullable=False, comment="所属账号标识")
    conversation_uid = Column(String(120), nullable=True, comment="所属会话标识")
    external_message_id = Column(String(180), nullable=False, comment="连接器消息ID")
    direction = Column(String(20), nullable=False, comment="消息方向 in/out")
    sender_wa_id = Column(String(180), nullable=True, comment="发送方 WhatsApp ID")
    sender_phone = Column(String(80), nullable=True, comment="发送方手机号")
    sender_name = Column(String(160), nullable=True, comment="发送方名称")
    content_type = Column(String(40), nullable=False, default="text", comment="内容类型 text/image/video/document")
    content_text = Column(Text, nullable=True, comment="消息文本内容")
    content_preview = Column(String(500), nullable=True, comment="消息内容预览")
    sent_at = Column(DateTime, nullable=True, comment="发送时间")
    received_at = Column(DateTime, nullable=True, comment="接收时间")
    raw_payload_hash = Column(String(80), nullable=True, comment="原始载荷哈希（去重用）")
    raw_payload = Column(JSON, nullable=True, comment="连接器原始载荷")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        UniqueConstraint("account_uid", "external_message_id", name="uk_wa_msg_account_external"),
        Index("idx_wa_msg_account_time", "account_uid", "sent_at"),
        Index("idx_wa_msg_conversation_time", "conversation_uid", "sent_at"),
        {"comment": "WhatsApp 消息投影表"},
    )


class WhatsAppAttachment(Base):
    """Attachment metadata; binary files stay in connector/object storage."""

    __tablename__ = "ark_whatsapp_attachments"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    message_uid = Column(String(160), nullable=False, comment="所属消息唯一标识")
    file_name = Column(String(255), nullable=True, comment="附件文件名")
    mime_type = Column(String(120), nullable=True, comment="MIME 类型")
    file_size = Column(BigInteger, nullable=True, comment="文件大小（字节）")
    storage_url = Column(Text, nullable=True, comment="存储地址URL")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("idx_wa_attach_message", "message_uid"),
        {"comment": "WhatsApp 附件元数据表"},
    )


class WhatsAppPullCursor(Base):
    """Incremental cursor per account/resource/scope."""

    __tablename__ = "ark_whatsapp_pull_cursors"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    account_uid = Column(String(80), nullable=False, comment="所属账号标识")
    resource = Column(String(40), nullable=False, comment="拉取资源类型（conversations/messages）")
    scope_uid = Column(String(160), nullable=False, default="global", comment="游标作用域（默认 global）")
    cursor_value = Column(String(500), nullable=True, comment="增量游标值")
    last_pulled_at = Column(DateTime, nullable=True, comment="最近拉取时间")
    last_error = Column(Text, nullable=True, comment="最近拉取错误信息")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        UniqueConstraint("account_uid", "resource", "scope_uid", name="uk_wa_cursor_account_resource_scope"),
        {"comment": "WhatsApp 增量拉取游标表"},
    )


class WhatsAppAuditLog(Base):
    """Operational audit for binding, sync and revoke actions."""

    __tablename__ = "ark_whatsapp_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    account_uid = Column(String(80), nullable=True, comment="相关账号标识")
    ark_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True, comment="操作用户ID")
    action = Column(String(60), nullable=False, comment="操作动作（绑定/同步/解绑等）")
    result = Column(String(30), nullable=False, comment="操作结果")
    detail = Column(Text, nullable=True, comment="操作详情")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="操作时间")

    __table_args__ = (
        Index("idx_wa_audit_account_time", "account_uid", "created_at"),
        {"comment": "WhatsApp 操作审计日志表"},
    )
