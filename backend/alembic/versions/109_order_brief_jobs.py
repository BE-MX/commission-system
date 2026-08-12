"""Add asynchronous order intelligence brief jobs.

Revision ID: 109_order_brief_jobs
Revises: 108_invoice_beijing_time
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "109_order_brief_jobs"
down_revision = "108_invoice_beijing_time"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "ark_order_intelligence_brief_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("owner_user_id", USER_ID, nullable=False, comment="提交简报的方舟用户"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued", comment="queued/running/succeeded/failed"),
        sa.Column("active_key", sa.String(length=64), nullable=True, comment="用户级活动任务锁，终态置空"),
        sa.Column("date_from", sa.Date(), nullable=False, comment="分析开始日期"),
        sa.Column("date_to", sa.Date(), nullable=False, comment="分析结束日期"),
        sa.Column("focus", sa.String(length=24), nullable=False, server_default="executive", comment="简报侧重点"),
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, comment="提交时数据权限范围快照"),
        sa.Column("content", sa.Text(), nullable=True, comment="AI 或规则简报内容"),
        sa.Column("source", sa.String(length=16), nullable=True, comment="ai/rules"),
        sa.Column("evidence", sa.JSON(), nullable=True, comment="生成简报的结构化证据"),
        sa.Column("error_message", sa.String(length=1000), nullable=True, comment="可行动失败原因"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="开始生成时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=True, comment="结束时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["ark_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_key", name="uq_oi_brief_active_key"),
        comment="订单经营 AI 简报后台任务",
    )
    op.create_index("idx_oi_brief_owner_created", "ark_order_intelligence_brief_jobs", ["owner_user_id", "created_at"])
    op.create_index("idx_oi_brief_status_updated", "ark_order_intelligence_brief_jobs", ["status", "updated_at"])


def downgrade() -> None:
    op.drop_index("idx_oi_brief_status_updated", table_name="ark_order_intelligence_brief_jobs")
    op.drop_index("idx_oi_brief_owner_created", table_name="ark_order_intelligence_brief_jobs")
    op.drop_table("ark_order_intelligence_brief_jobs")
