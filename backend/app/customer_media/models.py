"""客户拍摄素材交付 — SQLAlchemy 模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
OBJECT_KEY = String(768).with_variant(
    mysql.VARCHAR(length=768, charset="ascii", collation="ascii_bin"),
    "mysql",
)


class CustomerMediaBatch(Base):
    __tablename__ = "ark_customer_media_batches"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(Integer, ForeignKey("design_schedule_task.id"), nullable=False, comment="设计任务ID")
    request_id = Column(Integer, ForeignKey("design_schedule_request.id"), nullable=False, comment="预约申请ID")
    customer_id = Column(String(64), nullable=False, comment="customer_info.company_id")
    customer_name_snapshot = Column(String(256), nullable=False, comment="客户名称快照")
    applicant_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="预约发起人方舟用户ID")
    designer_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="上传设计师方舟用户ID")
    status = Column(String(24), nullable=False, default="draft", comment="批次状态")
    revision = Column(Integer, nullable=False, default=1, comment="送审修订号")
    lock_version = Column(Integer, nullable=False, default=1, comment="乐观锁版本")
    review_comment = Column(Text, nullable=True, comment="最近审核意见")
    submitted_at = Column(DateTime, nullable=True, comment="送审时间")
    reviewed_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="最近审核人ID")
    reviewed_at = Column(DateTime, nullable=True, comment="最近审核时间")
    published_at = Column(DateTime, nullable=True, comment="发布时间")
    unpublished_at = Column(DateTime, nullable=True, comment="下架时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

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

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("ark_customer_media_batches.id", ondelete="CASCADE"), nullable=False, comment="素材批次ID")
    file_name = Column(String(255), nullable=False, comment="上传文件名")
    media_type = Column(String(16), nullable=False, comment="媒体类型 image/video")
    content_type = Column(String(128), nullable=False, comment="MIME 类型")
    file_size = Column(BigInteger, nullable=False, comment="文件字节数")
    sha256 = Column(String(64), nullable=False, comment="原件 SHA-256")
    storage_provider = Column(String(16), nullable=False, default="local", comment="存储适配器 local/cos")
    object_key = Column(OBJECT_KEY, nullable=False, comment="私有存储对象键")
    thumbnail_key = Column(String(768), nullable=True, comment="缩略图对象键（预留）")
    width = Column(Integer, nullable=True, comment="图片宽度")
    height = Column(Integer, nullable=True, comment="图片高度")
    duration_seconds = Column(Integer, nullable=True, comment="视频时长秒数")
    sort_order = Column(Integer, nullable=False, default=0, comment="批次内排序")
    uploaded_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="上传人方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        UniqueConstraint("storage_provider", "object_key", name="uq_customer_media_object"),
        Index("idx_customer_media_asset_batch", "batch_id", "deleted_at", "sort_order"),
        Index("idx_customer_media_asset_sha", "batch_id", "sha256"),
        {"comment": "客户交付图片视频原件"},
    )


class CustomerMediaReview(Base):
    __tablename__ = "ark_customer_media_reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("ark_customer_media_batches.id", ondelete="CASCADE"), nullable=False, comment="素材批次ID")
    revision = Column(Integer, nullable=False, comment="送审修订号")
    action = Column(String(24), nullable=False, comment="审计动作")
    remark = Column(Text, nullable=True, comment="审核或操作说明")
    actor_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="操作人方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_customer_media_review_batch", "batch_id", "created_at"),
        {"comment": "客户素材提交审核发布审计"},
    )


class CustomerPortalAccount(Base):
    __tablename__ = "ark_customer_portal_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(String(64), nullable=False, unique=True, comment="customer_info.company_id")
    customer_name_snapshot = Column(String(256), nullable=False, comment="客户名称快照")
    login_email = Column(String(255), nullable=False, unique=True, comment="唯一登录邮箱")
    password_hash = Column(String(128), nullable=False, comment="bcrypt 密码哈希")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")
    session_version = Column(Integer, nullable=False, default=1, comment="会话失效版本")
    last_login_at = Column(DateTime, nullable=True, comment="最近登录时间")
    last_login_ip = Column(String(45), nullable=True, comment="最近登录IP")
    created_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="创建人方舟用户ID")
    updated_by = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="更新人方舟用户ID")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = ({"comment": "客户素材门户单客户单账号"},)


class CustomerPortalSession(Base):
    __tablename__ = "ark_customer_portal_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    account_id = Column(BigInteger, ForeignKey("ark_customer_portal_accounts.id", ondelete="CASCADE"), nullable=False, comment="门户账号ID")
    token_hash = Column(String(64), nullable=False, unique=True, comment="会话令牌 SHA-256")
    session_version = Column(Integer, nullable=False, comment="创建时账号会话版本")
    ip_address = Column(String(45), nullable=True, comment="登录IP")
    user_agent = Column(String(500), nullable=True, comment="浏览器标识")
    expires_at = Column(DateTime, nullable=False, comment="过期时间")
    revoked_at = Column(DateTime, nullable=True, comment="撤销时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="创建时间")

    account = relationship("CustomerPortalAccount", lazy="joined")

    __table_args__ = (
        Index("idx_customer_portal_session_account", "account_id", "expires_at"),
        {"comment": "客户素材门户会话"},
    )


class CustomerMediaDownload(Base):
    __tablename__ = "ark_customer_media_downloads"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    asset_id = Column(BigInteger, ForeignKey("ark_customer_media_assets.id"), nullable=False, comment="下载素材ID")
    account_id = Column(BigInteger, ForeignKey("ark_customer_portal_accounts.id"), nullable=False, comment="门户账号ID")
    ip_address = Column(String(45), nullable=True, comment="下载IP")
    created_at = Column(DateTime, nullable=False, default=datetime.now, comment="下载时间")

    __table_args__ = (
        Index("idx_customer_media_download_account", "account_id", "created_at"),
        Index("idx_customer_media_download_asset", "asset_id", "created_at"),
        {"comment": "客户门户素材下载审计"},
    )
