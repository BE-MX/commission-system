"""add invoice packaging quantity

Revision ID: 071_invoice_packaging_qty
Revises: 070_invoice_item_discount
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "071_invoice_packaging_qty"
down_revision = "070_invoice_item_discount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ark_invoices",
        sa.Column(
            "packaging_quantity",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="包装数量，不参与金额乘算",
        ),
    )


def downgrade() -> None:
    op.drop_column("ark_invoices", "packaging_quantity")
