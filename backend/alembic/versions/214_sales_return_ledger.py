"""Local sales returns and frozen economic effects; remote mirrors remain read-only."""
from alembic import op
import sqlalchemy as sa

revision = "214_sales_return_ledger"
down_revision = "213_salary_snap_export_cols"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('ark_sales_returns'):
        op.create_table('ark_sales_returns',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_no', sa.String(length=64), nullable=False, comment='退货单号'),
        sa.Column('order_id', sa.String(length=64), nullable=False, comment='原小满订单 ID'),
        sa.Column('order_no', sa.String(length=128), nullable=False, comment='原订单号快照'),
        sa.Column('invoice_id', sa.BigInteger(), nullable=True, comment='可选关联方舟发票 ID'),
        sa.Column('customer_id', sa.String(length=64), nullable=False, comment='原客户 ID'),
        sa.Column('customer_name', sa.String(length=256), nullable=False, comment='原客户名称快照'),
        sa.Column('owner_okki_user_id', sa.String(length=64), nullable=False, comment='原订单业务员 OKKI ID'),
        sa.Column('sales_user_id', sa.Integer(), nullable=True, comment='方舟业务员 ID 快照'),
        sa.Column('return_type', sa.String(length=24), nullable=False, comment='退货退款或仅退款'),
        sa.Column('currency', sa.String(length=16), nullable=False, comment='订单原币'),
        sa.Column('reduction_amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='商品货款冲减原币金额'),
        sa.Column('refund_amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='实际退款原币金额'),
        sa.Column('waived_amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='未收款减免原币金额'),
        sa.Column('reason_code', sa.String(length=32), nullable=False, comment='原因字典编码'),
        sa.Column('reason', sa.Text(), nullable=False, comment='原因说明'),
        sa.Column('status', sa.String(length=16), nullable=False, comment='退货业务状态'),
        sa.Column('cash_status', sa.String(length=16), nullable=False, comment='实际资金执行状态'),
        sa.Column('cash_evidence', sa.JSON(), nullable=False, comment='资金支付及收回证据'),
        sa.Column('snapshot', sa.JSON(), nullable=False, comment='原单与资金冻结证据'),
        sa.Column('request_key', sa.String(length=64), nullable=False, comment='提交幂等键'),
        sa.Column('request_hash', sa.String(length=64), nullable=False, comment='提交内容摘要'),
        sa.Column('activate_key', sa.String(length=64), nullable=True, comment='生效幂等键'),
        sa.Column('activate_hash', sa.String(length=64), nullable=True, comment='生效提交内容摘要'),
        sa.Column('reverse_key', sa.String(length=64), nullable=True, comment='反向更正幂等键'),
        sa.Column('version', sa.Integer(), nullable=False, comment='乐观并发版本'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='创建人方舟 ID'),
        sa.Column('activated_by', sa.Integer(), nullable=True, comment='生效操作人方舟 ID'),
        sa.Column('effective_date', sa.Date(), nullable=True, comment='生效业务日，北京时间'),
        sa.Column('effective_at', sa.DateTime(), nullable=True, comment='生效时间，北京时间'),
        sa.Column('reversed_at', sa.DateTime(), nullable=True, comment='反向更正时间，北京时间'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间，北京时间'),
        sa.ForeignKeyConstraint(['invoice_id'], ['ark_invoices.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('activate_key'),
        sa.UniqueConstraint('request_key'),
        sa.UniqueConstraint('return_no'),
        sa.UniqueConstraint('reverse_key')
        )
        op.create_index(op.f('ix_ark_sales_returns_customer_id'), 'ark_sales_returns', ['customer_id'], unique=False)
        op.create_index(op.f('ix_ark_sales_returns_effective_date'), 'ark_sales_returns', ['effective_date'], unique=False)
        op.create_index(op.f('ix_ark_sales_returns_order_id'), 'ark_sales_returns', ['order_id'], unique=False)
        op.create_index(op.f('ix_ark_sales_returns_owner_okki_user_id'), 'ark_sales_returns', ['owner_okki_user_id'], unique=False)
        op.create_index(op.f('ix_ark_sales_returns_status'), 'ark_sales_returns', ['status'], unique=False)
    if not inspector.has_table('ark_sales_return_order_guards'):
        op.create_table('ark_sales_return_order_guards',
        sa.Column('order_id', sa.String(length=64), nullable=False, comment='原小满订单 ID'),
        sa.Column('version', sa.Integer(), nullable=False, comment='乐观并发版本'),
        sa.PrimaryKeyConstraint('order_id')
        )
    if not inspector.has_table('ark_sales_return_items'):
        op.create_table('ark_sales_return_items',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_id', sa.BigInteger(), nullable=False, comment='关联退货单 ID'),
        sa.Column('source_key', sa.String(length=160), nullable=False, comment='原出库行稳定身份'),
        sa.Column('outbound_id', sa.String(length=64), nullable=False, comment='原出库单 ID'),
        sa.Column('outbound_line_id', sa.String(length=64), nullable=False, comment='原出库明细 ID'),
        sa.Column('order_line_id', sa.String(length=64), nullable=False, comment='原订单明细 ID'),
        sa.Column('product_id', sa.String(length=64), nullable=False, comment='原产品 ID'),
        sa.Column('sku_id', sa.String(length=64), nullable=False, comment='原 SKU ID'),
        sa.Column('product_name', sa.String(length=256), nullable=False, comment='产品名称快照'),
        sa.Column('specification', sa.String(length=500), nullable=False, comment='产品规格快照'),
        sa.Column('quantity', sa.Integer(), nullable=False, comment='本次计划或实收数量'),
        sa.Column('reduction_amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='商品货款冲减原币金额'),
        sa.Column('reduction_usd', sa.Numeric(precision=14, scale=2), nullable=False, comment='商品货款冲减美元金额'),
        sa.Column('source_snapshot', sa.JSON(), nullable=False, comment='原出库行冻结证据'),
        sa.ForeignKeyConstraint(['return_id'], ['ark_sales_returns.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('return_id', 'source_key', name='uq_sales_return_source_line')
        )
        op.create_index(op.f('ix_ark_sales_return_items_return_id'), 'ark_sales_return_items', ['return_id'], unique=False)
    if not inspector.has_table('ark_return_receipts'):
        op.create_table('ark_return_receipts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_id', sa.BigInteger(), nullable=False, comment='关联退货单 ID'),
        sa.Column('receipt_no', sa.String(length=64), nullable=False, comment='本地负数回款单号'),
        sa.Column('effect_kind', sa.String(length=16), nullable=False, comment='生效或冲销事实类型'),
        sa.Column('original_receipt_id', sa.BigInteger(), nullable=True, comment='关联原本地负数回款 ID'),
        sa.Column('order_id', sa.String(length=64), nullable=False, comment='原小满订单 ID'),
        sa.Column('customer_id', sa.String(length=64), nullable=False, comment='原客户 ID'),
        sa.Column('currency', sa.String(length=16), nullable=False, comment='订单原币'),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='原币有符号金额'),
        sa.Column('amount_usd', sa.Numeric(precision=14, scale=2), nullable=False, comment='美元有符号金额'),
        sa.Column('collection_date', sa.Date(), nullable=False, comment='回款业务日期，北京时间'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='创建人方舟 ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.ForeignKeyConstraint(['original_receipt_id'], ['ark_return_receipts.id'], ),
        sa.ForeignKeyConstraint(['return_id'], ['ark_sales_returns.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('receipt_no'),
        sa.UniqueConstraint('return_id', 'effect_kind', name='uq_return_receipt_effect')
        )
        op.create_index(op.f('ix_ark_return_receipts_collection_date'), 'ark_return_receipts', ['collection_date'], unique=False)
        op.create_index(op.f('ix_ark_return_receipts_customer_id'), 'ark_return_receipts', ['customer_id'], unique=False)
        op.create_index(op.f('ix_ark_return_receipts_order_id'), 'ark_return_receipts', ['order_id'], unique=False)
        op.create_index(op.f('ix_ark_return_receipts_return_id'), 'ark_return_receipts', ['return_id'], unique=False)
    if not inspector.has_table('ark_sales_return_allocations'):
        op.create_table('ark_sales_return_allocations',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_id', sa.BigInteger(), nullable=False, comment='关联退货单 ID'),
        sa.Column('original_payment_id', sa.String(length=64), nullable=False, comment='原回款稳定业务 ID'),
        sa.Column('original_principal', sa.Numeric(precision=14, scale=2), nullable=False, comment='原可退款本金原币金额'),
        sa.Column('original_principal_usd', sa.Numeric(precision=14, scale=2), nullable=False, comment='原可退款本金美元金额'),
        sa.Column('refund_amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='实际退款原币金额'),
        sa.Column('refund_amount_usd', sa.Numeric(precision=14, scale=2), nullable=False, comment='本次实际退款美元本金'),
        sa.Column('basis', sa.JSON(), nullable=False, comment='原人员及实际提成依据快照'),
        sa.Column('funding', sa.JSON(), nullable=False, comment='原回款和预售批次资金分摊'),
        sa.ForeignKeyConstraint(['return_id'], ['ark_sales_returns.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('return_id', 'original_payment_id', name='uq_return_original_payment')
        )
        op.create_index(op.f('ix_ark_sales_return_allocations_original_payment_id'), 'ark_sales_return_allocations', ['original_payment_id'], unique=False)
        op.create_index(op.f('ix_ark_sales_return_allocations_return_id'), 'ark_sales_return_allocations', ['return_id'], unique=False)
    if not inspector.has_table('ark_sales_return_effects'):
        op.create_table('ark_sales_return_effects',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_id', sa.BigInteger(), nullable=False, comment='关联退货单 ID'),
        sa.Column('effect_kind', sa.String(length=16), nullable=False, comment='生效或冲销事实类型'),
        sa.Column('order_id', sa.String(length=64), nullable=False, comment='原小满订单 ID'),
        sa.Column('owner_okki_user_id', sa.String(length=64), nullable=False, comment='原订单业务员 OKKI ID'),
        sa.Column('customer_id', sa.String(length=64), nullable=False, comment='原客户 ID'),
        sa.Column('currency', sa.String(length=16), nullable=False, comment='订单原币'),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False, comment='原币有符号金额'),
        sa.Column('amount_usd', sa.Numeric(precision=14, scale=2), nullable=False, comment='美元有符号金额'),
        sa.Column('effective_date', sa.Date(), nullable=False, comment='生效业务日，北京时间'),
        sa.Column('gmv_eligible', sa.Integer(), nullable=False, comment='原 GMV 计入资格'),
        sa.Column('order_role', sa.String(length=24), nullable=False, comment='原新签或复购分类'),
        sa.Column('departments', sa.JSON(), nullable=False, comment='原部门及分摊比例快照'),
        sa.Column('snapshot', sa.JSON(), nullable=False, comment='原单与资金冻结证据'),
        sa.ForeignKeyConstraint(['return_id'], ['ark_sales_returns.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('return_id', 'effect_kind', name='uq_sales_return_effect')
        )
        op.create_index(op.f('ix_ark_sales_return_effects_effective_date'), 'ark_sales_return_effects', ['effective_date'], unique=False)
        op.create_index(op.f('ix_ark_sales_return_effects_order_id'), 'ark_sales_return_effects', ['order_id'], unique=False)
        op.create_index(op.f('ix_ark_sales_return_effects_owner_okki_user_id'), 'ark_sales_return_effects', ['owner_okki_user_id'], unique=False)
        op.create_index(op.f('ix_ark_sales_return_effects_return_id'), 'ark_sales_return_effects', ['return_id'], unique=False)
    if not inspector.has_table('ark_sales_return_receivings'):
        op.create_table('ark_sales_return_receivings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_id', sa.BigInteger(), nullable=False, comment='关联退货单 ID'),
        sa.Column('item_id', sa.BigInteger(), nullable=False, comment='关联退货产品明细 ID'),
        sa.Column('quantity', sa.Integer(), nullable=False, comment='本次计划或实收数量'),
        sa.Column('accepted_quantity', sa.Integer(), nullable=False, comment='实收检验合格件数'),
        sa.Column('rejected_quantity', sa.Integer(), nullable=False, comment='实收检验不合格件数'),
        sa.Column('pending_quantity', sa.Integer(), nullable=False, comment='实收待检件数'),
        sa.Column('stock_status', sa.String(length=24), nullable=False, comment='权威库存入账核验状态'),
        sa.Column('stock_reference', sa.String(length=128), nullable=True, comment='权威入库单引用'),
        sa.Column('version', sa.Integer(), nullable=False, comment='收货检验乐观并发版本'),
        sa.Column('evidence', sa.JSON(), nullable=False, comment='收货检验及入库证据'),
        sa.Column('request_key', sa.String(length=64), nullable=False, comment='提交幂等键'),
        sa.Column('request_hash', sa.String(length=64), nullable=False, comment='提交内容摘要'),
        sa.Column('created_by', sa.Integer(), nullable=False, comment='创建人方舟 ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.ForeignKeyConstraint(['item_id'], ['ark_sales_return_items.id'], ),
        sa.ForeignKeyConstraint(['return_id'], ['ark_sales_returns.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_key', name='uq_return_receiving_request')
        )
        op.create_index(op.f('ix_ark_sales_return_receivings_return_id'), 'ark_sales_return_receivings', ['return_id'], unique=False)
    if not inspector.has_table('ark_sales_return_events'):
        op.create_table('ark_sales_return_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键'),
        sa.Column('return_id', sa.BigInteger(), nullable=False, comment='关联退货单 ID'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='审计动作编码'),
        sa.Column('actor_id', sa.Integer(), nullable=False, comment='操作人方舟 ID'),
        sa.Column('data', sa.JSON(), nullable=False, comment='审计摘要'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间，北京时间'),
        sa.ForeignKeyConstraint(['return_id'], ['ark_sales_returns.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_ark_sales_return_events_return_id'), 'ark_sales_return_events', ['return_id'], unique=False)
    if "source" not in {column["name"] for column in inspector.get_columns("synced_payment")}:
        op.add_column("synced_payment", sa.Column("source", sa.String(24), nullable=False, server_default="okki", comment="回款来源：okki 或 ark_return"))


def downgrade():
    raise RuntimeError("Sales return financial history is append-only; downgrade requires an audited recovery plan")
