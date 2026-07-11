"""make aftersales notifications resilient to missing dingtalk bindings

Revision ID: 059_aftersales_notify_user
Revises: 058_aftersales_controls
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "059_aftersales_notify_user"
down_revision = "058_aftersales_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "uq_aftersales_notify_event_recipient",
        "ark_aftersales_notification_logs",
        type_="unique",
    )
    op.alter_column(
        "ark_aftersales_notification_logs",
        "recipient_dingtalk_id",
        existing_type=sa.String(100),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_aftersales_notify_event_recipient",
        "ark_aftersales_notification_logs",
        ["business_event_key", "recipient_user_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_aftersales_notify_event_recipient",
        "ark_aftersales_notification_logs",
        type_="unique",
    )
    op.alter_column(
        "ark_aftersales_notification_logs",
        "recipient_dingtalk_id",
        existing_type=sa.String(100),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_aftersales_notify_event_recipient",
        "ark_aftersales_notification_logs",
        ["business_event_key", "recipient_dingtalk_id"],
    )
