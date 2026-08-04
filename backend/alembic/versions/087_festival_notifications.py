"""采购节状态型事件与钉钉投递字段

Revision ID: 087_festival_notify
Revises: 086_card_butler
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op

revision = "087_festival_notify"
down_revision = "086_card_butler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ark_festival_events", sa.Column("dingtalk_sent_at", sa.DateTime(), nullable=True))
    op.add_column("ark_festival_events", sa.Column("dingtalk_claimed_at", sa.DateTime(), nullable=True))
    op.add_column("ark_festival_events", sa.Column("dingtalk_next_retry_at", sa.DateTime(), nullable=True))
    op.add_column(
        "ark_festival_events",
        sa.Column("dingtalk_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("ark_festival_events", sa.Column("dingtalk_last_error", sa.String(500), nullable=True))

    # 上线时不补发历史事件；迁移后新事件保持 NULL，进入待投递队列。
    op.execute("UPDATE ark_festival_events SET dingtalk_sent_at = created_at")

    op.create_table(
        "ark_festival_states",
        sa.Column("state_key", sa.String(96), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False, comment="事件检测或投递状态 JSON"),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
            comment="状态最近更新时间",
        ),
    )
    op.execute(
        "INSERT INTO ark_festival_states (state_key, value_json) "
        "VALUES ('detector:lock', '{\"purpose\":\"serialize festival event detection\"}')"
    )


def downgrade() -> None:
    op.drop_table("ark_festival_states")
    op.drop_column("ark_festival_events", "dingtalk_last_error")
    op.drop_column("ark_festival_events", "dingtalk_attempts")
    op.drop_column("ark_festival_events", "dingtalk_next_retry_at")
    op.drop_column("ark_festival_events", "dingtalk_claimed_at")
    op.drop_column("ark_festival_events", "dingtalk_sent_at")
