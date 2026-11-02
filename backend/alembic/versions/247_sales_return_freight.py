"""Separate refunded freight from goods and total cash; preserve existing returns.

Revision ID: 247_sales_return_freight
Revises: 246_domestic_followup
"""
from alembic import op
import sqlalchemy as sa

revision = '247_sales_return_freight'
down_revision = '246_domestic_followup'
branch_labels = None
depends_on = None

FIELDS = {
    'ark_sales_returns': [('freight_refund_amount', '现金退款中的运费原币金额')],
    'ark_sales_return_allocations': [
        ('freight_refund_amount', '退款分摊中的运费原币金额'),
        ('freight_refund_amount_usd', '退款分摊中的运费美元金额')],
    'ark_sales_return_effects': [
        ('freight_amount', '运费应收有符号冲减原币金额，不计商品 GMV'),
        ('freight_amount_usd', '运费应收有符号冲减美元金额，不计商品 GMV')],
}


def upgrade():
    for table, fields in FIELDS.items():
        columns = {column['name']: column for column in sa.inspect(op.get_bind()).get_columns(table)}
        for name, comment in fields:
            if name in columns:
                column = columns[name]
                kind = column['type']
                default = str(column['default']).strip("'()")
                if (not isinstance(kind, sa.Numeric) or kind.precision != 14 or kind.scale != 2
                        or column['nullable'] or default not in ('0', '0.00')):
                    raise RuntimeError(f'Unexpected existing freight column: {table}.{name}')
                continue  # Resume a partially completed additive MySQL migration.
            op.add_column(table, sa.Column(name, sa.Numeric(14, 2), nullable=False,
                                          server_default=sa.text('0'), comment=comment))


def downgrade():
    # Refuse to erase recorded freight facts; rollback code cannot reinterpret them.
    connection = op.get_bind()
    for table, fields in FIELDS.items():
        for name, _ in fields:
            if connection.scalar(sa.text(f'SELECT COUNT(*) FROM {table} WHERE {name} <> 0')):
                raise RuntimeError('Freight refund facts exist; keep the migration and reconcile before rollback')
    for table, fields in reversed(list(FIELDS.items())):
        for name, _ in reversed(fields):
            op.drop_column(table, name)
