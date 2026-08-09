"""Add structured interactions to design image messages.

Revision ID: 103_di_message_interact
Revises: 102_customer_image_portal
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "103_di_message_interact"
down_revision = "102_customer_image_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_design_image_messages",
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ark_design_image_messages",
        sa.Column("interaction_json", sa.JSON(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_di_message_session_client_request",
        "ark_design_image_messages",
        ["session_id", "client_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_di_message_session_client_request",
        "ark_design_image_messages",
        type_="unique",
    )
    op.drop_column("ark_design_image_messages", "interaction_json")
    op.drop_column("ark_design_image_messages", "client_request_id")
