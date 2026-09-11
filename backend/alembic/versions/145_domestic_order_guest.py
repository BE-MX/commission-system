"""Add optional guest name to domestic business orders."""
from alembic import op
import sqlalchemy as sa

revision = "145_domestic_order_guest"
down_revision = "144_mail_outreach_core"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_orders", sa.Column(
        "guest_name", sa.String(120), nullable=True, comment="业务订单顾客",
    ))


def downgrade():
    op.drop_column("ark_domestic_orders", "guest_name")
