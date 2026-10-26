"""Persist buyer delivery defaults without rewriting order snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '204_portal_delivery_profile'
down_revision = '203_perf_goals'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ark_order_portal_accounts', sa.Column('delivery_json', sa.JSON(), nullable=True,
        comment='采购账号默认收货资料；历史订单保持独立快照'))


def downgrade():
    raise RuntimeError('Preserve saved buyer delivery details when rolling back application code')
