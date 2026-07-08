"""AI 接入模块 — SQLAlchemy 数据模型"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime,
    Enum, Text, JSON, SmallInteger, Boolean,
    ForeignKey, Index,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class AiProvider(Base):
    __tablename__ = "ark_ai_providers"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(64), nullable=False, unique=True, comment="提供商显示名称")
    provider_type = Column(
        Enum("direct", "accio_work", name="ai_provider_type"),
        nullable=False,
        default="direct",
        comment="接入类型",
    )
    api_base = Column(String(512), nullable=False, comment="基础 URL")
    api_key = Column(Text, nullable=True, comment="加密存储的 API Key")
    api_type = Column(
        Enum("openai", "anthropic", name="ai_api_type"),
        nullable=False,
        default="openai",
        comment="API 协议类型: openai=Chat Completions, anthropic=Messages",
    )
    extra_headers = Column(JSON, nullable=True, comment="附加请求头")
    is_enabled = Column(Boolean, nullable=False, default=True, comment="0=禁用 1=启用")
    timeout_sec = Column(
        SmallInteger, nullable=False, default=60, comment="请求超时秒数"
    )
    remark = Column(String(256), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
        comment="更新时间",
    )
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        Index("idx_provider_type", "provider_type"),
        Index("idx_is_enabled", "is_enabled"),
        {"comment": "AI 提供商配置表"},
    )

    presets = relationship(
        "AiPreset",
        back_populates="provider",
        lazy="dynamic",
    )


class AiPreset(Base):
    __tablename__ = "ark_ai_presets"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    preset_name = Column(String(64), nullable=False, unique=True, comment="预设名称，调用方使用")
    provider_id = Column(
        Integer,
        ForeignKey("ark_ai_providers.id"),
        nullable=False,
        comment="关联 Provider",
    )
    model = Column(String(128), nullable=False, comment="模型名称")
    system_prompt = Column(Text, nullable=True, comment="系统提示词")
    parameters = Column(JSON, nullable=True, comment="调用参数覆盖")
    description = Column(String(512), nullable=True, comment="预设用途说明")
    is_enabled = Column(Boolean, nullable=False, default=True, comment="0=禁用 1=启用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
        comment="更新时间",
    )
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        Index("idx_preset_provider_id", "provider_id"),
        {"comment": "AI 调用预设表"},
    )

    provider = relationship("AiProvider", back_populates="presets")


class AiCallLog(Base):
    __tablename__ = "ark_ai_call_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(String(64), nullable=True, comment="ACCIO WORK 异步任务 ID")
    caller_module = Column(String(64), nullable=False, comment="调用来源模块标识")
    caller_user_id = Column(Integer, nullable=True, comment="触发调用的用户 ID")
    preset_id = Column(Integer, nullable=True, comment="关联 Preset ID（预设删除后保留）")
    preset_name = Column(String(64), nullable=False, comment="调用时的预设名称快照")
    provider_type = Column(
        Enum("direct", "accio_work", name="ai_log_provider_type"),
        nullable=False,
        comment="调用时的提供商类型快照",
    )
    model = Column(String(128), nullable=True, comment="实际调用的模型名称快照")
    tokens_prompt = Column(Integer, nullable=True, comment="输入 token 数")
    tokens_completion = Column(Integer, nullable=True, comment="输出 token 数")
    tokens_used = Column(Integer, nullable=True, comment="总 token 数")
    duration_ms = Column(Integer, nullable=True, comment="调用耗时（毫秒）")
    status = Column(
        Enum("pending", "success", "error", "timeout", name="ai_call_status"),
        nullable=False,
        default="pending",
        comment="调用状态",
    )
    error_code = Column(String(64), nullable=True, comment="错误码")
    error_message = Column(Text, nullable=True, comment="错误详情")
    prompt_snapshot = Column(Text, nullable=True, comment="发送给模型的完整 messages JSON")
    response_snapshot = Column(Text, nullable=True, comment="模型返回的原始 response JSON")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
        comment="更新时间",
    )

    __table_args__ = (
        Index("idx_caller_module", "caller_module"),
        Index("idx_preset_id", "preset_id"),
        Index("idx_status", "status"),
        Index("idx_created_at", "created_at"),
        Index("idx_task_id", "task_id"),
        {"comment": "AI 调用日志表"},
    )
