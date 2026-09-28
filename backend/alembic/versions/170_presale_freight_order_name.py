"""Reserve a freight order name before remote creation for statistics fencing."""
from alembic import op
import sqlalchemy as sa


revision = "170_presale_freight_name"
down_revision = "169_pcw_customer_workbench"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_receivables", sa.Column("remote_order_name", sa.String(length=96), nullable=True))
    op.add_column("ark_receivables", sa.Column("remote_payload", sa.JSON(), nullable=True))
    op.add_column("ark_receivables", sa.Column("remote_payload_hash", sa.String(length=64), nullable=True))
    op.add_column("ark_receivables", sa.Column("attempt_token", sa.String(length=64), nullable=True))
    op.add_column("ark_receivables", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("ark_receivables", sa.Column("last_error", sa.String(length=500), nullable=True))
    op.add_column("ark_receivables", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_unique_constraint("uq_receivable_remote_order_name", "ark_receivables", ["remote_order_name"])
    op.add_column("ark_shipment_outbounds", sa.Column("remote_line_snapshot", sa.JSON(), nullable=True))
    op.add_column("ark_shipment_outbounds", sa.Column("last_check_attempt_at", sa.DateTime(), nullable=True))


def downgrade():
    raise RuntimeError("Freight roles may be active; preserve the order-name reservation on rollback.")
