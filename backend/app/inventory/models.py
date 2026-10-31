"""Inventory facts are append-only; balances are transactionally maintained projections."""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

USER_ID = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class Warehouse(Base):
    __tablename__ = "ark_warehouses"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    code = Column(String(64), nullable=False, unique=True, comment='唯一业务编码')
    name = Column(String(128), nullable=False, comment='名称')
    active = Column(Boolean, nullable=False, default=True, comment='是否启用')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时间）')


class StockBalance(Base):
    __tablename__ = "ark_stock_balances"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    warehouse_id = Column(BigInteger, ForeignKey("ark_warehouses.id", ondelete="RESTRICT"), nullable=False, comment='本地仓库ID')
    sku_id = Column(BigInteger, ForeignKey("ark_catalog_skus.id", ondelete="RESTRICT"), nullable=False, comment='本地SKU ID')
    quality = Column(String(16), nullable=False, default="sellable", comment='质量状态 sellable/quarantine/damaged')
    on_hand = Column(Integer, nullable=False, default=0, comment='实存件数')
    reserved = Column(Integer, nullable=False, default=0, comment='预占件数')
    version = Column(Integer, nullable=False, default=0, comment='库存变更版本')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间（北京时间）')

    __table_args__ = (
        UniqueConstraint("warehouse_id", "sku_id", "quality", name="uq_stock_balance_bucket"),
        CheckConstraint("on_hand >= 0 AND reserved >= 0 AND on_hand >= reserved", name="ck_stock_nonnegative"),
    )


class StockDocument(Base):
    __tablename__ = "ark_stock_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    idempotency_key = Column(String(128), nullable=False, unique=True, comment='全局库存命令幂等键')
    payload_hash = Column(String(64), nullable=False, comment='规范化请求SHA256')
    kind = Column(String(24), nullable=False, comment='业务类别')
    reason = Column(String(500), nullable=False, comment='业务原因')
    source_type = Column(String(32), nullable=True, comment='来源业务类型')
    source_id = Column(String(64), nullable=True, comment='来源业务ID')
    payload = Column(JSON, nullable=False, comment='原始命令快照')
    reversal_of_id = Column(BigInteger, ForeignKey("ark_stock_documents.id", ondelete="RESTRICT"), nullable=True, unique=True, comment='被冲销的原单ID，唯一')
    reversed_by_id = Column(BigInteger, nullable=True, comment='冲销单ID')
    created_by = Column(USER_ID, ForeignKey("ark_users.id", ondelete="RESTRICT"), nullable=True, comment='操作人 ark_users.id')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时间）')


class StockLedger(Base):
    __tablename__ = "ark_stock_ledger"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='本地主键')
    document_id = Column(BigInteger, ForeignKey("ark_stock_documents.id", ondelete="RESTRICT"), nullable=False, index=True, comment='库存单据ID')
    line_no = Column(Integer, nullable=False, comment='过账行号')
    warehouse_id = Column(BigInteger, ForeignKey("ark_warehouses.id", ondelete="RESTRICT"), nullable=False, comment='本地仓库ID')
    sku_id = Column(BigInteger, ForeignKey("ark_catalog_skus.id", ondelete="RESTRICT"), nullable=False, comment='本地SKU ID')
    quality = Column(String(16), nullable=False, comment='质量状态 sellable/quarantine/damaged')
    on_hand_delta = Column(Integer, nullable=False, comment='有符号实存变动件数')
    reserved_delta = Column(Integer, nullable=False, default=0, comment='有符号预占变动件数')
    on_hand_after = Column(Integer, nullable=False, comment='变动后实存件数')
    reserved_after = Column(Integer, nullable=False, comment='变动后预占件数')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间（北京时间）')

    __table_args__ = (UniqueConstraint("document_id", "line_no", name="uq_stock_ledger_line"),)


class StockReservation(Base):
    """Per-line demand projection, updated only with an immutable stock document."""

    __tablename__ = "ark_stock_reservations"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="本地主键")
    invoice_item_id = Column(BigInteger, ForeignKey("ark_invoice_items.id", ondelete="RESTRICT"), nullable=False, comment="销售订单明细ID")
    warehouse_id = Column(BigInteger, ForeignKey("ark_warehouses.id", ondelete="RESTRICT"), nullable=False, comment="预占仓库ID")
    sku_id = Column(BigInteger, ForeignKey("ark_catalog_skus.id", ondelete="RESTRICT"), nullable=False, comment="不可变本地SKU ID")
    reserved = Column(Integer, nullable=False, default=0, comment="当前未出库预占件数")
    shipped = Column(Integer, nullable=False, default=0, comment="累计已正式出库件数；退货不自动增加订单需求")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间（北京时间）")

    __table_args__ = (
        UniqueConstraint("invoice_item_id", "warehouse_id", name="uq_stock_reservation_line_warehouse"),
        CheckConstraint("reserved >= 0 AND shipped >= 0", name="ck_stock_reservation_nonnegative"),
    )
