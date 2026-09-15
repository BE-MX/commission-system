"""Shared-phone inspection sessions and immutable operation attribution."""
from alembic import op
import sqlalchemy as sa

revision = '153_shipping_station'
down_revision = '151_customer_media_tags'
branch_labels = None
depends_on = None


def upgrade():
    # DDL can stop between tables on MySQL; resume without overwriting rows.
    existing = sa.inspect(op.get_bind()).get_table_names()
    if 'ark_shipping_station_sessions' not in existing:
        op.create_table('ark_shipping_station_sessions',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('login_user_id', sa.Integer(), nullable=False),
            sa.Column('operator_user_id', sa.Integer(), nullable=False),
            sa.Column('operator_name', sa.String(50), nullable=False),
            sa.Column('outbound_record_id', sa.String(64), nullable=False),
            sa.Column('scan_request_id', sa.String(64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_active_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('ended_at', sa.DateTime()),
            sa.UniqueConstraint('login_user_id', 'scan_request_id', name='uq_shipping_station_scan'))
    if 'ark_shipping_operation_events' not in existing:
        op.create_table('ark_shipping_operation_events',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('scope', sa.String(80), nullable=False), sa.Column('request_id', sa.String(64)),
            sa.Column('source', sa.String(20), nullable=False), sa.Column('action', sa.String(20), nullable=False),
            sa.Column('login_user_id', sa.Integer(), nullable=False), sa.Column('operator_user_id', sa.Integer(), nullable=False),
            sa.Column('operator_name', sa.String(50), nullable=False), sa.Column('login_name', sa.String(50), nullable=False),
            sa.Column('outbound_record_id', sa.String(64), nullable=False), sa.Column('inspection_id', sa.BigInteger()),
            sa.Column('media_id', sa.BigInteger()), sa.Column('edit_version', sa.Integer()),
            sa.Column('payload', sa.JSON()), sa.Column('result', sa.JSON()), sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('scope', 'request_id', name='uq_shipping_event_request'))
    indexes = {i['name'] for i in sa.inspect(op.get_bind()).get_indexes('ark_shipping_operation_events')}
    if 'idx_shipping_event_outbound' not in indexes:
        op.create_index('idx_shipping_event_outbound', 'ark_shipping_operation_events', ['outbound_record_id', 'id'])
    validate_schema()


def validate_schema():
    inspector = sa.inspect(op.get_bind())
    # A prior interrupted DDL is reusable only if its contract actually matches.
    specifications = {
        'ark_shipping_station_sessions': {
            'id': (sa.String, 36, False), 'login_user_id': (sa.Integer, None, False),
            'operator_user_id': (sa.Integer, None, False), 'operator_name': (sa.String, 50, False),
            'outbound_record_id': (sa.String, 64, False), 'scan_request_id': (sa.String, 64, False),
            **{key: (sa.DateTime, None, False) for key in ('created_at', 'last_active_at', 'expires_at')},
            'ended_at': (sa.DateTime, None, True),
        },
        'ark_shipping_operation_events': {
            'id': (sa.Integer, None, False), 'scope': (sa.String, 80, False), 'request_id': (sa.String, 64, True),
            'source': (sa.String, 20, False), 'action': (sa.String, 20, False),
            'login_user_id': (sa.Integer, None, False), 'operator_user_id': (sa.Integer, None, False),
            'operator_name': (sa.String, 50, False), 'login_name': (sa.String, 50, False),
            'outbound_record_id': (sa.String, 64, False), 'inspection_id': (sa.Integer, None, True),
            'media_id': (sa.Integer, None, True), 'edit_version': (sa.Integer, None, True),
            'payload': (sa.JSON, None, True), 'result': (sa.JSON, None, True), 'created_at': (sa.DateTime, None, False),
        },
    }
    for table, columns in specifications.items():
        actual = {c['name']: c for c in inspector.get_columns(table)}
        for name, (kind, length, nullable) in columns.items():
            col = actual.get(name)
            if col is None or not isinstance(col['type'], kind) or col['nullable'] != nullable or (length and col['type'].length != length):
                raise RuntimeError(f'Incompatible shipping station column: {table}.{name}')
        if inspector.get_pk_constraint(table)['constrained_columns'] != ['id']:
            raise RuntimeError(f'Incompatible shipping station primary key: {table}')
        expected = ['login_user_id', 'scan_request_id'] if table.endswith('sessions') else ['scope', 'request_id']
        if not any(item['column_names'] == expected for item in inspector.get_unique_constraints(table)):
            raise RuntimeError(f'Missing shipping station receipt uniqueness: {table}')


def downgrade():
    raise RuntimeError('Shipping identity history must be preserved; use a reviewed forward migration')
