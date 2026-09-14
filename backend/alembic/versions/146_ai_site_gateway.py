"""Site AI credentials, capability grants and durable request admission."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "146_ai_site_gateway"
down_revision = "145_domestic_order_guest"
branch_labels = None
depends_on = None


def upgrade():
    uid = mysql.INTEGER(unsigned=True)
    op.create_table("ark_ai_gateway_apps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("name", sa.String(100), nullable=False, comment="站点应用名称"),
        sa.Column("owner_user_id", uid, sa.ForeignKey("ark_users.id"), nullable=False, comment="归属负责人ID"),
        sa.Column("site_url", sa.String(512), nullable=False, comment="站点地址备注"),
        sa.Column("description", sa.String(1000), nullable=False, comment="应用用途说明"),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True, comment="站点密钥SHA256哈希"),
        sa.Column("key_hint", sa.String(32), nullable=False, comment="密钥掩码"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, comment="是否允许新的请求"),
        sa.Column("daily_limit", sa.Integer(), nullable=False, comment="北京时间每日准入上限"),
        sa.Column("rpm_limit", sa.Integer(), nullable=False, comment="固定分钟准入上限"),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, comment="最大未确认结束请求数"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, comment="单次最大输出token"),
        sa.Column("created_by", uid, nullable=False, comment="创建人ID"),
        sa.Column("updated_by", uid, nullable=False, comment="最近管理操作人ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="北京时间创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="北京时间更新时间"),
        sa.Column("key_rotated_at", sa.DateTime(), nullable=False, comment="北京时间密钥重置时间"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_table("ark_ai_gateway_app_presets",
        sa.Column("app_id", sa.BigInteger(), sa.ForeignKey("ark_ai_gateway_apps.id"), primary_key=True, comment="站点应用ID"),
        sa.Column("preset_id", sa.Integer(), sa.ForeignKey("ark_ai_presets.id"), primary_key=True, comment="调用预设ID"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_table("ark_ai_gateway_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("app_id", sa.BigInteger(), sa.ForeignKey("ark_ai_gateway_apps.id"), nullable=False, comment="站点应用ID"),
        sa.Column("request_id", sa.String(36), nullable=False, comment="调用方UUID请求标识"),
        sa.Column("owner_user_id", uid, nullable=False, comment="归属负责人ID"),
        sa.Column("preset_id", sa.Integer(), nullable=False, comment="调用预设ID"),
        sa.Column("preset_name", sa.String(64), nullable=False, comment="调用预设名称快照"),
        sa.Column("model", sa.String(128), nullable=False, comment="模型名称快照"),
        sa.Column("status", sa.String(16), nullable=False, comment="pending/success/error/timeout/unknown"),
        sa.Column("ai_log_id", sa.BigInteger(), sa.ForeignKey("ark_ai_call_logs.id"), comment="关联AI调用日志ID"),
        sa.Column("tokens_prompt", sa.Integer(), comment="已知输入token数，未知为空"),
        sa.Column("tokens_completion", sa.Integer(), comment="已知输出token数，未知为空"),
        sa.Column("tokens_used", sa.Integer(), comment="已知总token数，未知为空"),
        sa.Column("usage_status", sa.String(16), nullable=False, comment="known/partial/unknown"),
        sa.Column("duration_ms", sa.Integer(), comment="调用耗时毫秒"),
        sa.Column("error_code", sa.String(64), comment="脱敏错误分类"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="北京时间创建时间"),
        sa.Column("finished_at", sa.DateTime(), comment="北京时间本地调用结束时间"),
        sa.Column("resolved_by", uid, comment="解除占用操作人ID"),
        sa.Column("resolved_at", sa.DateTime(), comment="北京时间解除占用时间"),
        sa.Column("resolution_reason", sa.Text(), comment="执行结束及上游核查结论"),
        sa.UniqueConstraint("app_id", "request_id", name="uq_ai_gateway_request"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("idx_ai_gateway_app_created", "ark_ai_gateway_requests", ["app_id", "created_at"])
    op.create_index("idx_ai_gateway_app_status", "ark_ai_gateway_requests", ["app_id", "status"])


def downgrade():
    # Explicit destructive downgrade only; never used by application rollback.
    op.drop_table("ark_ai_gateway_requests")
    op.drop_table("ark_ai_gateway_app_presets")
    op.drop_table("ark_ai_gateway_apps")
