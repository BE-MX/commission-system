"""add full_report_html column to ark_customer_opportunities

Revision ID: 032_opp_full_report
Revises: 031_customer_opportunity
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "032_opp_full_report"
down_revision = "031_customer_opportunity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_customer_opportunities",
        sa.Column("full_report_html", sa.Text(), nullable=True, comment="ACCIO 完整背调报告 HTML"),
    )


def downgrade() -> None:
    op.drop_column("ark_customer_opportunities", "full_report_html")
