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


def _column_exists(table_name: str, column_name: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(item.get("name") == column_name for item in columns)


def upgrade() -> None:
    if not _column_exists("ark_whatsapp_messages", "sender_wa_id"):
        op.add_column("ark_whatsapp_messages", sa.Column("sender_wa_id", sa.String(180), nullable=True))
    if not _column_exists("ark_whatsapp_messages", "sender_name"):
        op.add_column("ark_whatsapp_messages", sa.Column("sender_name", sa.String(160), nullable=True))


def downgrade() -> None:
    if _column_exists("ark_whatsapp_messages", "sender_name"):
        op.drop_column("ark_whatsapp_messages", "sender_name")
    if _column_exists("ark_whatsapp_messages", "sender_wa_id"):
        op.drop_column("ark_whatsapp_messages", "sender_wa_id")
