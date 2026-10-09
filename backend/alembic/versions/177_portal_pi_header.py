"""Persist the commercial header a customer actually confirms for a revised PI.

Existing revision evidence stays unchanged; NULL is not backfilled from a live PI.
"""
from alembic import op
import sqlalchemy as sa

revision = "177_portal_pi_header"
down_revision = "176_customer_order_portal"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_order_portal_revisions", sa.Column("invoice_presentation_json", sa.JSON(),
        nullable=True, comment="PI后续修订的客户可见商业抬头快照"))


def downgrade():
    raise RuntimeError("Confirmed PI evidence must not be dropped; use a forward migration")
