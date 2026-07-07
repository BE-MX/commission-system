"""add commission batch confirmation

Revision ID: 043_commission_confirmation
Revises: 042_commission_feedback
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "043_commission_confirmation"
down_revision = "042_commission_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commission_batch_confirmation",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False, comment="提成批次ID"),
        sa.Column("ark_user_id", sa.String(length=64), nullable=False, comment="方舟用户ID"),
        sa.Column("user_name", sa.String(length=128), nullable=True, comment="确认人姓名"),
        sa.Column("business_user_ids", sa.String(length=255), nullable=True, comment="确认人匹配到的业务库用户ID，逗号分隔"),
        sa.Column("confirmation_text", sa.String(length=32), nullable=False, comment="确认输入文本"),
        sa.Column("status", sa.String(length=32), server_default="confirmed", nullable=False, comment="confirmed/revoked"),
        sa.Column("confirmed_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True, comment="确认时间"),
        sa.ForeignKeyConstraint(["batch_id"], ["commission_batch.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_commission_confirmation_batch", "commission_batch_confirmation", ["batch_id"])
    op.create_index("ix_commission_confirmation_user", "commission_batch_confirmation", ["ark_user_id"])
    op.create_index("uq_commission_confirmation_user", "commission_batch_confirmation", ["batch_id", "ark_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_commission_confirmation_user", table_name="commission_batch_confirmation")
    op.drop_index("ix_commission_confirmation_user", table_name="commission_batch_confirmation")
    op.drop_index("ix_commission_confirmation_batch", table_name="commission_batch_confirmation")
    op.drop_table("commission_batch_confirmation")
