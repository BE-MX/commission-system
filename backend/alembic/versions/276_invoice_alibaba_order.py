"""Add Alibaba order number for convenient shipping invoices."""
from alembic import op
import sqlalchemy as sa

revision = "276_invoice_alibaba_order"
down_revision = "275_factory_inbound_batch"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoices", sa.Column("alibaba_order_no", sa.String(20), nullable=True, comment="阿里信保订单号（便捷发货必填）"))
    op.create_index("ix_ark_invoices_alibaba_order_no", "ark_invoices", ["alibaba_order_no"])


def downgrade():
    raise RuntimeError("Alibaba order numbers require an explicit retention decision")
