"""backfill product_amount for pre-049 invoices

049 added product_amount with server_default 0 but did not backfill, so
exports of legacy invoices showed 'Hair cost in total: 0.00' against a
non-zero Total. Legacy rows have shipping_fee/surcharge_amount = 0, so
product_amount equals total_amount.

Revision ID: 050_backfill_product_amt
Revises: 049_invoice_v2_pricing
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa


revision = "050_backfill_product_amt"
down_revision = "049_invoice_v2_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE ark_invoices "
        "SET product_amount = total_amount - shipping_fee - surcharge_amount "
        "WHERE product_amount = 0 AND total_amount <> 0"
    ))


def downgrade() -> None:
    pass  # data backfill, nothing to revert
