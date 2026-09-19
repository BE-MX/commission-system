"""Durable owner-bound file transfers with deletion tombstones."""
from alembic import op
import sqlalchemy as sa

revision = '159_storage_transfers'
down_revision = '158_invoice_linked_sync'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ark_storage_transfers',
        sa.Column('id', sa.String(64), primary_key=True, comment='SHA256 of domain and immutable relative key'),
        sa.Column('domain', sa.String(64), nullable=False, comment='Storage domain'),
        sa.Column('object_key', sa.String(768), nullable=False, comment='Immutable relative object key'),
        sa.Column('source_instance', sa.String(128), nullable=False, comment='Owner of durable local original'),
        sa.Column('file_size', sa.BigInteger(), nullable=False, comment='Original byte count'),
        sa.Column('sha256', sa.String(64), nullable=False, comment='Original SHA256'),
        sa.Column('content_type', sa.String(128), nullable=False, comment='Content MIME type'),
        sa.Column('status', sa.String(16), nullable=False, comment='pending/running/ready/deleted'),
        sa.Column('attempts', sa.Integer(), nullable=False, comment='Claim count'),
        sa.Column('lease_token', sa.String(64), comment='Fencing token'),
        sa.Column('lease_until', sa.DateTime(), comment='Lease expiry, Beijing time'),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False, comment='Next reconciliation, Beijing time'),
        sa.Column('last_error', sa.String(128), comment='Redacted failure category'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Created, Beijing time'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='Updated, Beijing time'))
    op.create_index('ix_storage_transfer_claim', 'ark_storage_transfers', ['source_instance', 'status', 'next_attempt_at'])
    op.create_table('ark_storage_aliases',
        sa.Column('id', sa.String(64), primary_key=True, comment='SHA256 of domain and logical key'),
        sa.Column('domain', sa.String(64), nullable=False, comment='Storage domain'),
        sa.Column('logical_key', sa.String(768), nullable=False, comment='Stable business name'),
        sa.Column('target_key', sa.String(768), nullable=True, comment='Immutable object key; NULL means deleted'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Created, Beijing time'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='Updated, Beijing time'))


    op.create_table('ark_storage_publications',
        sa.Column('id', sa.String(64), primary_key=True, comment='SHA256 of domain/key/upload identity'),
        sa.Column('response_json', sa.JSON(), nullable=False, comment='Immutable successful publication response'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Created, Beijing time'))


def downgrade():
    raise RuntimeError('Storage transfer receipts and tombstones must not be dropped automatically')
