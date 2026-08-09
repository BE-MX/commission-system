"""Add immutable customer generation request snapshots.

Revision ID: 102_ci_generation_snapshots
Revises: 101_di_message_interact
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "102_ci_generation_snapshots"
down_revision = "101_di_message_interact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_customer_image_generations",
        sa.Column(
            "requirement_snapshot",
            sa.Text(),
            nullable=True,
            comment="客户补充要求快照",
        ),
    )
    op.add_column(
        "ark_customer_image_generations",
        sa.Column(
            "parameters_snapshot",
            sa.JSON(),
            nullable=False,
            comment="任务执行参数快照",
        ),
    )


def downgrade() -> None:
    op.drop_column("ark_customer_image_generations", "parameters_snapshot")
    op.drop_column("ark_customer_image_generations", "requirement_snapshot")
