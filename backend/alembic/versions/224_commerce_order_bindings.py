"""Strong order opening links without replacing sales or customer order ledgers."""
from alembic import op
import sqlalchemy as sa

revision = '224_commerce_order_bindings'
down_revision = '223_commerce_opening_links'
branch_labels = None
depends_on = None


def upgrade():
    for column, target, label in (
        ('local_invoice_id', 'ark_invoices', '已核验整单承接的现有发票主账'),
        ('local_customer_order_id', 'ark_customer_orders', '已核验整单承接的原客户经营投影身份'),
    ):
        op.add_column('ark_commerce_migration_records', sa.Column(column, sa.BigInteger(), nullable=True, comment=label))
        op.create_foreign_key(f'fk_migration_{column}', 'ark_commerce_migration_records', target,
            [column], ['id'], ondelete='RESTRICT')
        op.create_unique_constraint(f'uq_migration_{column}', 'ark_commerce_migration_records', [column])


def downgrade():
    raise RuntimeError('Do not discard verified order bindings; recover forward')
