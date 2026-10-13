"""Persist unit deliveries and receipt allocation evidence. No historical guessing."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "186_domestic_delivery"
down_revision = "185_announcement_push_option"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ark_domestic_customer_requests", sa.Column("receipt_date", sa.Date(), nullable=True, comment="实际收款日期，北京时间业务日期"))
    op.add_column("ark_domestic_customer_requests", sa.Column("payload_hash", sa.String(64), nullable=True, comment="收款内容指纹"))
    with op.batch_alter_table("ark_domestic_customer_requests") as batch:
        batch.drop_constraint("ck_dom_request_type", type_="check")
        batch.create_check_constraint("ck_dom_request_type", "request_type IN ('recharge', 'adjust', 'receipt')")
    op.create_table("ark_domestic_shipments",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("shipment_no", sa.String(40), nullable=False, unique=True, comment="发货批次号"),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("ark_domestic_customers.id"), nullable=False, comment="客户ID"),
        sa.Column("ship_time", sa.DateTime(), nullable=False, comment="实际发货时间，北京时间"),
        sa.Column("received_date", sa.Date(), nullable=True, comment="客户确认收货日期"),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False, comment="批次货款合计"),
        sa.Column("remark", sa.String(500), nullable=True, comment="说明"),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True, comment="来源申请ID或客户端幂等键"),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="发货内容指纹"),
        sa.Column("created_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=False, comment="经办人ID"),
        sa.Column("received_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=True, comment="收货登记人ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间，北京时间"),
        sa.Column("received_at", sa.DateTime(), nullable=True, comment="收货登记时间，北京时间"),
        sa.CheckConstraint('total_amount >= 0', name="ck_dom_shipment_amount"),
    )
    op.create_index("ix_ark_domestic_shipments_customer_id", "ark_domestic_shipments", ['customer_id'], unique=False)
    op.create_table("ark_domestic_shipment_lines",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("shipment_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_shipments.id"), nullable=False, comment="发货批次ID"),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("ark_domestic_order_items.id"), nullable=False, comment="订单明细ID"),
        sa.Column("order_no", sa.String(64), nullable=False, comment="客户订单号快照"),
        sa.Column("domestic_no", sa.String(32), nullable=False, comment="系统订单号快照"),
        sa.Column("line_code", sa.String(24), nullable=False, comment="订单明细序号快照"),
        sa.Column("guest_name", sa.String(120), nullable=True, comment="顾客名称快照"),
        sa.Column("product_name", sa.String(255), nullable=False, comment="产品名称快照"),
        sa.Column("attrs_snapshot", sa.JSON(), nullable=True, comment="交付时规格快照"),
        sa.Column("quantity", sa.Integer(), nullable=False, comment="本批发货数量"),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False, comment="交付时成交单价"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, comment="货款或核销金额"),
        sa.Column("ship_weight", sa.Numeric(10, 2), nullable=True, comment="发货克重"),
        sa.UniqueConstraint('shipment_id', 'item_id', name="uq_dom_shipment_item"),
        sa.CheckConstraint('quantity > 0 AND unit_price >= 0 AND amount >= 0', name="ck_dom_ship_line_amount"),
    )
    op.create_index("ix_ark_domestic_shipment_lines_item_id", "ark_domestic_shipment_lines", ['item_id'], unique=False)
    op.create_index("ix_ark_domestic_shipment_lines_shipment_id", "ark_domestic_shipment_lines", ['shipment_id'], unique=False)
    op.create_table("ark_domestic_shipment_units",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("line_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_shipment_lines.id"), nullable=False, comment="批次明细ID"),
        sa.Column("unit_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_item_units.id"), nullable=False, unique=True, comment="已交付具体件ID"),
    )
    op.create_index("ix_ark_domestic_shipment_units_line_id", "ark_domestic_shipment_units", ['line_id'], unique=False)
    op.create_table("ark_domestic_receipt_allocations",
        sa.Column("id", sa.BigInteger(), nullable=False, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_customer_requests.id"), nullable=False, comment="来源申请ID或客户端幂等键"),
        sa.Column("shipment_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_shipments.id"), nullable=False, comment="发货批次ID"),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, comment="货款或核销金额"),
        sa.CheckConstraint('amount > 0', name="ck_dom_receipt_allocation_amount"),
        sa.Column("ledger_id", sa.BigInteger(), sa.ForeignKey("ark_domestic_customer_ledger.id"), nullable=True, comment="已入账证据"),
        sa.Column("business_key", sa.String(128), nullable=False, unique=True, comment="核销增量幂等键"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="核销分配时间，北京时间"),
        sa.Column("created_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=False, comment="核销经办人"),
    )
    op.create_index("ix_ark_domestic_receipt_allocations_shipment_id", "ark_domestic_receipt_allocations", ['shipment_id'], unique=False)
    op.create_index("ix_ark_domestic_receipt_allocations_request_id", "ark_domestic_receipt_allocations", ['request_id'], unique=False)


def downgrade():
    raise RuntimeError("Delivery and receipt evidence must be retained; use a forward migration")
