"""AI 接入模块 — SQLAlchemy 数据模型"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import beijing_now

USER_ID_TYPE = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


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
    runtime_config = Column(JSON, nullable=True, comment="AI transport and protocol options")
    is_enabled = Column(Boolean, nullable=False, default=True, comment="0=禁用 1=启用")
    timeout_sec = Column(
        SmallInteger, nullable=False, default=60, comment="请求超时秒数"
    )
    remark = Column(String(256), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now,
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


class AiBalanceCheckpoint(Base):
    __tablename__ = "ark_ai_balance_checkpoints"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    provider_id = Column(
        Integer,
        ForeignKey("ark_ai_providers.id"),
        nullable=False,
        comment="关联提供商 ID",
    )
    checkpoint_kind = Column(
        Enum("reconcile", "topup", name="ai_balance_checkpoint_kind"),
        nullable=False,
        default="reconcile",
        comment="流水类型：reconcile=余额核对 topup=充值入账",
    )
    balance_amount = Column(
        Numeric(14, 4),
        nullable=False,
        comment="本次登记余额（原币种，见 balance_currency）",
    )
    balance_currency = Column(
        String(3),
        nullable=False,
        default="CNY",
        comment="余额币种：CNY / USD",
    )
    recorded_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        comment="余额生效截点北京时间（精确到秒）",
    )
    estimated_before_amount = Column(
        Numeric(14, 4),
        nullable=True,
        comment="登记瞬间系统原估算余额快照（原币种，首次登记为空）",
    )
    remark = Column(String(256), nullable=True, comment="核对或充值备注")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建北京时间")
    created_by = Column(USER_ID_TYPE, nullable=True, comment="登记人用户 ID（ark_users.id）")

    __table_args__ = (
        Index("idx_ai_bal_cp_provider_recorded", "provider_id", "recorded_at", "id"),
        {"comment": "AI 提供商余额核对与充值流水表"},
    )


class AiProviderBilling(Base):
    __tablename__ = "ark_ai_provider_billings"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    provider_id = Column(
        Integer,
        ForeignKey("ark_ai_providers.id"),
        nullable=False,
        unique=True,
        comment="关联提供商 ID（1:1）",
    )
    service_kind = Column(
        Enum("official", "relay", name="ai_provider_service_kind"),
        nullable=False,
        default="official",
        comment="接入渠道：official=直连官方 relay=中转站",
    )
    plan_name = Column(String(64), nullable=True, comment="套餐名称")
    billing_mode = Column(
        Enum("monthly", "quarterly", "yearly", "pay_as_you_go", name="ai_provider_billing_mode"),
        nullable=False,
        default="pay_as_you_go",
        comment="计费方式：monthly=包月 quarterly=包季 yearly=包年 pay_as_you_go=按量充值",
    )
    is_balance_deducted_by_usage = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否按调用估算自动扣减余额：1=扣减 0=不扣减",
    )
    price_amount = Column(
        Numeric(12, 2),
        nullable=True,
        comment="周期订阅金额（原币种，见 price_currency）",
    )
    price_currency = Column(
        String(3),
        nullable=True,
        default="CNY",
        comment="订阅金额币种：CNY / USD",
    )
    subscribed_at = Column(Date, nullable=True, comment="订阅日期（北京业务日）")
    renew_at = Column(Date, nullable=True, comment="下次续费或到期日期（北京业务日，正交可选）")
    renew_confirmed_at = Column(DateTime, nullable=True, comment="最近一次人工确认续费北京时间")
    console_url = Column(String(512), nullable=True, comment="供应商控制台地址（仅 https）")
    docs_url = Column(String(512), nullable=True, comment="供应商 API 文档地址（仅 https）")
    logo_storage_key = Column(String(255), nullable=True, comment="LOGO 对象存储键（走 core/storage）")
    latest_checkpoint_id = Column(
        BigInteger,
        ForeignKey("ark_ai_balance_checkpoints.id"),
        nullable=True,
        comment="最新余额核对流水 ID",
    )
    low_balance_threshold = Column(
        Numeric(14, 4),
        nullable=True,
        comment="低余额预警线（按最新流水同币种比较）",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新北京时间",
    )
    created_by = Column(USER_ID_TYPE, nullable=True, comment="创建人用户 ID（ark_users.id）")
    updated_by = Column(USER_ID_TYPE, nullable=True, comment="更新人用户 ID（ark_users.id）")

    __table_args__ = (
        {"comment": "AI 提供商订阅与账务配置表"},
    )


class AiModelPrice(Base):
    __tablename__ = "ark_ai_model_prices"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    provider_id = Column(
        Integer,
        ForeignKey("ark_ai_providers.id"),
        nullable=False,
        comment="关联提供商 ID",
    )
    model = Column(String(128), nullable=False, comment="模型名称（与预设 model 一致）")
    pricing_mode = Column(
        Enum("token", "per_call", "image_rate_card", name="ai_model_pricing_mode"),
        nullable=False,
        default="token",
        comment="计价模式：token=每百万token per_call=按次固定 image_rate_card=复用生图rate_card",
    )
    input_per_million = Column(
        Numeric(14, 6),
        nullable=True,
        comment="每百万输入 token 单价（原币种，最多6位小数）",
    )
    output_per_million = Column(
        Numeric(14, 6),
        nullable=True,
        comment="每百万输出 token 单价（原币种，最多6位小数）",
    )
    per_call_amount = Column(
        Numeric(14, 6),
        nullable=True,
        comment="单次调用固定费用（per_call 模式使用，原币种）",
    )
    currency = Column(
        String(3),
        nullable=False,
        default="CNY",
        comment="单价币种：CNY / USD",
    )
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建北京时间")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=beijing_now,
        onupdate=beijing_now,
        comment="更新北京时间",
    )
    created_by = Column(USER_ID_TYPE, nullable=True, comment="创建人用户 ID（ark_users.id）")
    updated_by = Column(USER_ID_TYPE, nullable=True, comment="更新人用户 ID（ark_users.id）")

    __table_args__ = (
        UniqueConstraint("provider_id", "model", name="uq_ai_model_prices_provider_model"),
        {"comment": "AI 模型统一单价表"},
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
    feature_key = Column(
        String(64),
        nullable=True,
        comment="所属功能标识（来自 feature_catalog，存量无法回填时为空）",
    )
    system_prompt = Column(Text, nullable=True, comment="系统提示词")
    parameters = Column(JSON, nullable=True, comment="调用参数覆盖")
    description = Column(String(512), nullable=True, comment="预设用途说明")
    is_enabled = Column(Boolean, nullable=False, default=True, comment="0=禁用 1=启用")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now,
        comment="更新时间",
    )
    deleted_at = Column(DateTime, nullable=True, comment="软删除时间")

    __table_args__ = (
        Index("idx_preset_provider_id", "provider_id"),
        Index("idx_ai_presets_feature_key", "feature_key"),
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
    provider_id = Column(Integer, nullable=True, comment="调用时的提供商 ID 快照")
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
    finished_at = Column(DateTime, nullable=True, comment="调用结束北京时间（成功/失败/超时均写入）")
    cost_status = Column(
        Enum(
            "priced", "unpriced", "no_usage", "failed", "not_billed", "legacy", "test",
            name="ai_call_cost_status",
        ),
        nullable=True,
        comment="费用状态：priced/unpriced/no_usage/failed/not_billed/legacy/test",
    )
    cost_amount = Column(
        Numeric(14, 6),
        nullable=True,
        comment="本次估算费用（仅 priced 时有值，币种见 cost_currency）",
    )
    cost_currency = Column(String(3), nullable=True, comment="费用币种：CNY / USD")
    price_snapshot = Column(JSON, nullable=True, comment="计费时的单价来源、模式与用量快照")
    error_code = Column(String(64), nullable=True, comment="错误码")
    error_message = Column(Text, nullable=True, comment="错误详情")
    prompt_snapshot = Column(Text, nullable=True, comment="发送给模型的完整 messages JSON")
    response_snapshot = Column(Text, nullable=True, comment="模型返回的原始 response JSON")
    usage_detail = Column(JSON, nullable=True, comment="Provider 返回的原始用量明细")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, default=beijing_now, onupdate=beijing_now,
        comment="更新时间",
    )

    __table_args__ = (
        Index("idx_caller_module", "caller_module"),
        Index("idx_preset_id", "preset_id"),
        Index("idx_status", "status"),
        Index("idx_created_at", "created_at"),
        Index("idx_task_id", "task_id"),
        Index("idx_ai_call_logs_provider_finished", "provider_id", "finished_at"),
        Index("idx_ai_call_logs_cost_status_finished", "cost_status", "finished_at"),
        Index("idx_ai_call_logs_status_provider", "status", "provider_id"),
        {"comment": "AI 调用日志表"},
    )
