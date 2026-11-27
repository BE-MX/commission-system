"""AI subscription billing, balance checkpoints, unified model prices, and preset features.

Revision ID: 285_ai_subscription_billing
Revises: 284_customer_dedup_checks
Create Date: 2026-11-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = "285_ai_subscription_billing"
down_revision: Union[str, None] = "284_customer_dedup_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")

# 静态固化回填快照（不 import 运行时代码，保证迁移历史确定性）
PRESET_FEATURE_SNAPSHOT: dict[str, str] = {
    # 物流管理
    "waybill_ocr": "tracking",
    "tracking_summary": "tracking",
    # 展会营销
    "expo_face_analysis": "expo",
    "expo_wig_composite": "expo",
    "expo_sales_strategy": "expo",
    "expo_scene_generation": "expo",
    "expo_beautify": "expo",
    # 内贸订单
    "domestic_followup_parse": "domestic_followup",
    "domestic_followup_ocr": "domestic_followup",
    "domestic_followup_insights": "domestic_followup",
    "domestic_followup_strategy": "domestic_followup",
    "domestic_followup_audio_organize": "domestic_followup",
    "domestic_decision_brief": "domestic_followup",
    # 客户经营
    "mail_outreach_generate": "mail_outreach",
    "mail_outreach_internal_test": "system_test",
    "client_desk_daily": "client_desk",
    "client_desk_unlinked": "client_desk",
    "pcw_conversation_summary": "client_desk",
    "client_desk_analysis": "client_desk",
    "client_desk_unlinked_daily": "client_desk",
    "client_desk_unlinked_weekly": "client_desk",
    # 订单管理
    "order_intelligence_brief": "invoice",
    "invoice_screenshot_extract": "invoice",
    "fx_settlement_advisor": "invoice",
    "product_sales_grade_insight": "invoice",
    # 售后管理
    "aftersales_solution_advice": "aftersales",
    # 备货管理 / 工厂到货
    "factory_delivery_ocr": "stock",
    "factory_inbound_delivery_note": "stock",
    # 素材管理
    "asset_analyze": "asset",
    # 色彩管理
    "swatch_image_generation": "color",
    # 方舟洞见 / 培训速递
    "insight_daily_organize": "insight",
    "case_library_format": "insight",
    "training_digest_draft": "training",
    # 企业知识库
    "knowledge_ai_edit": "knowledge",
    "knowledge_ai_verify": "knowledge",
    # 设计中心（AI 生图 / 客户生图 / AI 工作台聊天）
    "design_image_generation": "design_image",
    "customer_image_generation": "customer_image",
    "customer_ai_chat": "ai_chat",
    # 个人效率
    "task_draft": "task",
    "task_brief": "task",
    # WhatsApp 助手
    "whatsapp_message_assistant": "whatsapp",
    "whatsapp_assistant_summary": "whatsapp",
    "whatsapp_text_translation": "whatsapp",
    "whatsapp_outgoing_translation": "whatsapp",
    "whatsapp_reply_generator": "whatsapp",
    "whatsapp_reply_query_rewrite": "whatsapp",
    # 平台内置非导航类
    "agent_runtime_copilot": "agent_runtime",
    "agent_runtime_repurchase": "agent_runtime",
    "agent_runtime_sales_shadow": "agent_runtime",
    "pm_diff": "pm_hub",
}


def upgrade() -> None:
    op.create_table(
        "ark_ai_balance_checkpoints",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("ark_ai_providers.id"),
            nullable=False,
            comment="关联提供商 ID",
        ),
        sa.Column(
            "checkpoint_kind",
            sa.Enum("reconcile", "topup", name="ai_balance_checkpoint_kind"),
            nullable=False,
            server_default="reconcile",
            comment="流水类型：reconcile=余额核对 topup=充值入账",
        ),
        sa.Column("balance_amount", sa.Numeric(14, 4), nullable=False, comment="本次登记余额（原币种，见 balance_currency）"),
        sa.Column("balance_currency", sa.String(3), nullable=False, server_default="CNY", comment="余额币种：CNY / USD"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, comment="余额生效截点北京时间（精确到秒）"),
        sa.Column("estimated_before_amount", sa.Numeric(14, 4), nullable=True, comment="登记瞬间系统原估算余额快照（原币种，首次登记为空）"),
        sa.Column("remark", sa.String(256), nullable=True, comment="核对或充值备注"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建北京时间"),
        sa.Column("created_by", USER_ID, nullable=True, comment="登记人用户 ID（ark_users.id）"),
        comment="AI 提供商余额核对与充值流水表",
    )
    op.create_index(
        "idx_ai_bal_cp_provider_recorded",
        "ark_ai_balance_checkpoints",
        ["provider_id", "recorded_at", "id"],
    )

    op.create_table(
        "ark_ai_provider_billings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("ark_ai_providers.id"),
            nullable=False,
            unique=True,
            comment="关联提供商 ID（1:1）",
        ),
        sa.Column(
            "service_kind",
            sa.Enum("official", "relay", name="ai_provider_service_kind"),
            nullable=False,
            server_default="official",
            comment="接入渠道：official=直连官方 relay=中转站",
        ),
        sa.Column("plan_name", sa.String(64), nullable=True, comment="套餐名称"),
        sa.Column(
            "billing_mode",
            sa.Enum("monthly", "quarterly", "yearly", "pay_as_you_go", name="ai_provider_billing_mode"),
            nullable=False,
            server_default="pay_as_you_go",
            comment="计费方式：monthly=包月 quarterly=包季 yearly=包年 pay_as_you_go=按量充值",
        ),
        sa.Column(
            "is_balance_deducted_by_usage",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="是否按调用估算自动扣减余额：1=扣减 0=不扣减",
        ),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=True, comment="周期订阅金额（原币种，见 price_currency）"),
        sa.Column("price_currency", sa.String(3), nullable=True, server_default="CNY", comment="订阅金额币种：CNY / USD"),
        sa.Column("subscribed_at", sa.Date(), nullable=True, comment="订阅日期（北京业务日）"),
        sa.Column("renew_at", sa.Date(), nullable=True, comment="下次续费或到期日期（北京业务日，正交可选）"),
        sa.Column("renew_confirmed_at", sa.DateTime(), nullable=True, comment="最近一次人工确认续费北京时间"),
        sa.Column("console_url", sa.String(512), nullable=True, comment="供应商控制台地址（仅 https）"),
        sa.Column("docs_url", sa.String(512), nullable=True, comment="供应商 API 文档地址（仅 https）"),
        sa.Column("logo_storage_key", sa.String(255), nullable=True, comment="LOGO 对象存储键（走 core/storage）"),
        sa.Column(
            "latest_checkpoint_id",
            sa.BigInteger(),
            sa.ForeignKey("ark_ai_balance_checkpoints.id"),
            nullable=True,
            comment="最新余额核对流水 ID",
        ),
        sa.Column("low_balance_threshold", sa.Numeric(14, 4), nullable=True, comment="低余额预警线（按最新流水同币种比较）"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建北京时间"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
            comment="更新北京时间",
        ),
        sa.Column("created_by", USER_ID, nullable=True, comment="创建人用户 ID（ark_users.id）"),
        sa.Column("updated_by", USER_ID, nullable=True, comment="更新人用户 ID（ark_users.id）"),
        comment="AI 提供商订阅与账务配置表",
    )

    op.create_table(
        "ark_ai_model_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column(
            "provider_id",
            sa.Integer(),
            sa.ForeignKey("ark_ai_providers.id"),
            nullable=False,
            comment="关联提供商 ID",
        ),
        sa.Column("model", sa.String(128), nullable=False, comment="模型名称（与预设 model 一致）"),
        sa.Column(
            "pricing_mode",
            sa.Enum("token", "per_call", "image_rate_card", name="ai_model_pricing_mode"),
            nullable=False,
            server_default="token",
            comment="计价模式：token=每百万token per_call=按次固定 image_rate_card=复用生图rate_card",
        ),
        sa.Column("input_per_million", sa.Numeric(14, 6), nullable=True, comment="每百万输入 token 单价（原币种，最多6位小数）"),
        sa.Column("output_per_million", sa.Numeric(14, 6), nullable=True, comment="每百万输出 token 单价（原币种，最多6位小数）"),
        sa.Column("per_call_amount", sa.Numeric(14, 6), nullable=True, comment="单次调用固定费用（per_call 模式使用，原币种）"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY", comment="单价币种：CNY / USD"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建北京时间"),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
            comment="更新北京时间",
        ),
        sa.Column("created_by", USER_ID, nullable=True, comment="创建人用户 ID（ark_users.id）"),
        sa.Column("updated_by", USER_ID, nullable=True, comment="更新人用户 ID（ark_users.id）"),
        sa.UniqueConstraint("provider_id", "model", name="uq_ai_model_prices_provider_model"),
        comment="AI 模型统一单价表",
    )

    op.add_column(
        "ark_ai_presets",
        sa.Column("feature_key", sa.String(64), nullable=True, comment="所属功能标识（来自 feature_catalog，存量无法回填时为空）"),
    )
    op.create_index("idx_ai_presets_feature_key", "ark_ai_presets", ["feature_key"])

    op.add_column(
        "ark_ai_call_logs",
        sa.Column("provider_id", sa.Integer(), nullable=True, comment="调用时的提供商 ID 快照"),
    )
    op.add_column(
        "ark_ai_call_logs",
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="调用结束北京时间（成功/失败/超时均写入）"),
    )
    op.add_column(
        "ark_ai_call_logs",
        sa.Column(
            "cost_status",
            sa.Enum(
                "priced", "unpriced", "no_usage", "failed", "not_billed", "legacy", "test",
                name="ai_call_cost_status",
            ),
            nullable=True,
            comment="费用状态：priced/unpriced/no_usage/failed/not_billed/legacy/test",
        ),
    )
    op.add_column(
        "ark_ai_call_logs",
        sa.Column("cost_amount", sa.Numeric(14, 6), nullable=True, comment="本次估算费用（仅 priced 时有值，币种见 cost_currency）"),
    )
    op.add_column(
        "ark_ai_call_logs",
        sa.Column("cost_currency", sa.String(3), nullable=True, comment="费用币种：CNY / USD"),
    )
    op.add_column(
        "ark_ai_call_logs",
        sa.Column("price_snapshot", sa.JSON(), nullable=True, comment="计费时的单价来源、模式与用量快照"),
    )
    op.create_index("idx_ai_call_logs_provider_finished", "ark_ai_call_logs", ["provider_id", "finished_at"])
    op.create_index("idx_ai_call_logs_cost_status_finished", "ark_ai_call_logs", ["cost_status", "finished_at"])
    op.create_index("idx_ai_call_logs_status_provider", "ark_ai_call_logs", ["status", "provider_id"])

    # 1) 存量日志全部标记为 legacy，不猜历史费用
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE ark_ai_call_logs SET cost_status = 'legacy' WHERE cost_status IS NULL"))

    # 2) 按静态快照回填存量预设的 feature_key（使用 literal_execute 兼容 alembic --sql 离线输出）
    for preset_name, feature_key in PRESET_FEATURE_SNAPSHOT.items():
        stmt = sa.text(
            "UPDATE ark_ai_presets SET feature_key = :fk "
            "WHERE preset_name = :pn AND feature_key IS NULL"
        ).bindparams(
            sa.bindparam("fk", value=feature_key, literal_execute=True),
            sa.bindparam("pn", value=preset_name, literal_execute=True),
        )
        conn.execute(stmt)
    conn.execute(
        sa.text(
            "UPDATE ark_ai_presets SET feature_key = 'design_image' "
            "WHERE preset_name LIKE 'design_image_generation_%' AND feature_key IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("idx_ai_call_logs_status_provider", table_name="ark_ai_call_logs")
    op.drop_index("idx_ai_call_logs_cost_status_finished", table_name="ark_ai_call_logs")
    op.drop_index("idx_ai_call_logs_provider_finished", table_name="ark_ai_call_logs")
    op.drop_column("ark_ai_call_logs", "price_snapshot")
    op.drop_column("ark_ai_call_logs", "cost_currency")
    op.drop_column("ark_ai_call_logs", "cost_amount")
    op.drop_column("ark_ai_call_logs", "cost_status")
    op.drop_column("ark_ai_call_logs", "finished_at")
    op.drop_column("ark_ai_call_logs", "provider_id")

    op.drop_index("idx_ai_presets_feature_key", table_name="ark_ai_presets")
    op.drop_column("ark_ai_presets", "feature_key")

    op.drop_table("ark_ai_model_prices")
    op.drop_table("ark_ai_provider_billings")
    op.drop_table("ark_ai_balance_checkpoints")
