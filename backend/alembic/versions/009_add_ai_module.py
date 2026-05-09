"""add ai module tables: providers, presets, call_logs

Revision ID: 009_add_ai_module
Revises: 008_add_props_designer
Create Date: 2026-05-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009_add_ai_module"
down_revision: Union[str, None] = "008_add_props_designer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 提供商表
    op.create_table(
        "ark_ai_providers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("name", sa.String(64), nullable=False, unique=True, comment="提供商显示名称"),
        sa.Column(
            "provider_type",
            sa.Enum("direct", "accio_work", name="ai_provider_type"),
            nullable=False,
            default="direct",
            comment="接入类型",
        ),
        sa.Column("api_base", sa.String(512), nullable=False, comment="基础 URL"),
        sa.Column("api_key", sa.Text, nullable=True, comment="加密存储的 API Key"),
        sa.Column("extra_headers", sa.JSON, nullable=True, comment="附加请求头"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, default=True, comment="0=禁用 1=启用"),
        sa.Column("timeout_sec", sa.SmallInteger, nullable=False, default=60, comment="请求超时秒数"),
        sa.Column("remark", sa.String(256), nullable=True, comment="备注"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime, nullable=True, comment="软删除时间"),
        sa.Index("idx_provider_type", "provider_type"),
        sa.Index("idx_is_enabled", "is_enabled"),
        comment="AI 提供商配置表",
    )

    # 预设表
    op.create_table(
        "ark_ai_presets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("preset_name", sa.String(64), nullable=False, unique=True, comment="预设名称"),
        sa.Column(
            "provider_id",
            sa.Integer,
            sa.ForeignKey("ark_ai_providers.id"),
            nullable=False,
            comment="关联 Provider",
        ),
        sa.Column("model", sa.String(128), nullable=False, comment="模型名称"),
        sa.Column("system_prompt", sa.Text, nullable=True, comment="系统提示词"),
        sa.Column("parameters", sa.JSON, nullable=True, comment="调用参数覆盖"),
        sa.Column("description", sa.String(512), nullable=True, comment="预设用途说明"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, default=True, comment="0=禁用 1=启用"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime, nullable=True, comment="软删除时间"),
        sa.Index("idx_preset_provider_id", "provider_id"),
        comment="AI 调用预设表",
    )

    # 调用日志表
    op.create_table(
        "ark_ai_call_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_id", sa.String(64), nullable=True, comment="ACCIO WORK 异步任务 ID"),
        sa.Column("caller_module", sa.String(64), nullable=False, comment="调用来源模块标识"),
        sa.Column("caller_user_id", sa.Integer, nullable=True, comment="触发调用的用户 ID"),
        sa.Column("preset_id", sa.Integer, nullable=True, comment="关联 Preset ID"),
        sa.Column("preset_name", sa.String(64), nullable=False, comment="调用时的预设名称快照"),
        sa.Column(
            "provider_type",
            sa.Enum("direct", "accio_work", name="ai_log_provider_type"),
            nullable=False,
            comment="调用时的提供商类型快照",
        ),
        sa.Column("model", sa.String(128), nullable=True, comment="实际调用的模型名称快照"),
        sa.Column("tokens_prompt", sa.Integer, nullable=True, comment="输入 token 数"),
        sa.Column("tokens_completion", sa.Integer, nullable=True, comment="输出 token 数"),
        sa.Column("tokens_used", sa.Integer, nullable=True, comment="总 token 数"),
        sa.Column("duration_ms", sa.Integer, nullable=True, comment="调用耗时（毫秒）"),
        sa.Column(
            "status",
            sa.Enum("pending", "success", "error", "timeout", name="ai_call_status"),
            nullable=False,
            default="pending",
            comment="调用状态",
        ),
        sa.Column("error_code", sa.String(64), nullable=True, comment="错误码"),
        sa.Column("error_message", sa.Text, nullable=True, comment="错误详情"),
        sa.Column("prompt_snapshot", sa.Text, nullable=True, comment="完整 messages JSON"),
        sa.Column("response_snapshot", sa.Text, nullable=True, comment="模型返回的原始 response JSON"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            server_onupdate=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("idx_caller_module", "caller_module"),
        sa.Index("idx_preset_id", "preset_id"),
        sa.Index("idx_status", "status"),
        sa.Index("idx_created_at", "created_at"),
        sa.Index("idx_task_id", "task_id"),
        comment="AI 调用日志表",
    )


def downgrade() -> None:
    op.drop_table("ark_ai_call_logs")
    op.drop_table("ark_ai_presets")
    op.drop_table("ark_ai_providers")
