"""add invoice item discount

Revision ID: 070_invoice_item_discount
Revises: 069_aftersales_review_split
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "070_invoice_item_discount"
down_revision = "069_aftersales_review_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_invoice_items",
        sa.Column(
            "discount_amount",
            sa.Numeric(14, 2),
            nullable=False,
            server_default=sa.text("0"),
            comment="行级折扣，恒为负数或0（发票币种）",
        ),
    )


def downgrade() -> None:
    op.drop_column("ark_invoice_items", "discount_amount")
