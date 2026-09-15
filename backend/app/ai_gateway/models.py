"""Persistent site identity and admission ledger (no message content)."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import INTEGER

from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(INTEGER(unsigned=True), "mysql")


class GatewayApp(Base):
    __tablename__ = "ark_ai_gateway_apps"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(100), nullable=False, comment="站点应用名称")
    owner_user_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="归属负责人ID")
    site_url = Column(String(512), nullable=False, default="", comment="站点地址备注")
    description = Column(String(1000), nullable=False, default="", comment="应用用途说明")
    key_hash = Column(String(64), nullable=False, unique=True, comment="站点密钥SHA256哈希")
    key_hint = Column(String(32), nullable=False, comment="密钥掩码")
    is_enabled = Column(Boolean, nullable=False, default=True, comment="是否允许新的请求")
    daily_limit = Column(Integer, nullable=False, default=100, comment="北京时间每日准入上限")
    rpm_limit = Column(Integer, nullable=False, default=10, comment="固定分钟准入上限")
    concurrency_limit = Column(Integer, nullable=False, default=2, comment="最大未确认结束请求数")
    max_output_tokens = Column(Integer, nullable=False, default=2048, comment="单次最大输出token")
    created_by = Column(USER_ID, nullable=False, comment="创建人ID")
    updated_by = Column(USER_ID, nullable=False, comment="最近管理操作人ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="北京时间创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="北京时间更新时间")
    key_rotated_at = Column(DateTime, nullable=False, default=beijing_now, comment="北京时间密钥重置时间")


class GatewayAppPreset(Base):
    __tablename__ = "ark_ai_gateway_app_presets"

    app_id = Column(BigInteger, ForeignKey("ark_ai_gateway_apps.id"), primary_key=True, comment="站点应用ID")
    preset_id = Column(Integer, ForeignKey("ark_ai_presets.id"), primary_key=True, comment="调用预设ID")


class GatewayRequest(Base):
    __tablename__ = "ark_ai_gateway_requests"
    __table_args__ = (
        UniqueConstraint("app_id", "request_id", name="uq_ai_gateway_request"),
        Index("idx_ai_gateway_app_created", "app_id", "created_at"),
        Index("idx_ai_gateway_app_status", "app_id", "status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    app_id = Column(BigInteger, ForeignKey("ark_ai_gateway_apps.id"), nullable=False, comment="站点应用ID")
    request_id = Column(String(36), nullable=False, comment="调用方UUID请求标识")
    owner_user_id = Column(USER_ID, nullable=False, comment="归属负责人ID")
    preset_id = Column(Integer, nullable=False, comment="调用预设ID")
    preset_name = Column(String(64), nullable=False, comment="调用预设名称快照")
    model = Column(String(128), nullable=False, comment="模型名称快照")
    status = Column(String(16), nullable=False, default="pending", comment="pending/success/error/timeout/unknown")
    ai_log_id = Column(BigInteger, ForeignKey("ark_ai_call_logs.id"), nullable=True, comment="关联AI调用日志ID")
    tokens_prompt = Column(Integer, nullable=True, comment="已知输入token数，未知为空")
    tokens_completion = Column(Integer, nullable=True, comment="已知输出token数，未知为空")
    tokens_used = Column(Integer, nullable=True, comment="已知总token数，未知为空")
    usage_status = Column(String(16), nullable=False, default="unknown", comment="known/partial/unknown")
    duration_ms = Column(Integer, nullable=True, comment="调用耗时毫秒")
    error_code = Column(String(64), nullable=True, comment="脱敏错误分类")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="北京时间创建时间")
    finished_at = Column(DateTime, nullable=True, comment="北京时间本地调用结束时间")
    resolved_by = Column(USER_ID, nullable=True, comment="解除占用操作人ID")
    resolved_at = Column(DateTime, nullable=True, comment="北京时间解除占用时间")
    resolution_reason = Column(Text, nullable=True, comment="执行结束及上游核查结论")
