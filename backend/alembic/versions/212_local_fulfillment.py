"""Freeze local presale deposit terms independently of cash received.

Revision ID: 212_local_fulfillment
Revises: 211_local_production
"""
from alembic import op
import sqlalchemy as sa

revision = "212_local_fulfillment"
down_revision = "211_local_production"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoices", sa.Column("local_deposit_amount", sa.Numeric(14, 2), nullable=False,
        server_default="0", comment="本地预售合同首款总额，确认后冻结"))
    op.add_column("ark_invoices", sa.Column("local_deposit_charge", sa.Numeric(14, 2), nullable=False,
        server_default="0", comment="本地预售首款包含的客户附加费用"))

    op.add_column("ark_shipping_inspections", sa.Column("local_outbound_id", sa.BigInteger(), nullable=True,
        comment="本地出库ID，历史检验保持为空"))
    op.add_column("ark_shipping_inspections", sa.Column("local_outbound_version", sa.Integer(), nullable=True,
        comment="本次检验对应的本地出库明细版本"))
    op.create_foreign_key("fk_inspection_local_outbound", "ark_shipping_inspections", "ark_shipment_outbounds", ["local_outbound_id"], ["id"])
    op.create_unique_constraint("uq_inspection_local_outbound", "ark_shipping_inspections", ["local_outbound_id"])


def downgrade():
    raise RuntimeError("Financial contract facts cannot be discarded; use a reviewed forward migration")
