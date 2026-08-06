"""Design Image Studio persistence models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.ai.models import AiCallLog  # noqa: F401 -- registers FK target for isolated metadata
from app.auth.models import ArkUser  # noqa: F401 -- registers user FK target in isolation
from app.core.database import Base


USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class DesignImageSession(Base):
    __tablename__ = "ark_design_image_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="会话所有者")
    title = Column(String(200), nullable=False, comment="会话标题")
    status = Column(String(16), nullable=False, default="active", comment="会话状态")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("idx_di_session_owner_updated", "owner_user_id", "updated_at"),
        {"comment": "AI 生图会话"},
    )

    messages = relationship("DesignImageMessage", back_populates="session", lazy="noload")
    assets = relationship("DesignImageAsset", back_populates="session", lazy="noload")
    jobs = relationship("DesignImageJob", back_populates="session", lazy="noload")


class DesignImageMessage(Base):
    __tablename__ = "ark_design_image_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("ark_design_image_sessions.id", ondelete="RESTRICT"), nullable=False, comment="所属会话")
    role = Column(String(16), nullable=False, comment="消息角色")
    content = Column(Text, nullable=False, comment="消息正文")
    status = Column(String(16), nullable=False, default="normal", comment="消息状态")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_di_message_session_created", "session_id", "created_at"),
        {"comment": "AI 生图会话消息"},
    )

    session = relationship("DesignImageSession", back_populates="messages", lazy="noload")
    assets = relationship("DesignImageAsset", back_populates="message", lazy="noload")
    request_jobs = relationship(
        "DesignImageJob", foreign_keys="DesignImageJob.request_message_id",
        back_populates="request_message", lazy="noload",
    )
    response_jobs = relationship(
        "DesignImageJob", foreign_keys="DesignImageJob.response_message_id",
        back_populates="response_message", lazy="noload",
    )


class DesignImageAsset(Base):
    __tablename__ = "ark_design_image_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("ark_design_image_sessions.id", ondelete="RESTRICT"), nullable=False, comment="所属会话")
    message_id = Column(BigInteger, ForeignKey("ark_design_image_messages.id", ondelete="RESTRICT"), nullable=True, comment="关联消息")
    asset_type = Column(String(16), nullable=False, comment="资产类型")
    storage_path = Column(String(512), nullable=False, comment="私有根目录下相对路径")
    mime_type = Column(String(64), nullable=False, comment="MIME 类型")
    file_size = Column(BigInteger, nullable=False, comment="文件字节数")
    width = Column(Integer, nullable=False, comment="图片宽度")
    height = Column(Integer, nullable=False, comment="图片高度")
    sha256 = Column(String(64), nullable=False, comment="文件 SHA-256")
    source_asset_id = Column(BigInteger, ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), nullable=True, comment="来源资产")
    status = Column(String(16), nullable=False, default="attached", comment="草稿或已附加状态")
    expires_at = Column(DateTime, nullable=True, comment="草稿过期时间")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="创建人")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        Index("idx_di_asset_session_created", "session_id", "created_at"),
        Index("idx_di_asset_draft", "status", "expires_at"),
        {"comment": "AI 生图私有图片资产"},
    )

    session = relationship("DesignImageSession", back_populates="assets", lazy="noload")
    message = relationship("DesignImageMessage", back_populates="assets", lazy="noload")
    source_asset = relationship(
        "DesignImageAsset", remote_side=[id], back_populates="derived_assets", lazy="noload",
    )
    derived_assets = relationship("DesignImageAsset", back_populates="source_asset", lazy="noload")
    base_jobs = relationship(
        "DesignImageJob", foreign_keys="DesignImageJob.base_asset_id",
        back_populates="base_asset", lazy="noload",
    )
    output_jobs = relationship(
        "DesignImageJob", foreign_keys="DesignImageJob.output_asset_id",
        back_populates="output_asset", lazy="noload",
    )
    job_links = relationship("DesignImageJobAsset", back_populates="asset", lazy="noload")


class DesignImageJob(Base):
    __tablename__ = "ark_design_image_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="任务所有者")
    session_id = Column(BigInteger, ForeignKey("ark_design_image_sessions.id", ondelete="RESTRICT"), nullable=False, comment="所属会话")
    request_message_id = Column(BigInteger, ForeignKey("ark_design_image_messages.id", ondelete="RESTRICT"), nullable=False, comment="请求消息")
    base_asset_id = Column(BigInteger, ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), nullable=True, comment="编辑基准资产")
    mode = Column(String(16), nullable=False, comment="生成或编辑模式")
    status = Column(String(16), nullable=False, default="queued", comment="任务状态")
    prompt_snapshot = Column(Text, nullable=False, comment="实际提示词快照")
    parameters = Column(JSON, nullable=True, comment="图片调用参数快照")
    preset_name = Column(String(64), nullable=False, comment="调用预设名快照")
    model = Column(String(128), nullable=True, comment="模型名快照")
    ai_call_log_id = Column(BigInteger, ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"), nullable=True, comment="共享 AI 调用日志")
    idempotency_key = Column(String(64), nullable=False, comment="用户范围幂等键")
    output_asset_id = Column(BigInteger, ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), nullable=True, comment="输出资产")
    response_message_id = Column(BigInteger, ForeignKey("ark_design_image_messages.id", ondelete="RESTRICT"), nullable=True, comment="响应消息")
    retry_of_job_id = Column(BigInteger, ForeignKey("ark_design_image_jobs.id", ondelete="RESTRICT"), nullable=True, comment="被重试任务")
    claimed_by = Column(String(128), nullable=True, comment="Worker 标识")
    lease_token = Column(String(64), nullable=True, comment="Worker 租约令牌")
    lease_expires_at = Column(DateTime, nullable=True, comment="租约到期时间")
    claim_count = Column(Integer, nullable=False, default=0, comment="任务领取次数")
    provider_attempt_count = Column(Integer, nullable=False, default=0, comment="Provider 请求次数")
    error_code = Column(String(64), nullable=True, comment="失败错误码")
    error_message = Column(Text, nullable=True, comment="可行动失败信息")
    billing_certainty = Column(String(16), nullable=True, comment="计费确定性")
    input_tokens = Column(Integer, nullable=True, comment="输入 token")
    output_tokens = Column(Integer, nullable=True, comment="输出 token")
    total_tokens = Column(Integer, nullable=True, comment="总 token")
    estimated_cost_microusd = Column(BigInteger, nullable=True, comment="估算成本微美元")
    pricing_snapshot = Column(JSON, nullable=True, comment="定价规则快照")
    started_at = Column(DateTime, nullable=True, comment="开始执行时间")
    finished_at = Column(DateTime, nullable=True, comment="执行完成时间")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_di_job_owner_idem"),
        Index("idx_di_job_claim", "status", "lease_expires_at", "created_at"),
        Index("idx_di_job_owner_day", "owner_user_id", "created_at", "status"),
        Index("idx_di_job_session_created", "session_id", "created_at"),
        {"comment": "AI 生图可恢复任务"},
    )

    session = relationship("DesignImageSession", back_populates="jobs", lazy="noload")
    request_message = relationship(
        "DesignImageMessage", foreign_keys=[request_message_id],
        back_populates="request_jobs", lazy="noload",
    )
    base_asset = relationship(
        "DesignImageAsset", foreign_keys=[base_asset_id],
        back_populates="base_jobs", lazy="noload",
    )
    ai_call_log = relationship("AiCallLog", lazy="noload")
    output_asset = relationship(
        "DesignImageAsset", foreign_keys=[output_asset_id],
        back_populates="output_jobs", lazy="noload",
    )
    response_message = relationship(
        "DesignImageMessage", foreign_keys=[response_message_id],
        back_populates="response_jobs", lazy="noload",
    )
    retry_of_job = relationship(
        "DesignImageJob", remote_side=[id], back_populates="retry_jobs", lazy="noload",
    )
    retry_jobs = relationship("DesignImageJob", back_populates="retry_of_job", lazy="noload")
    asset_links = relationship("DesignImageJobAsset", back_populates="job", lazy="noload")


class DesignImageJobAsset(Base):
    __tablename__ = "ark_design_image_job_assets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(BigInteger, ForeignKey("ark_design_image_jobs.id", ondelete="CASCADE"), nullable=False, comment="所属任务")
    asset_id = Column(BigInteger, ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), nullable=False, comment="参考资产")
    role = Column(String(16), nullable=False, default="reference", comment="资产用途")
    position = Column(Integer, nullable=False, comment="发送顺序")

    __table_args__ = (
        UniqueConstraint("job_id", "asset_id", name="uq_di_job_asset"),
        CheckConstraint("position >= 0", name="ck_di_job_asset_position"),
        Index("idx_di_job_asset_position", "job_id", "position"),
        {"comment": "AI 生图任务额外参考资产"},
    )

    job = relationship("DesignImageJob", back_populates="asset_links", lazy="noload")
    asset = relationship("DesignImageAsset", back_populates="job_links", lazy="noload")
