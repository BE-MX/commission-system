"""Keep default price snapshots and register sample orders."""
from alembic import op
import sqlalchemy as sa

revision = "160_domestic_price_review"
down_revision = "159_storage_transfers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_order_items", sa.Column(
        "default_discount_price", sa.Numeric(14, 2), nullable=True,
        comment="系统默认优惠价快照，不含手工费",
    ))
    op.execute(sa.text("""
        INSERT INTO sys_dict (type, code, label, sort, is_active, created_at, updated_at)
        SELECT 'domestic_order_type', 'sample', '样单', 60, 1, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM sys_dict WHERE type='domestic_order_type' AND code='sample'
        )
    """))


def downgrade():
    # Keep the dictionary entry: persisted orders may already reference it.
    op.drop_column("ark_domestic_order_items", "default_discount_price")
