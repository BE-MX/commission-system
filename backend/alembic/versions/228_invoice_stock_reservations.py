"""Local invoice identities and inventory reservation ownership.

Revision ID: 228_invoice_stock_reservations
Revises: 227_local_commerce
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "228_invoice_stock_reservations"
down_revision = "227_local_commerce"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ark_invoice_items", "model", existing_type=sa.String(128), type_=sa.String(200),
                    existing_nullable=True, existing_comment="production model; optional for custom lines")
    op.add_column("ark_invoices", sa.Column("transaction_mode", sa.String(16), nullable=False,
                  server_default="legacy", comment="交易事实来源 legacy/local；历史单须核对后承接"))
    op.add_column("ark_invoices", sa.Column("commerce_status", sa.String(24), nullable=False,
                  server_default="draft", comment="本地交易状态 draft/confirmed/cancelled/closed，与远端同步状态分离"))
    op.add_column("ark_invoices", sa.Column("commerce_version", sa.Integer(), nullable=False,
                  server_default="0", comment="本地订单乐观并发版本"))
    op.add_column("ark_invoices", sa.Column("local_customer_id", sa.BigInteger(), nullable=True,
                  comment="本地稳定客户ID；保留历史外部客户编号"))
    op.create_index("ix_ark_invoices_local_customer_id", "ark_invoices", ["local_customer_id"])
    op.create_foreign_key("fk_invoice_local_customer", "ark_invoices", "ark_customer_accounts",
                         ["local_customer_id"], ["id"], ondelete="RESTRICT")
    op.add_column("ark_invoice_items", sa.Column("local_sku_id", sa.BigInteger(), nullable=True,
                  comment="本地SKU ID；与旧外部SKU编号分离"))
    op.add_column("ark_invoice_items", sa.Column("stock_reserved_quantity", sa.Integer(), nullable=False,
                  server_default="0", comment="跨仓当前预占件数；与库存流水同事务更新"))
    op.add_column("ark_invoice_items", sa.Column("stock_shipped_quantity", sa.Integer(), nullable=False,
                  server_default="0", comment="跨仓累计正式出库件数；退货不自动恢复需求"))
    op.create_check_constraint("ck_invoice_stock_quantities", "ark_invoice_items",
                               "stock_reserved_quantity >= 0 AND stock_shipped_quantity >= 0")
    op.create_index("ix_ark_invoice_items_local_sku_id", "ark_invoice_items", ["local_sku_id"])
    op.create_foreign_key("fk_invoice_item_local_sku", "ark_invoice_items", "ark_catalog_skus",
                         ["local_sku_id"], ["id"], ondelete="RESTRICT")
    op.create_table("ark_stock_reservations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="本地主键"),
        sa.Column("invoice_item_id", sa.BigInteger(), sa.ForeignKey("ark_invoice_items.id", ondelete="RESTRICT"), nullable=False, comment="销售订单明细ID"),
        sa.Column("warehouse_id", sa.BigInteger(), sa.ForeignKey("ark_warehouses.id", ondelete="RESTRICT"), nullable=False, comment="预占仓库ID"),
        sa.Column("sku_id", sa.BigInteger(), sa.ForeignKey("ark_catalog_skus.id", ondelete="RESTRICT"), nullable=False, comment="不可变本地SKU ID"),
        sa.Column("reserved", sa.Integer(), nullable=False, comment="当前未出库预占件数"),
        sa.Column("shipped", sa.Integer(), nullable=False, comment="累计已正式出库件数；退货不自动增加订单需求"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间（北京时间）"),
        sa.UniqueConstraint("invoice_item_id", "warehouse_id", name="uq_stock_reservation_line_warehouse"),
        sa.CheckConstraint("reserved >= 0 AND shipped >= 0", name="ck_stock_reservation_nonnegative"),
    )
    op.create_table("ark_invoice_commerce_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="本地主键"),
        sa.Column("invoice_id", sa.BigInteger(), sa.ForeignKey("ark_invoices.id", ondelete="RESTRICT"), nullable=True, comment="订单ID；创建事务内认领时暂为空"),
        sa.Column("request_key", sa.String(128), nullable=False, unique=True, comment="本地订单命令幂等键"),
        sa.Column("request_hash", sa.String(64), nullable=False, comment="请求SHA256"),
        sa.Column("action", sa.String(32), nullable=False, comment="本地订单动作"),
        sa.Column("payload", sa.JSON(), nullable=False, comment="命令快照及变更依据"),
        sa.Column("created_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=True, comment="操作人ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（北京时间）"),
    )
    op.create_index("ix_ark_invoice_commerce_events_invoice_id", "ark_invoice_commerce_events", ["invoice_id"])


def downgrade():
    raise RuntimeError("库存责任记录不允许自动删除；回退应保留业务事实并走修复迁移")
