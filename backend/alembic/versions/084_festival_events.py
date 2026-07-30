"""采购节大屏事件流表（摘要屏滚动记录 + 弹窗触发源，幂等键去重）

Revision ID: 084_festival_events
Revises: 083_expo_result_quality
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op

revision = "084_festival_events"
down_revision = "083_expo_result_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ark_festival_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("level", sa.String(4), nullable=False),
        sa.Column("subject_type", sa.String(8), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("subject_name", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("detail", sa.String(255), nullable=True),
        sa.Column("dedup_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_festival_events_dedup", "ark_festival_events", ["dedup_key"])
    op.create_index("ix_festival_events_created", "ark_festival_events", ["created_at"])
    op.create_index("ix_ark_festival_events_event_type", "ark_festival_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("ark_festival_events")
