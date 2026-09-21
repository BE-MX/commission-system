"""Durable invoice cancellation and outbound enrollment."""
from alembic import op
import sqlalchemy as sa

revision = "161_invoice_lifecycle"
down_revision = "160_domestic_price_review"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ark_invoices")}
    if "sync_attempt" not in columns:
        op.add_column("ark_invoices", sa.Column("sync_attempt", sa.JSON(), nullable=True, comment="Durable order send token and lease"))
    if "cancellation" not in columns:
        op.add_column("ark_invoices", sa.Column("cancellation", sa.JSON(), nullable=True,
                                              comment="Durable cancellation workflow and evidence"))
    if "outbound_auto_requested" not in columns:
        op.add_column("ark_invoices", sa.Column("outbound_auto_requested", sa.SmallInteger(), nullable=False,
                                              server_default="0", comment="Explicit automatic outbound enrollment"))


def downgrade():
    raise RuntimeError("Cancellation evidence must be retained; use a forward migration")
