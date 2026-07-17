"""invoice: isolate standard-price keys by product kind

Revision ID: 074_invoice_price_kind_key
Revises: 073_invoice_accessory_products
Create Date: 2026-07-15
"""

from alembic import op


revision = "074_invoice_price_kind_key"
down_revision = "073_invoice_accessory_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ark_std_prices
        DROP INDEX uq_ark_std_prices_key,
        ADD UNIQUE KEY uq_ark_std_prices_key
            (product_kind, series_grade, length, weight_unit, color_type)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE ark_std_prices
        DROP INDEX uq_ark_std_prices_key,
        ADD UNIQUE KEY uq_ark_std_prices_key
            (series_grade, length, weight_unit, color_type)
    """)
