"""add whatsapp pull cursor scope

Revision ID: 037_wa_cursor_scope
Revises: 036_wa_sender_profile
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "037_wa_cursor_scope"
down_revision = "036_wa_sender_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_whatsapp_pull_cursors",
        sa.Column("scope_uid", sa.String(160), nullable=False, server_default="global"),
    )
    op.drop_constraint("uk_wa_cursor_account_resource", "ark_whatsapp_pull_cursors", type_="unique")
    op.create_unique_constraint(
        "uk_wa_cursor_account_resource_scope",
        "ark_whatsapp_pull_cursors",
        ["account_uid", "resource", "scope_uid"],
    )
    op.alter_column("ark_whatsapp_pull_cursors", "scope_uid", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uk_wa_cursor_account_resource_scope", "ark_whatsapp_pull_cursors", type_="unique")
    op.create_unique_constraint(
        "uk_wa_cursor_account_resource",
        "ark_whatsapp_pull_cursors",
        ["account_uid", "resource"],
    )
    op.drop_column("ark_whatsapp_pull_cursors", "scope_uid")
