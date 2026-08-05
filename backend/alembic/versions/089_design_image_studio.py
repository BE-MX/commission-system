"""Add Design Image Studio persistence schema.

Revision ID: 089_design_image_studio
Revises: 088_festival_first_sign
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "089_design_image_studio"
down_revision = "088_festival_first_sign"
branch_labels = None
depends_on = None


USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
TABLES = [
    "ark_design_image_job_assets",
    "ark_design_image_jobs",
    "ark_design_image_assets",
    "ark_design_image_messages",
    "ark_design_image_sessions",
]


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names() and column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def _ensure_index(name: str, table_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return
    if name not in {index["name"] for index in inspector.get_indexes(table_name)}:
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    if not _has_column("ark_ai_call_logs", "usage_detail"):
        op.add_column(
            "ark_ai_call_logs",
            sa.Column("usage_detail", sa.JSON(), nullable=True, comment="Provider 返回的原始用量明细"),
        )

    existing = _table_names()
    if "ark_design_image_sessions" not in existing:
        op.create_table(
            "ark_design_image_sessions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("owner_user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="会话所有者"),
            sa.Column("title", sa.String(200), nullable=False, comment="会话标题"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active", comment="会话状态"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            comment="AI 生图会话",
        )

    if "ark_design_image_messages" not in existing:
        op.create_table(
            "ark_design_image_messages",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_sessions.id", ondelete="RESTRICT"), nullable=False, comment="所属会话"),
            sa.Column("role", sa.String(16), nullable=False, comment="消息角色"),
            sa.Column("content", sa.Text(), nullable=False, comment="消息正文"),
            sa.Column("status", sa.String(16), nullable=False, server_default="normal", comment="消息状态"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            comment="AI 生图会话消息",
        )

    if "ark_design_image_assets" not in existing:
        op.create_table(
            "ark_design_image_assets",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_sessions.id", ondelete="RESTRICT"), nullable=False, comment="所属会话"),
            sa.Column("message_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_messages.id", ondelete="RESTRICT"), comment="关联消息"),
            sa.Column("asset_type", sa.String(16), nullable=False, comment="资产类型"),
            sa.Column("storage_path", sa.String(512), nullable=False, comment="私有根目录下相对路径"),
            sa.Column("mime_type", sa.String(64), nullable=False, comment="MIME 类型"),
            sa.Column("file_size", sa.BigInteger(), nullable=False, comment="文件字节数"),
            sa.Column("width", sa.Integer(), nullable=False, comment="图片宽度"),
            sa.Column("height", sa.Integer(), nullable=False, comment="图片高度"),
            sa.Column("sha256", sa.String(64), nullable=False, comment="文件 SHA-256"),
            sa.Column("source_asset_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), comment="来源资产"),
            sa.Column("status", sa.String(16), nullable=False, server_default="attached", comment="草稿或已附加状态"),
            sa.Column("expires_at", sa.DateTime(), comment="草稿过期时间"),
            sa.Column("created_by", USER_ID, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="创建人"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("deleted_at", sa.DateTime(), comment="软删除时间"),
            comment="AI 生图私有图片资产",
        )

    if "ark_design_image_jobs" not in existing:
        op.create_table(
            "ark_design_image_jobs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("owner_user_id", USER_ID, sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="任务所有者"),
            sa.Column("session_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_sessions.id", ondelete="RESTRICT"), nullable=False, comment="所属会话"),
            sa.Column("request_message_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_messages.id", ondelete="RESTRICT"), nullable=False, comment="请求消息"),
            sa.Column("base_asset_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), comment="编辑基准资产"),
            sa.Column("mode", sa.String(16), nullable=False, comment="生成或编辑模式"),
            sa.Column("status", sa.String(16), nullable=False, server_default="queued", comment="任务状态"),
            sa.Column("prompt_snapshot", sa.Text(), nullable=False, comment="实际提示词快照"),
            sa.Column("parameters", sa.JSON(), comment="图片调用参数快照"),
            sa.Column("preset_name", sa.String(64), nullable=False, comment="调用预设名快照"),
            sa.Column("model", sa.String(128), comment="模型名快照"),
            sa.Column("ai_call_log_id", sa.BigInteger(), sa.ForeignKey("ark_ai_call_logs.id", ondelete="RESTRICT"), comment="共享 AI 调用日志"),
            sa.Column("idempotency_key", sa.String(64), nullable=False, comment="用户范围幂等键"),
            sa.Column("output_asset_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), comment="输出资产"),
            sa.Column("response_message_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_messages.id", ondelete="RESTRICT"), comment="响应消息"),
            sa.Column("retry_of_job_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_jobs.id", ondelete="RESTRICT"), comment="被重试任务"),
            sa.Column("claimed_by", sa.String(128), comment="Worker 标识"),
            sa.Column("lease_token", sa.String(64), comment="Worker 租约令牌"),
            sa.Column("lease_expires_at", sa.DateTime(), comment="租约到期时间"),
            sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0", comment="任务领取次数"),
            sa.Column("provider_attempt_count", sa.Integer(), nullable=False, server_default="0", comment="Provider 请求次数"),
            sa.Column("error_code", sa.String(64), comment="失败错误码"),
            sa.Column("error_message", sa.Text(), comment="可行动失败信息"),
            sa.Column("billing_certainty", sa.String(16), comment="计费确定性"),
            sa.Column("input_tokens", sa.Integer(), comment="输入 token"),
            sa.Column("output_tokens", sa.Integer(), comment="输出 token"),
            sa.Column("total_tokens", sa.Integer(), comment="总 token"),
            sa.Column("estimated_cost_microusd", sa.BigInteger(), comment="估算成本微美元"),
            sa.Column("pricing_snapshot", sa.JSON(), comment="定价规则快照"),
            sa.Column("started_at", sa.DateTime(), comment="开始执行时间"),
            sa.Column("finished_at", sa.DateTime(), comment="执行完成时间"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.UniqueConstraint("owner_user_id", "idempotency_key", name="uq_di_job_owner_idem"),
            comment="AI 生图可恢复任务",
        )

    if "ark_design_image_job_assets" not in existing:
        op.create_table(
            "ark_design_image_job_assets",
            sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
            sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_jobs.id", ondelete="CASCADE"), nullable=False, comment="所属任务"),
            sa.Column("asset_id", sa.BigInteger(), sa.ForeignKey("ark_design_image_assets.id", ondelete="RESTRICT"), nullable=False, comment="参考资产"),
            sa.Column("role", sa.String(16), nullable=False, server_default="reference", comment="资产用途"),
            sa.Column("position", sa.Integer(), nullable=False, comment="发送顺序"),
            sa.UniqueConstraint("job_id", "asset_id", name="uq_di_job_asset"),
            sa.CheckConstraint("position >= 0", name="ck_di_job_asset_position"),
            comment="AI 生图任务额外参考资产",
        )

    _ensure_index("idx_di_session_owner_updated", "ark_design_image_sessions", ["owner_user_id", "updated_at"])
    _ensure_index("idx_di_message_session_created", "ark_design_image_messages", ["session_id", "created_at"])
    _ensure_index("idx_di_asset_session_created", "ark_design_image_assets", ["session_id", "created_at"])
    _ensure_index("idx_di_asset_draft", "ark_design_image_assets", ["status", "expires_at"])
    _ensure_index("idx_di_job_claim", "ark_design_image_jobs", ["status", "lease_expires_at", "created_at"])
    _ensure_index("idx_di_job_owner_day", "ark_design_image_jobs", ["owner_user_id", "created_at", "status"])
    _ensure_index("idx_di_job_session_created", "ark_design_image_jobs", ["session_id", "created_at"])
    _ensure_index("idx_di_job_asset_position", "ark_design_image_job_assets", ["job_id", "position"])


def downgrade() -> None:
    existing = _table_names()
    for table_name in TABLES:
        if table_name in existing:
            op.drop_table(table_name)
    if _has_column("ark_ai_call_logs", "usage_detail"):
        op.drop_column("ark_ai_call_logs", "usage_detail")
