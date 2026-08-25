"""add semifinished order and inventory domain

Revision ID: 120_semifinished
Revises: 119_invoice_screenshot_src
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "120_semifinished"
down_revision = "119_invoice_screenshot_src"
branch_labels = None
depends_on = None


QTY = sa.Numeric(14, 3)
RATIO = sa.Numeric(8, 6)
USER_ID = sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _columns(table: str) -> set[str]:
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in _inspector().get_indexes(table)}


def upgrade() -> None:
    if not _has_table("ark_semifinished_materials"):
        op.create_table(
            "ark_semifinished_materials",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("material_code", sa.String(32), nullable=False, comment="半成品编码"),
            sa.Column("size", sa.String(32), nullable=False, comment="标准化尺寸"),
            sa.Column("color_code", sa.String(128), nullable=False, comment="显示色号"),
            sa.Column("color_key", sa.String(128), nullable=False, comment="标准化色号键"),
            sa.Column("color_type", sa.String(24), nullable=False, server_default="solid", comment="solid/piano/t/named_t/compound"),
            sa.Column("safety_stock_grams", QTY, nullable=False, server_default="0", comment="安全库存g"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active", comment="active/inactive"),
            sa.Column("source", sa.String(16), nullable=False, server_default="auto", comment="auto/manual"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.UniqueConstraint("material_code", name="uq_semifinished_material_code"),
            sa.UniqueConstraint("size", "color_key", name="uq_semifinished_size_color"),
            comment="半成品主数据",
        )
    if "idx_semifinished_material_status" not in _indexes("ark_semifinished_materials"):
        op.create_index("idx_semifinished_material_status", "ark_semifinished_materials", ["status", "size"])

    if not _has_table("ark_semifinished_product_mappings"):
        op.create_table(
            "ark_semifinished_product_mappings",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("source_type", sa.String(16), nullable=False, server_default="okki", comment="产品来源 okki"),
            sa.Column("product_id", sa.BigInteger(), nullable=False, comment="来源产品ID"),
            sa.Column("product_name", sa.String(512), nullable=False, comment="产品名称快照"),
            sa.Column("model", sa.String(200), nullable=True, comment="产品型号快照"),
            sa.Column("size", sa.String(32), nullable=False, comment="解析尺寸"),
            sa.Column("color_expression", sa.String(256), nullable=False, comment="原始颜色表达式"),
            sa.Column("unit_grams", QTY, nullable=False, comment="单件克重"),
            sa.Column("parse_status", sa.String(24), nullable=False, comment="confirmed/needs_review/error"),
            sa.Column("source", sa.String(16), nullable=False, server_default="auto", comment="auto/manual"),
            sa.Column("parser_version", sa.String(32), nullable=False, comment="解析器版本"),
            sa.Column("parse_message", sa.String(500), nullable=True, comment="解析提示"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.UniqueConstraint("source_type", "product_id", name="uq_semifinished_product_source"),
            comment="产品半成品解析结果",
        )
    if "idx_semifinished_mapping_status" not in _indexes("ark_semifinished_product_mappings"):
        op.create_index("idx_semifinished_mapping_status", "ark_semifinished_product_mappings", ["parse_status", "product_id"])

    if not _has_table("ark_semifinished_product_components"):
        op.create_table(
            "ark_semifinished_product_components",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("mapping_id", sa.BigInteger(), nullable=False, comment="产品映射ID"),
            sa.Column("material_id", sa.BigInteger(), nullable=False, comment="半成品ID"),
            sa.Column("component_order", sa.SmallInteger(), nullable=False, server_default="1", comment="组成顺序"),
            sa.Column("ratio", RATIO, nullable=False, comment="用料比例"),
            sa.Column("grams_per_piece", QTY, nullable=False, comment="每件产品对应克数"),
            sa.ForeignKeyConstraint(["mapping_id"], ["ark_semifinished_product_mappings.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["material_id"], ["ark_semifinished_materials.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("mapping_id", "material_id", name="uq_semifinished_mapping_material"),
            comment="产品半成品组成",
        )

    if not _has_table("ark_semifinished_orders"):
        op.create_table(
            "ark_semifinished_orders",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("order_no", sa.String(32), nullable=False, comment="半成品订单号"),
            sa.Column("batch_no", sa.String(64), nullable=True, comment="生产批次号"),
            sa.Column("source_type", sa.String(24), nullable=False, server_default="manual", comment="manual/production_sync"),
            sa.Column("production_order_id", sa.Integer(), nullable=True, comment="关联产成品生产订单ID"),
            sa.Column("status", sa.String(16), nullable=False, server_default="submitted", comment="submitted/partial/completed/terminated"),
            sa.Column("is_urgent", sa.SmallInteger(), nullable=False, server_default="0", comment="是否加急"),
            sa.Column("expected_delivery_date", sa.Date(), nullable=True, comment="预计交期"),
            sa.Column("remark", sa.String(500), nullable=True, comment="备注"),
            sa.Column("created_by", USER_ID, nullable=False, comment="创建人"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["production_order_id"], ["ark_production_orders.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("order_no", name="uq_semifinished_order_no"),
            comment="半成品订单",
        )
    if "idx_semifinished_order_status" not in _indexes("ark_semifinished_orders"):
        op.create_index("idx_semifinished_order_status", "ark_semifinished_orders", ["status", "created_at"])

    if not _has_table("ark_semifinished_order_items"):
        op.create_table(
            "ark_semifinished_order_items",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("order_id", sa.BigInteger(), nullable=False, comment="半成品订单ID"),
            sa.Column("material_id", sa.BigInteger(), nullable=False, comment="半成品ID"),
            sa.Column("order_qty_grams", QTY, nullable=False, comment="下单克数"),
            sa.Column("received_qty_grams", QTY, nullable=False, server_default="0", comment="累计入库克数"),
            sa.Column("remark", sa.String(500), nullable=True, comment="备注"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["order_id"], ["ark_semifinished_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["material_id"], ["ark_semifinished_materials.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("order_id", "material_id", name="uq_semifinished_order_material"),
            comment="半成品订单明细",
        )

    if not _has_table("ark_semifinished_inventory_balances"):
        op.create_table(
            "ark_semifinished_inventory_balances",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("material_id", sa.BigInteger(), nullable=False, comment="半成品ID"),
            sa.Column("on_hand_grams", QTY, nullable=False, server_default="0", comment="实存克数"),
            sa.Column("reserved_grams", QTY, nullable=False, server_default="0", comment="占用克数"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="0", comment="余额版本号"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["material_id"], ["ark_semifinished_materials.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("material_id", name="uq_semifinished_balance_material"),
            comment="半成品库存余额",
        )

    if not _has_table("ark_semifinished_inventory_ledger"):
        op.create_table(
            "ark_semifinished_inventory_ledger",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("material_id", sa.BigInteger(), nullable=False, comment="半成品ID"),
            sa.Column("movement_type", sa.String(24), nullable=False, comment="inbound/outbound/reserve/release/adjust/reversal"),
            sa.Column("quantity_grams", QTY, nullable=False, comment="有符号数量"),
            sa.Column("on_hand_after", QTY, nullable=False, comment="变动后实存克数"),
            sa.Column("reserved_after", QTY, nullable=False, comment="变动后占用克数"),
            sa.Column("business_type", sa.String(32), nullable=False, comment="来源业务类型"),
            sa.Column("business_id", sa.BigInteger(), nullable=True, comment="来源业务ID"),
            sa.Column("business_line_id", sa.BigInteger(), nullable=True, comment="来源业务明细ID"),
            sa.Column("idempotency_key", sa.String(128), nullable=False, comment="全局幂等键"),
            sa.Column("created_by", USER_ID, nullable=True, comment="操作人"),
            sa.Column("remark", sa.String(500), nullable=True, comment="备注"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
            sa.ForeignKeyConstraint(["material_id"], ["ark_semifinished_materials.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by"], ["ark_users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("idempotency_key", name="uq_semifinished_ledger_idempotency"),
            comment="半成品库存不可变流水",
        )
    if "idx_semifinished_ledger_material" not in _indexes("ark_semifinished_inventory_ledger"):
        op.create_index("idx_semifinished_ledger_material", "ark_semifinished_inventory_ledger", ["material_id", "created_at"])

    if not _has_table("ark_semifinished_cart_plans"):
        op.create_table(
            "ark_semifinished_cart_plans",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("production_cart_id", sa.Integer(), nullable=False, comment="生产购物车行ID"),
            sa.Column("material_id", sa.BigInteger(), nullable=False, comment="半成品ID"),
            sa.Column("quantity_grams", QTY, nullable=False, comment="同步下单克数"),
            sa.ForeignKeyConstraint(["production_cart_id"], ["ark_production_cart.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["material_id"], ["ark_semifinished_materials.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("production_cart_id", "material_id", name="uq_semifinished_cart_material"),
            comment="生产购物车半成品同步计划",
        )

    if not _has_table("ark_invoice_semifinished_allocations"):
        op.create_table(
            "ark_invoice_semifinished_allocations",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
            sa.Column("invoice_id", sa.BigInteger(), nullable=False, comment="发票ID"),
            sa.Column("material_id", sa.BigInteger(), nullable=False, comment="半成品ID"),
            sa.Column("allocated_qty_grams", QTY, nullable=False, server_default="0", comment="已正式出库克数"),
            sa.Column("pending_delta_grams", QTY, nullable=False, server_default="0", comment="待完成差额克数"),
            sa.Column("operation_key", sa.String(64), nullable=True, comment="同步操作批次键"),
            sa.Column("status", sa.String(16), nullable=False, server_default="allocated", comment="allocated/pending"),
            sa.Column("pending_at", sa.DateTime(), nullable=True, comment="进入待处理时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
            sa.ForeignKeyConstraint(["invoice_id"], ["ark_invoices.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["material_id"], ["ark_semifinished_materials.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("invoice_id", "material_id", name="uq_invoice_semifinished_material"),
            comment="发票半成品当前分配与同步差额",
        )
    if "idx_invoice_semifinished_pending" not in _indexes("ark_invoice_semifinished_allocations"):
        op.create_index("idx_invoice_semifinished_pending", "ark_invoice_semifinished_allocations", ["status", "pending_at"])

    invoice_columns = _columns("ark_invoice_items")
    if "semifinished_enabled" not in invoice_columns:
        op.add_column("ark_invoice_items", sa.Column("semifinished_enabled", sa.SmallInteger(), nullable=False, server_default="0", comment="是否自动使用半成品"))
    if "semifinished_plan" not in invoice_columns:
        op.add_column("ark_invoice_items", sa.Column("semifinished_plan", sa.JSON(), nullable=True, comment="半成品计划快照[{material_id,quantity_grams}]"))


def downgrade() -> None:
    if _has_table("ark_invoice_items"):
        invoice_columns = _columns("ark_invoice_items")
        if "semifinished_plan" in invoice_columns:
            op.drop_column("ark_invoice_items", "semifinished_plan")
        if "semifinished_enabled" in invoice_columns:
            op.drop_column("ark_invoice_items", "semifinished_enabled")
    for table in (
        "ark_invoice_semifinished_allocations",
        "ark_semifinished_cart_plans",
        "ark_semifinished_inventory_ledger",
        "ark_semifinished_inventory_balances",
        "ark_semifinished_order_items",
        "ark_semifinished_orders",
        "ark_semifinished_product_components",
        "ark_semifinished_product_mappings",
        "ark_semifinished_materials",
    ):
        if _has_table(table):
            op.drop_table(table)
