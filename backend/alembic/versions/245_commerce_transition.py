"""Persistent dual-route ownership, observation and isolated comparison contracts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '245_commerce_transition'
down_revision = '244_customer_item_aliases'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ark_commerce_bank_domains',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Closed collection subject/account/channel domain'),
        sa.Column('subject_key', sa.String(length=96).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=96), "mysql"), nullable=False, comment='Receiving legal subject identity'),
        sa.Column('account_key', sa.String(length=96).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=96), "mysql"), nullable=False, comment='Stable account identity, no raw account secret'),
        sa.Column('channel', sa.String(length=64).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=64), "mysql"), nullable=False, comment='Verified transaction identity channel'),
        sa.Column('legacy_identity_complete', sa.Boolean(), nullable=False, comment='All legacy, unallocated and remote entries reconciled', server_default=sa.text('0')),
        sa.Column('enforced', sa.Boolean(), nullable=False, comment='All entry writers constrained or revoked', server_default=sa.text('0')),
        sa.Column('exclusive_route', sa.String(length=16), nullable=True, comment='Optional whole domain exclusion'),
        sa.Column('evidence', sa.JSON(), nullable=False, comment='Account inventory, completeness and enforcement receipts'),
        sa.Column('version', sa.Integer(), nullable=False, comment='Domain coordination version', server_default=sa.text('1')),
        sa.UniqueConstraint('subject_key', 'account_key', 'channel', name='uq_transition_bank_domain'),
    )
    op.create_table('ark_commerce_invoice_authorities',
        sa.Column('invoice_id', sa.BigInteger(), nullable=False, primary_key=True, comment='Only formal invoice identity'),
        sa.Column('route', sa.String(length=16), nullable=False, comment='legacy/local formal owner'),
        sa.Column('epoch', sa.Integer(), nullable=False, comment='Authority generation', server_default=sa.text('1')),
        sa.Column('lock_version', sa.Integer(), nullable=False, comment='CAS lock shared by sending and transfer', server_default=sa.text('1')),
        sa.Column('status', sa.String(length=16), nullable=False, comment='active/frozen', server_default='active'),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True, comment='Beijing route finalization time'),
        sa.Column('source_evidence', sa.JSON(), nullable=False, comment='Explicit historical source or new draft evidence'),
        sa.Column('settled_evidence', sa.JSON(), nullable=True, comment='Verified complete economic closure, never inferred from invoice status'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing creation time'),
        sa.CheckConstraint('epoch > 0', name='ck_transition_authority_epoch'),
        sa.CheckConstraint("route IN ('legacy','local')", name='ck_transition_authority_route'),
        sa.CheckConstraint("status IN ('active','frozen')", name='ck_transition_authority_state'),
        sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], name='fk_ct_invoice_authorities_invoice_id', ondelete='RESTRICT'),
    )
    op.create_table('ark_commerce_resource_scopes',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Exclusive physical responsibility scope'),
        sa.Column('resource_kind', sa.String(length=24), nullable=False, comment='sku/material/production'),
        sa.Column('resource_key', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, comment='Stable physical SKU or material identity'),
        sa.Column('warehouse_key', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, comment='Warehouse bucket or * for all physical stock'),
        sa.Column('route', sa.String(length=16), nullable=False, comment='Only formal route allowed to use the scope'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='active/frozen', server_default='active'),
        sa.Column('evidence', sa.JSON(), nullable=False, comment='Count checkpoint, old responsibility closure and writer exclusion'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing scope time'),
        sa.UniqueConstraint('resource_kind', 'resource_key', 'warehouse_key', name='uq_transition_resource_scope'),
    )
    op.create_table('ark_commerce_responsibility_groups',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Shared payment, production or commission responsibility'),
        sa.Column('kind', sa.String(length=24), nullable=False, comment='payment/production/reservation/commission'),
        sa.Column('responsibility_key', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, comment='Original stable consumed economic identity'),
        sa.Column('complete', sa.Boolean(), nullable=False, comment='Full related object set verified', server_default=sa.text('0')),
        sa.Column('evidence', sa.JSON(), nullable=False, comment='Original relationship inventory and checkpoint'),
        sa.UniqueConstraint('kind', 'responsibility_key', name='uq_transition_responsibility'),
    )
    op.create_table('ark_commerce_shadow_binding',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('dataset_id', sa.String(length=64), nullable=False),
        sa.Column('checkpoint_hash', sa.String(length=64), nullable=False),
        sa.UniqueConstraint('dataset_id', name=None),
    )
    op.create_table('ark_commerce_shadow_datasets',
        sa.Column('id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('checkpoint', sa.JSON(), nullable=False),
        sa.Column('checkpoint_hash', sa.String(length=64), nullable=False),
        sa.Column('target_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table('ark_commerce_shadow_differences',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('observation_id', sa.BigInteger(), nullable=False),
        sa.Column('invoice_id', sa.BigInteger(), nullable=True),
        sa.Column('local_customer_id', sa.BigInteger(), nullable=True),
        sa.Column('payment_id', sa.BigInteger(), nullable=True),
        sa.Column('field', sa.String(length=128), nullable=False),
        sa.Column('expected', sa.JSON(), nullable=False),
        sa.Column('actual', sa.JSON(), nullable=False),
        sa.Column('classification', sa.String(length=24), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ark_commerce_shadow_differences_invoice_id', 'ark_commerce_shadow_differences', ['invoice_id'], unique=False)
    op.create_index('ix_ark_commerce_shadow_differences_local_customer_id', 'ark_commerce_shadow_differences', ['local_customer_id'], unique=False)
    op.create_index('ix_ark_commerce_shadow_differences_payment_id', 'ark_commerce_shadow_differences', ['payment_id'], unique=False)
    op.create_index('ix_ark_commerce_shadow_differences_run_id', 'ark_commerce_shadow_differences', ['run_id'], unique=False)
    op.create_table('ark_commerce_shadow_executions',
        sa.Column('id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('dataset_id', sa.String(length=64), nullable=False),
        sa.Column('first_run_id', sa.String(length=64), nullable=False),
        sa.Column('source_event_id', sa.String(length=128), nullable=False),
        sa.Column('aggregate_key', sa.String(length=128), nullable=False),
        sa.Column('causal_version', sa.Integer(), nullable=False),
        sa.Column('contract_revision', sa.Integer(), nullable=False),
        sa.Column('authority_epoch', sa.Integer(), nullable=False),
        sa.Column('input_hash', sa.String(length=64), nullable=False),
        sa.Column('outcome', sa.String(length=24), nullable=False),
        sa.Column('actual', sa.JSON(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('dataset_id', 'source_event_id', name='uq_shadow_execution_source'),
    )
    op.create_table('ark_commerce_shadow_observations',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('source_event_id', sa.String(length=128), nullable=False),
        sa.Column('invoice_id', sa.BigInteger(), nullable=True),
        sa.Column('local_customer_id', sa.BigInteger(), nullable=True),
        sa.Column('payment_id', sa.BigInteger(), nullable=True),
        sa.Column('aggregate_key', sa.String(length=128), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('request_key', sa.String(length=128), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('contract_revision', sa.Integer(), nullable=False),
        sa.Column('causal_version', sa.Integer(), nullable=False),
        sa.Column('authority_epoch', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.BigInteger(), nullable=False),
        sa.Column('outcome', sa.String(length=16), nullable=False),
        sa.Column('reason_code', sa.String(length=160), nullable=True),
        sa.Column('resolves_source_event_id', sa.String(length=128), nullable=True),
        sa.Column('resolution_evidence', sa.JSON(), nullable=True),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('dependencies', sa.JSON(), nullable=False),
        sa.Column('observed_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('resolves_source_event_id', name=None),
        sa.UniqueConstraint('source_event_id', name=None),
        sa.UniqueConstraint('aggregate_key', 'request_key', name='uq_shadow_observation_request'),
    )
    op.create_index('ix_ark_commerce_shadow_observations_aggregate_key', 'ark_commerce_shadow_observations', ['aggregate_key'], unique=False)
    op.create_index('ix_ark_commerce_shadow_observations_invoice_id', 'ark_commerce_shadow_observations', ['invoice_id'], unique=False)
    op.create_index('ix_ark_commerce_shadow_observations_local_customer_id', 'ark_commerce_shadow_observations', ['local_customer_id'], unique=False)
    op.create_index('ix_ark_commerce_shadow_observations_payment_id', 'ark_commerce_shadow_observations', ['payment_id'], unique=False)
    op.create_table('ark_commerce_shadow_outbox',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('observation_id', sa.BigInteger(), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_error', sa.String(length=128), nullable=True),
        sa.Column('exported_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('observation_id', name=None),
    )
    op.create_index('ix_ark_commerce_shadow_outbox_state', 'ark_commerce_shadow_outbox', ['state'], unique=False)
    op.create_table('ark_commerce_shadow_results',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('observation_id', sa.BigInteger(), nullable=False),
        sa.Column('execution_event_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('candidate_outcome', sa.String(length=24), nullable=False),
        sa.Column('actual', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('run_id', 'observation_id', name='uq_shadow_result_sample'),
    )
    op.create_index('ix_ark_commerce_shadow_results_run_id', 'ark_commerce_shadow_results', ['run_id'], unique=False)
    op.create_table('ark_commerce_shadow_reviews',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column('difference_id', sa.BigInteger(), nullable=False),
        sa.Column('actor_id', sa.BigInteger(), nullable=False),
        sa.Column('classification', sa.String(length=24), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_ark_commerce_shadow_reviews_difference_id', 'ark_commerce_shadow_reviews', ['difference_id'], unique=False)
    op.create_table('ark_commerce_shadow_runs',
        sa.Column('id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('dataset_id', sa.String(length=64), nullable=False),
        sa.Column('request_key', sa.String(length=128), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('calculator_version', sa.String(length=64), nullable=False),
        sa.Column('invoice_ids', sa.JSON(), nullable=False),
        sa.Column('payment_ids', sa.JSON(), nullable=False),
        sa.Column('local_customer_ids', sa.JSON(), nullable=False),
        sa.Column('through_observation_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='queued'),
        sa.Column('coverage', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('request_key', name=None),
    )
    op.create_index('ix_ark_commerce_shadow_runs_dataset_id', 'ark_commerce_shadow_runs', ['dataset_id'], unique=False)
    op.create_index('ix_ark_commerce_shadow_runs_status', 'ark_commerce_shadow_runs', ['status'], unique=False)
    op.create_table('ark_commerce_transfer_preparations',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Recoverable frozen responsibility closure transfer'),
        sa.Column('request_key', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, comment='Stable transfer preparation identity'),
        sa.Column('source_route', sa.String(length=16), nullable=False, comment='Original ownership'),
        sa.Column('target_route', sa.String(length=16), nullable=False, comment='Destination ownership'),
        sa.Column('status', sa.String(length=24), nullable=False, comment='waiting/ready/completed'),
        sa.Column('manifest_hash', sa.String(length=64), nullable=False, comment='Immutable closure and checkpoint digest'),
        sa.Column('manifest', sa.JSON(), nullable=False, comment='Invoice IDs, original epochs, responsibility closure and checkpoint'),
        sa.Column('verification', sa.JSON(), nullable=True, comment='Contract/funds/fulfillment/inventory/production/media/commission evidence'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing preparation time'),
        sa.Column('completed_at', sa.DateTime(), nullable=True, comment='Beijing atomic ownership switch time'),
        sa.UniqueConstraint('request_key', name=None),
    )
    op.create_table('ark_commerce_transition_policy',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True, autoincrement=False, comment='Singleton coordination lock, always 1'),
        sa.Column('phase', sa.String(length=24), nullable=False, comment='Installed platform phase', server_default='legacy_only'),
        sa.Column('version', sa.Integer(), nullable=False, comment='Policy optimistic version', server_default=sa.text('1')),
        sa.Column('min_writer_version', sa.Integer(), nullable=False, comment='Minimum compatible writer protocol', server_default=sa.text('1')),
        sa.Column('writer_inventory_verified', sa.Boolean(), nullable=False, comment='All writers inventoried with enforced receipts', server_default=sa.text('0')),
        sa.Column('inventory_evidence', sa.JSON(), nullable=True, comment='Writer inventory and enforcement evidence'),
        sa.Column('local_ever_effective', sa.Boolean(), nullable=False, comment='Irreversible local economic responsibility marker', server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='Beijing policy time'),
        sa.CheckConstraint("phase IN ('legacy_only','transition','local_only')", name='ck_transition_phase'),
        sa.CheckConstraint('id = 1', name='ck_transition_policy_singleton'),
    )
    op.create_table('ark_commerce_writer_receipts',
        sa.Column('writer_key', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, primary_key=True, comment='Stable worker, script or manual credential identity'),
        sa.Column('protocol_version', sa.Integer(), nullable=False, comment='Verified route and epoch protocol version'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='compatible/revoked/unknown'),
        sa.Column('evidence', sa.JSON(), nullable=False, comment='Enforcement or revocation verification receipt'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='Beijing receipt time'),
        sa.CheckConstraint("status IN ('compatible','revoked','unknown')", name='ck_transition_writer_state'),
    )
    op.create_table('ark_commerce_authority_events',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Append only authority history'),
        sa.Column('invoice_id', sa.BigInteger(), nullable=False, comment='Invoice ownership'),
        sa.Column('epoch', sa.Integer(), nullable=False, comment='Resulting generation'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='initialize/draft_route/confirm/freeze/transfer'),
        sa.Column('payload', sa.JSON(), nullable=False, comment='Evidence and original ownership'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing event time'),
        sa.ForeignKeyConstraint(['invoice_id'], ['ark_commerce_invoice_authorities.invoice_id'], name='fk_ct_authority_events_invoice_id', ondelete='RESTRICT'),
    )
    op.create_index('ix_ark_commerce_authority_events_invoice_id', 'ark_commerce_authority_events', ['invoice_id'], unique=False)
    op.create_table('ark_commerce_bank_identities',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='One real payment economic identity across routes'),
        sa.Column('domain_id', sa.BigInteger(), nullable=False, comment='Verified identity domain'),
        sa.Column('transaction_id', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, comment='Bank verified nonempty transaction identifier'),
        sa.Column('route', sa.String(length=16), nullable=False, comment='Only formal route consuming this principal'),
        sa.Column('currency', sa.String(length=16), nullable=False, comment='Original currency'),
        sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False, comment='Original immutable total principal'),
        sa.Column('payer_evidence', sa.JSON(), nullable=False, comment='Bank payer evidence, never a fabricated random key'),
        sa.Column('payment_ref', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=True, comment='One formal money ledger identity, bound in same transaction'),
        sa.Column('settled_evidence', sa.JSON(), nullable=True, comment='Verified funds and aftersales closure'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing registration time'),
        sa.CheckConstraint('amount > 0', name='ck_transition_bank_amount'),
        sa.ForeignKeyConstraint(['domain_id'], ['ark_commerce_bank_domains.id'], name='fk_ct_bank_identities_domain_id', ondelete='RESTRICT'),
        sa.UniqueConstraint('payment_ref', name=None),
        sa.UniqueConstraint('domain_id', 'transaction_id', name='uq_transition_bank_identity'),
    )
    op.create_table('ark_commerce_responsibility_members',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Shared liability relationship'),
        sa.Column('group_id', sa.BigInteger(), nullable=False, comment='Original responsibility group'),
        sa.Column('invoice_id', sa.BigInteger(), nullable=False, comment='Full affected formal invoice identity'),
        sa.Column('amount', sa.Numeric(precision=18, scale=3), nullable=True, comment='Original consumed amount or quantity; not a new available opening'),
        sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], name='fk_ct_responsibility_members_invoice_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['group_id'], ['ark_commerce_responsibility_groups.id'], name='fk_ct_responsibility_members_group_id', ondelete='RESTRICT'),
        sa.UniqueConstraint('group_id', 'invoice_id', name='uq_transition_responsibility_member'),
    )
    op.create_index('ix_ark_commerce_responsibility_members_group_id', 'ark_commerce_responsibility_members', ['group_id'], unique=False)
    op.create_index('ix_ark_commerce_responsibility_members_invoice_id', 'ark_commerce_responsibility_members', ['invoice_id'], unique=False)
    op.create_table('ark_commerce_sending_claims',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Persistent external sending responsibility'),
        sa.Column('invoice_id', sa.BigInteger(), nullable=False, comment='Original formal invoice'),
        sa.Column('request_key', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=False, comment='Stable original external request identity'),
        sa.Column('operation', sa.String(length=64), nullable=False, comment='External command type'),
        sa.Column('route', sa.String(length=16), nullable=False, comment='Original route'),
        sa.Column('epoch', sa.Integer(), nullable=False, comment='Original authority epoch'),
        sa.Column('payload_hash', sa.String(length=64), nullable=False, comment='Canonical command digest'),
        sa.Column('responsibilities', sa.JSON(), nullable=False, comment='Persistent stock and funding references'),
        sa.Column('status', sa.String(length=24), nullable=False, comment='sending/unknown/succeeded/failed/not_sent', server_default='sending'),
        sa.Column('active_invoice_key', sa.BigInteger(), nullable=True, comment='One unresolved external responsibility per invoice; terminal NULL'),
        sa.Column('external_id', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=True, comment='Original remote economic identity'),
        sa.Column('lease_until', sa.DateTime(), nullable=True, comment='Observation only; expiration never releases responsibility'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing claim time'),
        sa.Column('terminal_at', sa.DateTime(), nullable=True, comment='Beijing proven terminal result time'),
        sa.CheckConstraint("status IN ('sending','unknown','succeeded','failed','not_sent')", name='ck_transition_claim_state'),
        sa.ForeignKeyConstraint(['invoice_id'], ['ark_commerce_invoice_authorities.invoice_id'], name='fk_ct_sending_claims_invoice_id', ondelete='RESTRICT'),
        sa.UniqueConstraint('request_key', name=None),
        sa.UniqueConstraint('active_invoice_key', name=None),
    )
    op.create_index('ix_ark_commerce_sending_claims_invoice_id', 'ark_commerce_sending_claims', ['invoice_id'], unique=False)
    op.create_table('ark_commerce_claim_evidence',
        sa.Column('id', sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True, comment='Append only late and recovery evidence'),
        sa.Column('claim_id', sa.BigInteger(), nullable=False, comment='Original sending claim'),
        sa.Column('outcome', sa.String(length=24), nullable=False, comment='Observed result, including contradictions'),
        sa.Column('evidence', sa.JSON(), nullable=False, comment='Immutable callback or original-request readback'),
        sa.Column('external_id', sa.String(length=128).with_variant(mysql.VARCHAR(collation='utf8mb4_bin', length=128), "mysql"), nullable=True, comment='Observed remote identity'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='Beijing observation time'),
        sa.ForeignKeyConstraint(['claim_id'], ['ark_commerce_sending_claims.id'], name='fk_ct_claim_evidence_claim_id', ondelete='RESTRICT'),
    )
    op.create_index('ix_ark_commerce_claim_evidence_claim_id', 'ark_commerce_claim_evidence', ['claim_id'], unique=False)

    connection = op.get_bind()
    connection.exec_driver_sql("SET time_zone='+08:00'")
    invalid = connection.exec_driver_sql("SELECT COUNT(*) FROM ark_invoices WHERE transaction_mode NOT IN ('legacy','local') OR transaction_mode IS NULL").scalar_one()
    if invalid:
        raise RuntimeError("Invoice transaction provenance must be reviewed before installing authority")
    # This is the installation-time route seal, not a guessed historical approval time.
    connection.exec_driver_sql("""INSERT INTO ark_commerce_transition_policy
        (id,phase,version,min_writer_version,writer_inventory_verified,local_ever_effective,updated_at)
        SELECT 1,'legacy_only',1,1,0,EXISTS(SELECT 1 FROM ark_invoices WHERE transaction_mode='local'),NOW()""")
    connection.exec_driver_sql("""INSERT INTO ark_commerce_invoice_authorities
        (invoice_id,route,epoch,lock_version,status,confirmed_at,source_evidence,created_at)
        SELECT id,transaction_mode,1,1,'active',NOW(),
            JSON_OBJECT('origin','migration_245','source_transaction_mode',transaction_mode,'route_locked_at_install',TRUE),NOW()
        FROM ark_invoices""")


def downgrade():
    raise RuntimeError("Dual-route financial and physical responsibilities require forward recovery")
