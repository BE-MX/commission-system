"""Preserve allocation faces and project cumulative local reversals.

Revision ID: 213_partial_receipt_reversal
Revises: 212_local_fulfillment
"""
from alembic import op
import sqlalchemy as sa

revision = "213_partial_receipt_reversal"
down_revision = "212_local_fulfillment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_receipts", sa.Column("reversed_amount", sa.Numeric(14, 2),
        nullable=False, server_default="0", comment="本地核销累计冲回金额，原核销事实不覆盖"))
    op.add_column("ark_receipts", sa.Column("reversed_bank_charge", sa.Numeric(14, 2),
        nullable=False, server_default="0", comment="本地核销累计冲回客户附加费"))
    # The previous local command only permitted complete reversals. Reconstruct
    # those projections without changing the immutable amount or fee faces.
    op.execute("UPDATE ark_receipts SET reversed_amount = amount, reversed_bank_charge = bank_charge "
               "WHERE source = 'local' AND status = 'reversed'")


def downgrade():
    raise RuntimeError("Partial reversal facts cannot be discarded; use a corrective migration")
