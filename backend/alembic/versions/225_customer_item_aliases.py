"""Retain collapsed historical rows while analysing actual sales line projections."""
from alembic import op
import sqlalchemy as sa

revision = '225_customer_item_aliases'
down_revision = '224_commerce_order_bindings'
branch_labels = None
depends_on = None


def upgrade():
    # Match the existing catalog/invoice display boundary throughout analytics;
    # widening preserves prior values and avoids strict-MySQL truncation.
    for table, column in [('ark_customer_order_items', 'product_family'),
            ('ark_customer_order_batch_map', 'product_family'),
            ('ark_customer_reorder_windows', 'product_family'),
            ('ark_customer_list_projections', 'primary_product_family')]:
        original = next(row for row in sa.inspect(op.get_bind()).get_columns(table) if row['name'] == column)
        op.alter_column(table, column, existing_type=sa.String(128), type_=sa.String(256),
            existing_nullable=original['nullable'], existing_comment=original.get('comment'))
    op.add_column('ark_customer_order_items', sa.Column('projection_role', sa.String(24),
        nullable=False, server_default='active', comment='活动真实明细或保留原身份的历史聚合别名'))
    op.add_column('ark_customer_order_items', sa.Column('historical_alias_id', sa.BigInteger(),
        nullable=True, comment='真实明细所对应的已核验原聚合行，保留旧媒体与审计引用'))
    op.create_foreign_key('fk_customer_item_historical_alias', 'ark_customer_order_items',
        'ark_customer_order_items', ['historical_alias_id'], ['id'], ondelete='RESTRICT')
    op.create_check_constraint('ck_customer_item_projection_role', 'ark_customer_order_items',
        "projection_role IN ('active', 'historical_alias') AND "
        "(projection_role <> 'historical_alias' OR (historical_alias_id IS NULL AND local_invoice_item_id IS NULL))")


def downgrade():
    raise RuntimeError('Do not delete historical aliases or active sales identities; recover forward')
