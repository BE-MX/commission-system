"""Audit an in-place upgrade of an unpaid legacy shipment's funding."""
from alembic import op
import sqlalchemy as sa

revision = "180_settlement_funding_amendment"
down_revision = "179_presale_funding"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ark_settlement_funding_amendments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("settlement_id", sa.BigInteger(), sa.ForeignKey("ark_shipment_settlements.id"), nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("ark_invoices.id"), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), sa.ForeignKey("ark_receipts.id"), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False, comment="升级前原结算、现金与运费完整快照"),
        sa.Column("after_snapshot", sa.JSON(), nullable=False, comment="升级后结算与资金分配完整快照"),
        sa.Column("evidence", sa.JSON(), nullable=False, comment="主单、首款、运费单及出库核验摘要"),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("settlement_id", name="uq_funding_amendment_settlement"),
        sa.UniqueConstraint("request_key", name="uq_funding_amendment_request"))
    op.create_index("ix_funding_amendment_invoice", "ark_settlement_funding_amendments", ["invoice_id"])


def downgrade():
    raise RuntimeError("Funding amendment audit facts must be preserved; use a forward migration")
