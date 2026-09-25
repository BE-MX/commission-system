"""Presale settlement ledgers and shared receipt batches (additive)."""
from alembic import op
import sqlalchemy as sa
revision = "166_presale_settlement"
down_revision = "164_battle_posters"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ark_shipment_settlements',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('settlement_no', sa.String(length=96), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('is_final', sa.Integer(), nullable=False),
    sa.Column('quote', sa.JSON(), nullable=False),
    sa.Column('quote_hash', sa.String(length=64), nullable=False),
    sa.Column('request_key', sa.String(length=64), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invoice_id', 'sequence', name='uq_shipment_sequence'),
    sa.UniqueConstraint('request_key'),
    sa.UniqueConstraint('settlement_no')
    )
    op.create_index(op.f('ix_ark_shipment_settlements_invoice_id'), 'ark_shipment_settlements', ['invoice_id'], unique=False)
    op.create_table('ark_shipment_settlement_items',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('settlement_id', sa.BigInteger(), nullable=False),
    sa.Column('invoice_item_id', sa.BigInteger(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('line_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['invoice_item_id'], ['ark_invoice_items.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['settlement_id'], ['ark_shipment_settlements.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('settlement_id', 'invoice_item_id', name='uq_shipment_item')
    )
    op.create_index(op.f('ix_ark_shipment_settlement_items_settlement_id'), 'ark_shipment_settlement_items', ['settlement_id'], unique=False)
    op.create_table('ark_receivables',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('settlement_id', sa.BigInteger(), nullable=True),
    sa.Column('business_key', sa.String(length=96), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('handling_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=16), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('remote_order_id', sa.String(length=64), nullable=True),
    sa.Column('remote_status', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], ),
    sa.ForeignKeyConstraint(['settlement_id'], ['ark_shipment_settlements.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_key'),
    sa.UniqueConstraint('remote_order_id')
    )
    op.create_index(op.f('ix_ark_receivables_invoice_id'), 'ark_receivables', ['invoice_id'], unique=False)
    op.create_table('ark_receipt_batches',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('batch_no', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('currency', sa.String(length=16), nullable=False),
    sa.Column('gross_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('bank_charge_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('collection_date', sa.Date(), nullable=False),
    sa.Column('payment_type', sa.String(length=64), nullable=False),
    sa.Column('remark', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('request_key', sa.String(length=64), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_no'),
    sa.UniqueConstraint('request_key')
    )
    op.create_table('ark_receipt_batch_attachments',
    sa.Column('batch_id', sa.BigInteger(), nullable=False),
    sa.Column('attachment_id', sa.String(length=32, collation='utf8mb4_0900_ai_ci'), nullable=False),
    sa.ForeignKeyConstraint(['attachment_id'], ['ark_receipt_attachments.id'], ),
    sa.ForeignKeyConstraint(['batch_id'], ['ark_receipt_batches.id'], ),
    sa.PrimaryKeyConstraint('batch_id', 'attachment_id'),
    sa.UniqueConstraint('attachment_id')
    )
    op.create_table('ark_settlement_applications',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('settlement_id', sa.BigInteger(), nullable=False),
    sa.Column('receipt_id', sa.BigInteger(), nullable=False),
    sa.Column('component', sa.String(length=16), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('bank_charge', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['receipt_id'], ['ark_receipts.id'], ),
    sa.ForeignKeyConstraint(['settlement_id'], ['ark_shipment_settlements.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('settlement_id', 'receipt_id', 'component', name='uq_settlement_application')
    )
    op.create_index(op.f('ix_ark_settlement_applications_receipt_id'), 'ark_settlement_applications', ['receipt_id'], unique=False)
    op.create_index(op.f('ix_ark_settlement_applications_settlement_id'), 'ark_settlement_applications', ['settlement_id'], unique=False)
    op.create_table('ark_shipment_outbounds',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('settlement_id', sa.BigInteger(), nullable=False),
    sa.Column('invoice_id', sa.BigInteger(), nullable=False),
    sa.Column('outbound_no', sa.String(length=96), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('remote_id', sa.String(length=64), nullable=True),
    sa.Column('attempt_token', sa.String(length=64), nullable=True),
    sa.Column('lease_until', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], ),
    sa.ForeignKeyConstraint(['settlement_id'], ['ark_shipment_settlements.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('outbound_no'),
    sa.UniqueConstraint('remote_id'),
    sa.UniqueConstraint('settlement_id')
    )
    op.create_index(op.f('ix_ark_shipment_outbounds_status'), 'ark_shipment_outbounds', ['status'], unique=False)
    op.create_table('ark_settlement_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('settlement_id', sa.BigInteger(), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['settlement_id'], ['ark_shipment_settlements.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ark_settlement_events_settlement_id'), 'ark_settlement_events', ['settlement_id'], unique=False)
    op.add_column('ark_receipts', sa.Column('batch_id', sa.BigInteger(), nullable=True))
    op.add_column('ark_receipts', sa.Column('receivable_id', sa.BigInteger(), nullable=True))
    op.add_column('ark_receipts', sa.Column('purpose', sa.String(24), server_default='ordinary', nullable=False))
    op.create_foreign_key('fk_receipt_batch', 'ark_receipts', 'ark_receipt_batches', ['batch_id'], ['id'])
    op.create_foreign_key('fk_receipt_receivable', 'ark_receipts', 'ark_receivables', ['receivable_id'], ['id'])
    op.create_index('ix_ark_receipts_batch_id', 'ark_receipts', ['batch_id'])
    op.create_index('ix_ark_receipts_receivable_id', 'ark_receipts', ['receivable_id'])
    op.create_unique_constraint('uq_receipt_batch_target', 'ark_receipts', ['batch_id', 'receivable_id'])
    op.alter_column('ark_receipts', 'xiaoman_order_id', existing_type=sa.String(64), nullable=True)


def downgrade():
    raise RuntimeError('Presale ledgers contain financial facts; disable new writes and reconcile, do not drop data.')
