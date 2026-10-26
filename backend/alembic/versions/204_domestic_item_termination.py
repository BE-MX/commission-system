"""Preserve quantity cancellation audit without altering historical work or shipments."""
from alembic import op
import sqlalchemy as sa

revision = '204_domestic_item_termination'
down_revision = '202_presale_order_revision'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ark_domestic_orders', sa.Column(
        'skip_all_records', sa.JSON(), nullable=True, comment='整单跳过请求幂等结果与操作者审计',
    ))
    op.add_column('ark_domestic_order_items', sa.Column(
        'termination_records', sa.JSON(), nullable=True,
        comment='明细终止审计：数量、单件、原因、操作者、北京时间与幂等键',
    ))


def downgrade():
    raise RuntimeError('终止数量与退款审计不可删除；回退代码须保留扩展字段')
