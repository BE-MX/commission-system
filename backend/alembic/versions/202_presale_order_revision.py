"""Persist explicit whole-order presale revisions without rewriting shipment facts."""
from alembic import op
import sqlalchemy as sa

revision='202_presale_order_revision'
down_revision='201_portal_access_requests'
branch_labels=None
depends_on=None

def upgrade():
    if op.get_context().as_sql or 'presale_order_revision' not in {
            column['name'] for column in sa.inspect(op.get_bind()).get_columns('ark_invoices')}:
        op.add_column('ark_invoices',sa.Column('presale_order_revision',sa.JSON(),nullable=True))

def downgrade():
    raise RuntimeError('不可删除整单修订、历史来源及已用抵扣证据；回退代码须保留扩展结构')
