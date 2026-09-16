"""OKKI outbound task queue: auto-generate sales outbound after first invoice push."""
from alembic import op
import sqlalchemy as sa

revision = '154_okki_outbound_tasks'
down_revision = '153_shipping_station'
branch_labels = None
depends_on = None


def upgrade():
    # DDL can stop mid-way on MySQL; resume without overwriting rows.
    existing = sa.inspect(op.get_bind()).get_table_names()
    if 'ark_okki_outbound_tasks' not in existing:
        op.create_table('ark_okki_outbound_tasks',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('invoice_id', sa.BigInteger(), nullable=False),
            sa.Column('order_id', sa.String(64), nullable=False),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('reason', sa.String(255)),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_error', sa.Text()),
            sa.Column('processed_at', sa.DateTime()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('order_id', name='uq_okki_outbound_task_order'),
            mysql_comment='OKKI 销售出库单自动生成任务队列（singapore okki-sync 轮询消费）')
    indexes = {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('ark_okki_outbound_tasks')}
    if 'idx_okki_outbound_task_status' not in indexes:
        op.create_index('idx_okki_outbound_task_status', 'ark_okki_outbound_tasks', ['status', 'id'])
    validate_schema()


def validate_schema():
    inspector = sa.inspect(op.get_bind())
    # A prior interrupted DDL is reusable only if its contract actually matches.
    specifications = {
        'id': (sa.BigInteger, None, False), 'invoice_id': (sa.BigInteger, None, False),
        'order_id': (sa.String, 64, False), 'status': (sa.String, 16, False),
        'reason': (sa.String, 255, True), 'attempts': (sa.Integer, None, False),
        'last_error': (sa.Text, None, True),
        **{key: (sa.DateTime, None, True) for key in ('processed_at',)},
        **{key: (sa.DateTime, None, False) for key in ('created_at', 'updated_at')},
    }
    actual = {c['name']: c for c in inspector.get_columns('ark_okki_outbound_tasks')}
    for name, (kind, length, nullable) in specifications.items():
        col = actual.get(name)
        if col is None or not isinstance(col['type'], kind) or col['nullable'] != nullable or (length and col['type'].length != length):
            raise RuntimeError(f'Incompatible outbound task column: ark_okki_outbound_tasks.{name}')
    if inspector.get_pk_constraint('ark_okki_outbound_tasks')['constrained_columns'] != ['id']:
        raise RuntimeError('Incompatible outbound task primary key: ark_okki_outbound_tasks')
    if not any(item['column_names'] == ['order_id'] for item in inspector.get_unique_constraints('ark_okki_outbound_tasks')):
        raise RuntimeError('Missing outbound task order_id uniqueness')


def downgrade():
    raise RuntimeError('Outbound task history must be preserved; use a reviewed forward migration')
