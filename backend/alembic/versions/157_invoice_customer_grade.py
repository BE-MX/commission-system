"""Add Ark customer grades and invoice snapshots without changing the mirror."""
from alembic import op
import sqlalchemy as sa

revision = "157_invoice_customer_grade"
down_revision = "156_receipt_management"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_invoice_customer_profiles",
        sa.Column("customer_id", sa.String(64), primary_key=True),
        sa.Column("customer_grade", sa.String(1), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    op.add_column("ark_invoices", sa.Column("customer_grade", sa.String(1), nullable=True))


def downgrade():
    op.drop_column("ark_invoices", "customer_grade")
    op.drop_table("ark_invoice_customer_profiles")
