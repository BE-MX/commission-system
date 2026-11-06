"""Audit explicit product inventory refreshes."""
from alembic import op
import sqlalchemy as sa

revision = '253_inventory_sync_audit'
down_revision = '252_alibaba_feed_business'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ark_inventory_sync_logs',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True, comment='主键'),
        sa.Column('product_id', sa.BigInteger(), nullable=False, comment='小满产品ID'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='操作人ID'),
        sa.Column('observed_at', sa.DateTime(), nullable=False, comment='库存拉取开始北京时间'),
        sa.Column('before_data', sa.JSON(), nullable=False, comment='同步前库存快照'),
        sa.Column('after_data', sa.JSON(), nullable=False, comment='同步后库存快照'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='审计创建北京时间'))
    op.create_index('ix_inventory_sync_product_time', 'ark_inventory_sync_logs', ['product_id', 'created_at'])


def downgrade():
    op.drop_table('ark_inventory_sync_logs')
