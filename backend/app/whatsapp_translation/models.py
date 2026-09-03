"""Persistence models for the isolated WhatsApp translation extension domain."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.auth.models import ArkUser  # noqa: F401 -- registers isolated FK target
from app.core.database import Base
from app.core.time import beijing_now


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
PAIRING_STATUSES = ("pending", "approved", "consumed", "expired", "rejected")
NON_NEGATIVE_COLUMNS = (
    "request_count",
    "input_chars",
    "success_count",
    "failure_count",
    "input_tokens",
    "output_tokens",
    "duration_ms_total",
)


class TranslationPairing(Base):
    __tablename__ = "ark_whatsapp_translation_pairings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_code_hash = Column(mysql.CHAR(64), nullable=False, comment="设备码 SHA-256")
    proposed_token_hash = Column(mysql.CHAR(64), nullable=False, comment="本地设备 token SHA-256")
    device_name = Column(String(100), nullable=False, comment="员工可识别设备名")
    browser_name = Column(String(50), nullable=False, comment="浏览器名称")
    browser_version = Column(String(32), nullable=False, comment="浏览器版本")
    extension_version = Column(String(32), nullable=False, comment="扩展版本")
    status = Column(String(16), nullable=False, default="pending", comment="配对状态")
    user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="批准人",
    )
    device_id = Column(
        BigInteger,
        ForeignKey("ark_whatsapp_translation_devices.id", ondelete="CASCADE"),
        nullable=True,
        comment="消费后创建的设备",
    )
    expires_at = Column(DateTime, nullable=False, comment="过期时间")
    approved_at = Column(DateTime, nullable=True, comment="批准时间")
    consumed_at = Column(DateTime, nullable=True, comment="消费时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("device_code_hash", name="uq_wat_pairing_device_code_hash"),
        UniqueConstraint("device_id", name="uq_wat_pairing_device"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'consumed', 'expired', 'rejected')",
            name="ck_wat_pairing_status",
        ),
        Index("idx_wat_pairing_status_expiry", "status", "expires_at"),
        {"comment": "WhatsApp 翻译扩展配对"},
    )

    user = relationship("ArkUser", lazy="noload")
    device = relationship("TranslationDevice", lazy="noload")


class TranslationDevice(Base):
    __tablename__ = "ark_whatsapp_translation_devices"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="方舟员工",
    )
    token_hash = Column(mysql.CHAR(64), nullable=False, comment="设备 token SHA-256")
    device_name = Column(String(100), nullable=False, comment="设备名称")
    browser_name = Column(String(50), nullable=False, comment="浏览器名称")
    browser_version = Column(String(32), nullable=False, comment="浏览器版本")
    extension_version = Column(String(32), nullable=False, comment="扩展版本")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否有效")
    expires_at = Column(DateTime, nullable=False, comment="过期时间")
    last_used_at = Column(DateTime, nullable=True, comment="最近使用时间")
    revoked_at = Column(DateTime, nullable=True, comment="撤销时间")
    revoked_by = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="撤销人",
    )
    revoke_reason = Column(String(255), nullable=True, comment="撤销原因")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_wat_device_token_hash"),
        Index("idx_wat_device_user_active", "user_id", "is_active"),
        Index("idx_wat_device_expiry", "expires_at"),
        {"comment": "WhatsApp 翻译扩展设备"},
    )

    user = relationship("ArkUser", lazy="noload")


class TranslationUsageDaily(Base):
    __tablename__ = "ark_whatsapp_translation_usage_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    usage_date = Column(Date, nullable=False, comment="北京时区自然日")
    user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="方舟员工",
    )
    device_id = Column(
        BigInteger,
        ForeignKey("ark_whatsapp_translation_devices.id", ondelete="CASCADE"),
        nullable=False,
        comment="设备",
    )
    request_count = Column(Integer, nullable=False, default=0, comment="请求数")
    input_chars = Column(Integer, nullable=False, default=0, comment="输入字符数")
    success_count = Column(Integer, nullable=False, default=0, comment="成功数")
    failure_count = Column(Integer, nullable=False, default=0, comment="失败数")
    input_tokens = Column(Integer, nullable=False, default=0, comment="输入 token")
    output_tokens = Column(Integer, nullable=False, default=0, comment="输出 token")
    duration_ms_total = Column(Integer, nullable=False, default=0, comment="总耗时")
    duration_buckets = Column(JSON, nullable=False, default=dict, comment="延迟分桶")
    direction_counts = Column(JSON, nullable=False, default=dict, comment="方向计数")
    language_pair_counts = Column(JSON, nullable=False, default=dict, comment="语言对计数")
    error_counts = Column(JSON, nullable=False, default=dict, comment="标准错误码计数")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint(
            "usage_date",
            "user_id",
            "device_id",
            name="uq_wat_usage_day_user_device",
        ),
        CheckConstraint(
            " AND ".join(f"{column} >= 0" for column in NON_NEGATIVE_COLUMNS),
            name="ck_wat_usage_non_negative",
        ),
        Index("idx_wat_usage_date_user", "usage_date", "user_id"),
        {"comment": "WhatsApp 翻译扩展日用量"},
    )

    user = relationship("ArkUser", lazy="noload")
    device = relationship("TranslationDevice", lazy="noload")
