"""客户拍摄素材交付 — SQLAlchemy 模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class CustomerMediaBatch(Base):
    __tablename__ = "ark_customer_media_batches"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("design_schedule_task.id"), nullable=False)
    request_id = Column(Integer, ForeignKey("design_schedule_request.id"), nullable=False)
    customer_id = Column(String(64), nullable=False)
    customer_name_snapshot = Column(String(256), nullable=False)
    applicant_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    designer_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=True)
    status = Column(String(24), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    lock_version = Column(Integer, nullable=False, default=1)
    review_comment = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("ark_users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    unpublished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    assets = relationship("CustomerMediaAsset", lazy="selectin", order_by="CustomerMediaAsset.sort_order")
    reviews = relationship("CustomerMediaReview", lazy="selectin", order_by="CustomerMediaReview.created_at")

    __table_args__ = (
        UniqueConstraint("task_id", name="uq_customer_media_batch_task"),
        Index("idx_customer_media_batch_customer", "customer_id", "status", "published_at"),
        Index("idx_customer_media_batch_applicant", "applicant_user_id", "status", "submitted_at"),
        {"comment": "客户拍摄素材交付批次"},
    )


class CustomerMediaAsset(Base):
    __tablename__ = "ark_customer_media_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_id = Column(BigInteger, ForeignKey("ark_customer_media_batches.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(String(255), nullable=False)
    media_type = Column(String(16), nullable=False)
    content_type = Column(String(128), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_provider = Column(String(16), nullable=False, default="local")
    object_key = Column(String(768), nullable=False)
    thumbnail_key = Column(String(768), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    uploaded_by = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    deleted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("storage_provider", "object_key", name="uq_customer_media_object"),
        Index("idx_customer_media_asset_batch", "batch_id", "deleted_at", "sort_order"),
        Index("idx_customer_media_asset_sha", "batch_id", "sha256"),
        {"comment": "客户交付图片视频原件"},
    )


class CustomerMediaReview(Base):
    __tablename__ = "ark_customer_media_reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_id = Column(BigInteger, ForeignKey("ark_customer_media_batches.id", ondelete="CASCADE"), nullable=False)
    revision = Column(Integer, nullable=False)
    action = Column(String(24), nullable=False)
    comment = Column(Text, nullable=True)
    actor_user_id = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        Index("idx_customer_media_review_batch", "batch_id", "created_at"),
        {"comment": "客户素材提交审核发布审计"},
    )


class CustomerPortalAccount(Base):
    __tablename__ = "ark_customer_portal_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, unique=True)
    customer_name_snapshot = Column(String(256), nullable=False)
    login_email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(128), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    session_version = Column(Integer, nullable=False, default=1)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    created_by = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    updated_by = Column(Integer, ForeignKey("ark_users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = ({"comment": "客户素材门户单客户单账号"},)


class CustomerPortalSession(Base):
    __tablename__ = "ark_customer_portal_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(BigInteger, ForeignKey("ark_customer_portal_accounts.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    session_version = Column(Integer, nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    account = relationship("CustomerPortalAccount", lazy="joined")

    __table_args__ = (
        Index("idx_customer_portal_session_account", "account_id", "expires_at"),
        {"comment": "客户素材门户会话"},
    )


class CustomerMediaDownload(Base):
    __tablename__ = "ark_customer_media_downloads"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    asset_id = Column(BigInteger, ForeignKey("ark_customer_media_assets.id"), nullable=False)
    account_id = Column(BigInteger, ForeignKey("ark_customer_portal_accounts.id"), nullable=False)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        Index("idx_customer_media_download_account", "account_id", "created_at"),
        Index("idx_customer_media_download_asset", "asset_id", "created_at"),
        {"comment": "客户门户素材下载审计"},
    )

