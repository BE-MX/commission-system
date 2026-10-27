"""Persist invoice inspection photo requirements with deterministic historical defaults."""
from alembic import op
import sqlalchemy as sa

revision = "208_invoice_inspection_photos"
down_revision = "207_inkboard"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_invoices", sa.Column(
        "inspection_requirement", sa.String(16), nullable=False, server_default="single",
        comment="检验要求：single单张检验照片/detail明细检验照片"))
    op.execute(sa.text(
        "UPDATE ark_invoices SET inspection_requirement = 'detail' WHERE okki_new_deal = 1"))


def downgrade():
    # Preserve saved warehouse instructions; production uses forward-only migrations.
    pass
