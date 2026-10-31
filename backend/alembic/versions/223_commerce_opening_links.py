"""Preserve historical order-item identities and effective commission FX."""
from alembic import op
import sqlalchemy as sa

revision = '223_commerce_opening_links'
down_revision = '222_commerce_migration'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ark_customer_order_items', sa.Column('local_invoice_item_id', sa.BigInteger(), nullable=True,
        comment='核验后的本地销售行唯一关联；承接保留原明细身份与信源'))
    op.create_foreign_key('fk_customer_order_item_local_invoice', 'ark_customer_order_items', 'ark_invoice_items',
        ['local_invoice_item_id'], ['id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_customer_order_item_local_invoice', 'ark_customer_order_items', ['local_invoice_item_id'])
    # Widening retains every original scaled historical value. New effective
    # rates have eight decimal places after converting the legacy /100 unit.
    op.alter_column('synced_payment', 'exchange_rate', existing_type=sa.Numeric(12, 6),
        type_=sa.Numeric(18, 8), existing_nullable=True, existing_comment='汇率',
        comment='汇率；历史原值不缩放，本地记录保留冻结有效汇率')
    for role, label in (('salesperson', '业务员'), ('supervisor', '一级主管'), ('second_supervisor', '二级主管')):
        op.add_column('ark_commission_event_projections', sa.Column(f'{role}_commission_rmb', sa.Numeric(14, 2),
            nullable=True, comment=f'冻结人民币{label}提成及累计冲回尾差'))


def downgrade():
    raise RuntimeError('Do not discard opening identities or frozen FX; recover forward')
