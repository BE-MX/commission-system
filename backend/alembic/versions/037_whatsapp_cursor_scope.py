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


def _column_exists(table_name: str, column_name: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(item.get("name") == column_name for item in columns)


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    constraints = sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    return any(item.get("name") == constraint_name for item in constraints)


def upgrade() -> None:
    if not _column_exists("ark_whatsapp_pull_cursors", "scope_uid"):
        op.add_column(
            "ark_whatsapp_pull_cursors",
            sa.Column("scope_uid", sa.String(160), nullable=False, server_default="global"),
        )
    if _unique_constraint_exists("ark_whatsapp_pull_cursors", "uk_wa_cursor_account_resource"):
        op.drop_constraint("uk_wa_cursor_account_resource", "ark_whatsapp_pull_cursors", type_="unique")
    if not _unique_constraint_exists("ark_whatsapp_pull_cursors", "uk_wa_cursor_account_resource_scope"):
        op.create_unique_constraint(
            "uk_wa_cursor_account_resource_scope",
            "ark_whatsapp_pull_cursors",
            ["account_uid", "resource", "scope_uid"],
        )
    if _column_exists("ark_whatsapp_pull_cursors", "scope_uid"):
        op.alter_column("ark_whatsapp_pull_cursors", "scope_uid", server_default=None)


def downgrade() -> None:
    if _unique_constraint_exists("ark_whatsapp_pull_cursors", "uk_wa_cursor_account_resource_scope"):
        op.drop_constraint("uk_wa_cursor_account_resource_scope", "ark_whatsapp_pull_cursors", type_="unique")
    if not _unique_constraint_exists("ark_whatsapp_pull_cursors", "uk_wa_cursor_account_resource"):
        op.create_unique_constraint(
            "uk_wa_cursor_account_resource",
            "ark_whatsapp_pull_cursors",
            ["account_uid", "resource"],
        )
    if _column_exists("ark_whatsapp_pull_cursors", "scope_uid"):
        op.drop_column("ark_whatsapp_pull_cursors", "scope_uid")
