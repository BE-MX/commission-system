"""add whatsapp message sender profile fields

Revision ID: 036_wa_sender_profile
Revises: 034_customer_radar, 035_whatsapp_connector
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "036_wa_sender_profile"
down_revision = ("034_customer_radar", "035_whatsapp_connector")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ark_whatsapp_messages", sa.Column("sender_wa_id", sa.String(180), nullable=True))
    op.add_column("ark_whatsapp_messages", sa.Column("sender_name", sa.String(160), nullable=True))


def downgrade() -> None:
    op.drop_column("ark_whatsapp_messages", "sender_name")
    op.drop_column("ark_whatsapp_messages", "sender_wa_id")
