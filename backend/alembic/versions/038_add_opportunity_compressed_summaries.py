"""add compressed opportunity summaries

Revision ID: 038_opp_summaries
Revises: 037_wa_cursor_scope
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "038_opp_summaries"
down_revision = "037_wa_cursor_scope"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(item.get("name") == column_name for item in columns)


def upgrade() -> None:
    if not _column_exists("ark_customer_opportunities", "conversation_summary_json"):
        op.add_column(
            "ark_customer_opportunities",
            sa.Column("conversation_summary_json", sa.JSON(), nullable=True, comment="ACCIO 压缩后的询盘历史摘要"),
        )
    if not _column_exists("ark_customer_opportunities", "background_summary_json"):
        op.add_column(
            "ark_customer_opportunities",
            sa.Column("background_summary_json", sa.JSON(), nullable=True, comment="ACCIO 压缩后的背调摘要"),
        )
    if not _column_exists("ark_customer_opportunities", "customer_profile_json"):
        op.add_column(
            "ark_customer_opportunities",
            sa.Column("customer_profile_json", sa.JSON(), nullable=True, comment="ACCIO 客户档案快照"),
        )


def downgrade() -> None:
    if _column_exists("ark_customer_opportunities", "customer_profile_json"):
        op.drop_column("ark_customer_opportunities", "customer_profile_json")
    if _column_exists("ark_customer_opportunities", "background_summary_json"):
        op.drop_column("ark_customer_opportunities", "background_summary_json")
    if _column_exists("ark_customer_opportunities", "conversation_summary_json"):
        op.drop_column("ark_customer_opportunities", "conversation_summary_json")
