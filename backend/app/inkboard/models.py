"""Persistent device credentials, personal notes, messages and receipts."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

ID = BigInteger().with_variant(Integer, "sqlite")
USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class InkDevice(Base):
    __tablename__ = "ark_ink_devices"
    id = Column(ID, primary_key=True, autoincrement=True, comment="设备ID")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, index=True, comment="个人设备所有者")
    name = Column(String(80), nullable=False, comment="设备名称")
    token_hash = Column(String(64), nullable=False, unique=True, comment="SHA256，原始凭证仅签发一次")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    last_received_at = Column(DateTime, comment="最近成功落盘回执时间")
    revoked_at = Column(DateTime, comment="撤销时间")


class InkNote(Base):
    __tablename__ = "ark_ink_notes"
    id = Column(ID, primary_key=True, autoincrement=True, comment="备忘ID")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, index=True, comment="所有者")
    title = Column(String(120), nullable=False, comment="标题")
    body = Column(Text, nullable=False, comment="纯文本内容")
    version = Column(Integer, nullable=False, default=1, comment="乐观锁版本")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, comment="更新时间")
    deleted_at = Column(DateTime, comment="软删除时间")


class InkMessage(Base):
    __tablename__ = "ark_ink_messages"
    __table_args__ = (
        UniqueConstraint("owner_id", "request_key", name="uq_ink_message_request"),
        Index("ix_ink_message_owner_id", "owner_id", "id"),
    )
    id = Column(ID, primary_key=True, autoincrement=True, comment="消息ID")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="收件人")
    request_key = Column(String(80), nullable=False, comment="调用方幂等键")
    title = Column(String(120), nullable=False, comment="标题")
    body = Column(Text, nullable=False, comment="纯文本内容")
    priority = Column(String(10), nullable=False, default="normal", comment="normal/high")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    expires_at = Column(DateTime, nullable=False, comment="过期时间")
    withdrawn_at = Column(DateTime, comment="撤回时间")


class InkReceipt(Base):
    __tablename__ = "ark_ink_receipts"
    device_id = Column(ID, ForeignKey("ark_ink_devices.id"), primary_key=True, comment="设备ID")
    message_id = Column(ID, ForeignKey("ark_ink_messages.id"), primary_key=True, comment="消息ID")
    received_at = Column(DateTime, nullable=False, comment="设备确认落盘时间")
    read_at = Column(DateTime, comment="用户明确确认已读时间")
