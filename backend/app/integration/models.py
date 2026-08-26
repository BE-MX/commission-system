"""Persistence models for authenticated external invoice ingestion."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Column,
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

from app.auth.models import ArkUser  # noqa: F401 -- register ark_users FK target
from app.core.database import Base
from app.core.time import beijing_now
from app.invoice.models import Invoice  # noqa: F401 -- register ark_invoices FK target


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
INTEGRATION_ID = BigInteger().with_variant(Integer(), "sqlite")


class IntegrationApp(Base):
    __tablename__ = "ark_integration_apps"

    id = Column(INTEGRATION_ID, primary_key=True, autoincrement=True, comment="主键")
    public_id = Column(String(32), nullable=False, unique=True, comment="对外应用ID")
    name = Column(String(100), nullable=False, comment="应用名称")
    owner_user_id = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="应用所有人方舟用户ID",
    )
    token_hash = Column(CHAR(64), nullable=False, unique=True, comment="访问令牌SHA-256")
    token_suffix = Column(String(6), nullable=False, comment="令牌末六位展示值")
    scopes = Column(JSON, nullable=False, comment="授权范围列表")
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="是否启用",
    )
    expires_at = Column(DateTime, nullable=True, comment="令牌过期时间（北京时间）")
    last_used_at = Column(DateTime, nullable=True, comment="最后使用时间（北京时间）")
    created_by = Column(
        USER_ID,
        ForeignKey("ark_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建人方舟用户ID",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新时间（北京时间）",
    )

    __table_args__ = (
        Index("idx_integration_app_owner", "owner_user_id"),
        Index("idx_integration_app_active", "is_active", "expires_at"),
        {"comment": "外部系统发票接入应用"},
    )

    ingest_requests = relationship(
        "InvoiceIngestRequest",
        back_populates="integration_app",
        lazy="noload",
        cascade="all, delete-orphan",
    )


class InvoiceIngestRequest(Base):
    __tablename__ = "ark_invoice_ingest_requests"

    id = Column(INTEGRATION_ID, primary_key=True, autoincrement=True, comment="主键")
    public_id = Column(String(32), nullable=False, unique=True, comment="对外请求ID")
    integration_app_id = Column(
        INTEGRATION_ID,
        ForeignKey("ark_integration_apps.id", ondelete="CASCADE"),
        nullable=False,
        comment="接入应用ID",
    )
    external_order_id = Column(String(64), nullable=False, comment="外部系统订单ID")
    request_sha256 = Column(CHAR(64), nullable=False, comment="规范化请求SHA-256")
    invoice_id = Column(
        INTEGRATION_ID,
        ForeignKey("ark_invoices.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建的发票ID",
    )
    status = Column(
        String(16),
        nullable=False,
        default="processing",
        server_default="processing",
        comment="processing/created/rejected",
    )
    error_code = Column(String(64), nullable=True, comment="稳定错误码")
    error_json = Column(JSON, nullable=True, comment="结构化错误详情")
    attempt_count = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="处理尝试次数",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间（北京时间）")
    finished_at = Column(DateTime, nullable=True, comment="完成时间（北京时间）")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新时间（北京时间）",
    )

    __table_args__ = (
        UniqueConstraint(
            "integration_app_id",
            "external_order_id",
            name="uq_invoice_ingest_app_order",
        ),
        CheckConstraint(
            "status IN ('processing', 'created', 'rejected')",
            name="ck_invoice_ingest_status",
        ),
        CheckConstraint(
            "attempt_count > 0",
            name="ck_invoice_ingest_attempt_positive",
        ),
        Index("idx_invoice_ingest_app", "integration_app_id"),
        Index("idx_invoice_ingest_status", "status", "updated_at"),
        Index("idx_invoice_ingest_invoice", "invoice_id"),
        {"comment": "外部系统发票幂等接入请求"},
    )

    integration_app = relationship(
        "IntegrationApp",
        back_populates="ingest_requests",
        lazy="noload",
    )
    invoice = relationship("Invoice", lazy="noload")
