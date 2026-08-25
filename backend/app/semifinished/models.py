"""半成品领域 ORM 模型。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship

from app.core.database import Base


QTY = Numeric(14, 3)
RATIO = Numeric(8, 6)
USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class SemifinishedMaterial(Base):
    __tablename__ = "ark_semifinished_materials"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    material_code = Column(String(32), nullable=False, unique=True, comment="半成品编码")
    size = Column(String(32), nullable=False, comment="标准化尺寸")
    color_code = Column(String(128), nullable=False, comment="显示色号")
    color_key = Column(String(128), nullable=False, comment="标准化色号键")
    color_type = Column(String(24), nullable=False, default="solid", comment="色型 solid/t/named_t")
    safety_stock_grams = Column(QTY, nullable=False, default=0, comment="安全库存克数")
    status = Column(String(16), nullable=False, default="active", comment="状态 active/inactive")
    source = Column(String(16), nullable=False, default="auto", comment="来源 auto/manual")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("size", "color_key", name="uq_semifinished_size_color"),
        Index("idx_semifinished_material_status", "status", "size"),
        {"comment": "半成品主数据"},
    )


class ProductMapping(Base):
    __tablename__ = "ark_semifinished_product_mappings"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    source_type = Column(String(16), nullable=False, default="okki", comment="产品来源 okki")
    product_id = Column(BigInteger, nullable=False, comment="来源产品ID")
    product_name = Column(String(512), nullable=False, comment="产品名称快照")
    model = Column(String(200), nullable=True, comment="产品型号快照")
    size = Column(String(32), nullable=False, comment="解析尺寸")
    color_expression = Column(String(256), nullable=False, comment="原始颜色表达式")
    unit_grams = Column(QTY, nullable=False, comment="单件克重")
    parse_status = Column(String(24), nullable=False, comment="解析状态 confirmed/needs_review/error")
    source = Column(String(16), nullable=False, default="auto", comment="映射来源 auto/manual")
    parser_version = Column(String(32), nullable=False, comment="解析器版本")
    parse_message = Column(String(500), nullable=True, comment="解析提示")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    components = relationship("ProductComponent", cascade="all, delete-orphan", lazy="noload")

    __table_args__ = (
        UniqueConstraint("source_type", "product_id", name="uq_semifinished_product_source"),
        Index("idx_semifinished_mapping_status", "parse_status", "product_id"),
        {"comment": "产品半成品解析结果"},
    )


class ProductComponent(Base):
    __tablename__ = "ark_semifinished_product_components"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    mapping_id = Column(BigInteger, ForeignKey("ark_semifinished_product_mappings.id", ondelete="CASCADE"), nullable=False, comment="产品映射ID")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id", ondelete="RESTRICT"), nullable=False, comment="半成品ID")
    component_order = Column(SmallInteger, nullable=False, default=1, comment="组成顺序")
    ratio = Column(RATIO, nullable=False, comment="用料比例")
    grams_per_piece = Column(QTY, nullable=False, comment="每件产品对应克数")
    material = relationship("SemifinishedMaterial", lazy="noload")

    __table_args__ = (
        UniqueConstraint("mapping_id", "material_id", name="uq_semifinished_mapping_material"),
        {"comment": "产品半成品组成"},
    )


class SemifinishedOrder(Base):
    __tablename__ = "ark_semifinished_orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_no = Column(String(32), nullable=False, unique=True, comment="半成品订单号")
    batch_no = Column(String(64), nullable=True, comment="生产批次号")
    source_type = Column(String(24), nullable=False, default="manual", comment="来源 manual/production_sync")
    production_order_id = Column(Integer, ForeignKey("ark_production_orders.id", ondelete="SET NULL"), nullable=True, comment="关联产成品生产订单ID")
    status = Column(String(16), nullable=False, default="submitted", comment="状态 submitted/partial/completed/terminated")
    is_urgent = Column(SmallInteger, nullable=False, default=0, comment="是否加急")
    expected_delivery_date = Column(Date, nullable=True, comment="预计交期")
    remark = Column(String(500), nullable=True, comment="备注")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=False, comment="创建人")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    items = relationship("SemifinishedOrderItem", cascade="all, delete-orphan", lazy="noload")

    __table_args__ = (
        Index("idx_semifinished_order_status", "status", "created_at"),
        {"comment": "半成品订单"},
    )


class SemifinishedOrderItem(Base):
    __tablename__ = "ark_semifinished_order_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    order_id = Column(BigInteger, ForeignKey("ark_semifinished_orders.id", ondelete="CASCADE"), nullable=False, comment="半成品订单ID")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id", ondelete="RESTRICT"), nullable=False, comment="半成品ID")
    order_qty_grams = Column(QTY, nullable=False, comment="下单克数")
    received_qty_grams = Column(QTY, nullable=False, default=0, comment="累计入库克数")
    remark = Column(String(500), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    material = relationship("SemifinishedMaterial", lazy="noload")

    __table_args__ = (
        UniqueConstraint("order_id", "material_id", name="uq_semifinished_order_material"),
        {"comment": "半成品订单明细"},
    )


class InventoryBalance(Base):
    __tablename__ = "ark_semifinished_inventory_balances"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id", ondelete="RESTRICT"), nullable=False, unique=True, comment="半成品ID")
    on_hand_grams = Column(QTY, nullable=False, default=0, comment="实存克数")
    reserved_grams = Column(QTY, nullable=False, default=0, comment="占用克数")
    version = Column(Integer, nullable=False, default=0, comment="余额版本号")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    material = relationship("SemifinishedMaterial", lazy="noload")

    __table_args__ = ({"comment": "半成品库存余额"},)


class InventoryLedger(Base):
    __tablename__ = "ark_semifinished_inventory_ledger"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id", ondelete="RESTRICT"), nullable=False, comment="半成品ID")
    movement_type = Column(String(24), nullable=False, comment="变动类型 inbound/outbound/reserve/release/adjust/reversal")
    quantity_grams = Column(QTY, nullable=False, comment="有符号变动克数")
    on_hand_after = Column(QTY, nullable=False, comment="变动后实存克数")
    reserved_after = Column(QTY, nullable=False, comment="变动后占用克数")
    business_type = Column(String(32), nullable=False, comment="来源业务类型")
    business_id = Column(BigInteger, nullable=True, comment="来源业务ID")
    business_line_id = Column(BigInteger, nullable=True, comment="来源业务明细ID")
    idempotency_key = Column(String(128), nullable=False, unique=True, comment="全局幂等键")
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="操作人")
    remark = Column(String(500), nullable=True, comment="备注")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_semifinished_ledger_material", "material_id", "created_at"),
        {"comment": "半成品库存不可变流水"},
    )


class CartPlan(Base):
    __tablename__ = "ark_semifinished_cart_plans"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    production_cart_id = Column(Integer, ForeignKey("ark_production_cart.id", ondelete="CASCADE"), nullable=False, comment="生产购物车行ID")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id", ondelete="RESTRICT"), nullable=False, comment="半成品ID")
    quantity_grams = Column(QTY, nullable=False, comment="同步下单克数")

    __table_args__ = (
        UniqueConstraint("production_cart_id", "material_id", name="uq_semifinished_cart_material"),
        {"comment": "生产购物车半成品同步计划"},
    )


class InvoiceAllocation(Base):
    __tablename__ = "ark_invoice_semifinished_allocations"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), nullable=False, comment="发票ID")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id", ondelete="RESTRICT"), nullable=False, comment="半成品ID")
    allocated_qty_grams = Column(QTY, nullable=False, default=0, comment="已正式出库克数")
    pending_delta_grams = Column(QTY, nullable=False, default=0, comment="待完成差额克数")
    operation_key = Column(String(64), nullable=True, comment="同步操作批次键")
    status = Column(String(16), nullable=False, default="allocated", comment="状态 allocated/pending")
    pending_at = Column(DateTime, nullable=True, comment="进入待处理时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("invoice_id", "material_id", name="uq_invoice_semifinished_material"),
        Index("idx_invoice_semifinished_pending", "status", "pending_at"),
        {"comment": "发票半成品当前分配与同步差额"},
    )
