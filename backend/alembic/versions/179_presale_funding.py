"""Preserve presale shipment history and original payment purpose/charge."""
from alembic import op
import sqlalchemy as sa

revision = "179_presale_funding"
down_revision = "178_account_unlock"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoices", sa.Column("presale_current_accessory", sa.Numeric(14, 2), nullable=True, comment="预售当前明细包装费"))
    op.add_column("ark_invoices", sa.Column("presale_current_handling", sa.Numeric(14, 2), nullable=True, comment="预售当前明细手续费"))
    op.add_column("ark_invoice_items", sa.Column("presale_archived", sa.Integer(), nullable=False, server_default="0", comment="预售历史明细标记"))
    op.add_column("ark_invoice_items", sa.Column("presale_shipped_quantity", sa.Integer(), nullable=False, server_default="0", comment="归档实际已出库数量"))
    op.add_column("ark_invoice_items", sa.Column("presale_shipped_amount", sa.Numeric(14, 2), nullable=False, server_default="0", comment="归档实际已出库商品金额"))
    op.add_column("ark_receipt_intents", sa.Column("purpose", sa.String(32), nullable=True, comment="首款用途"))
    op.add_column("ark_receipt_intents", sa.Column("bank_charge", sa.Numeric(14, 2), nullable=True, comment="首款原银行手续费"))


def downgrade():
    raise RuntimeError("Presale funding and shipment history must be preserved; use a forward migration")
