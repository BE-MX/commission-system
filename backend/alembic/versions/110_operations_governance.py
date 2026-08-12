"""Add runtime operation audit and scheduler policy.

Revision ID: 110_operations_governance
Revises: 109_order_brief_jobs
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "110_operations_governance"
down_revision = "109_order_brief_jobs"
branch_labels = None
depends_on = None

USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def upgrade() -> None:
    op.create_table(
        "ark_operation_audits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False, comment="主键"),
        sa.Column("actor_user_id", USER_ID, nullable=True, comment="操作人方舟用户ID"),
        sa.Column("actor_name", sa.String(length=80), nullable=False, comment="操作人名称快照"),
        sa.Column("source_ip", sa.String(length=45), nullable=True, comment="可信代理来源IP"),
        sa.Column("instance_id", sa.String(length=255), nullable=False, comment="目标实例hostname"),
        sa.Column("action", sa.String(length=20), nullable=False, comment="任务控制动作"),
        sa.Column("job_id", sa.String(length=100), nullable=False, comment="稳定任务ID"),
        sa.Column("result", sa.String(length=20), nullable=False, comment="控制结果"),
        sa.Column("detail", sa.String(length=255), nullable=True, comment="非敏感结果摘要"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="操作时间"),
        sa.PrimaryKeyConstraint("id"),
        comment="运行中心任务控制审计",
    )
    op.create_index("idx_operations_audit_job_time", "ark_operation_audits", ["job_id", "created_at"])
    op.create_table(
        "ark_scheduler_job_policies",
        sa.Column("instance_id", sa.String(length=255), nullable=False, comment="目标实例hostname"),
        sa.Column("job_id", sa.String(length=100), nullable=False, comment="稳定任务ID"),
        sa.Column("paused", sa.Integer(), nullable=False, server_default="0", comment="1=跨重启保持暂停"),
        sa.Column("updated_by", USER_ID, nullable=True, comment="最近操作人方舟用户ID"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.PrimaryKeyConstraint("instance_id", "job_id"),
        comment="定时任务持久暂停策略",
    )


def downgrade() -> None:
    op.drop_table("ark_scheduler_job_policies")
    op.drop_index("idx_operations_audit_job_time", table_name="ark_operation_audits")
    op.drop_table("ark_operation_audits")
