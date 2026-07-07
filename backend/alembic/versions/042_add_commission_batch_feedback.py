"""add commission batch feedback

Revision ID: 042_commission_feedback
Revises: 041_confirming_status
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "042_commission_feedback"
down_revision = "041_confirming_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commission_batch_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False, comment="提成批次ID"),
        sa.Column("ark_user_id", sa.String(length=64), nullable=False, comment="方舟用户ID"),
        sa.Column("user_name", sa.String(length=128), nullable=True, comment="反馈人姓名"),
        sa.Column("business_user_ids", sa.String(length=255), nullable=True, comment="匹配到的业务库用户ID，逗号分隔"),
        sa.Column("content", sa.Text(), nullable=False, comment="反馈内容"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True, comment="反馈时间"),
        sa.ForeignKeyConstraint(["batch_id"], ["commission_batch.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commission_feedback_batch", "commission_batch_feedback", ["batch_id"])
    op.create_index("ix_commission_feedback_user", "commission_batch_feedback", ["ark_user_id"])


def downgrade() -> None:
    op.drop_index("ix_commission_feedback_user", table_name="commission_batch_feedback")
    op.drop_index("ix_commission_feedback_batch", table_name="commission_batch_feedback")
    op.drop_table("commission_batch_feedback")
