"""add confirming status to commission_batch

Revision ID: 041_confirming_status
Revises: 040_payment_fx_fields
Create Date: 2026-07-01
"""

from alembic import op


revision = "041_confirming_status"
down_revision = "040_payment_fx_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE commission_batch MODIFY COLUMN status "
        "ENUM('draft','calculated','confirming','confirmed','voided') "
        "DEFAULT 'draft'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE commission_batch MODIFY COLUMN status "
        "ENUM('draft','calculated','confirmed','voided') "
        "DEFAULT 'draft'"
    )
