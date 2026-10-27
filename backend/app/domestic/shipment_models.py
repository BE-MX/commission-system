"""Delivery batches reference existing order units; allocations never replace the cash ledger."""
from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, Numeric, JSON, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.mysql import INTEGER
from app.core.database import Base
from app.core.time import beijing_now

_UINT = INTEGER(unsigned=True).with_variant(Integer, "sqlite")


class DomesticShipment(Base):
    __tablename__ = "ark_domestic_shipments"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    shipment_no = Column(String(40), nullable=False, unique=True, comment="发货批次号")
    customer_id = Column(Integer, ForeignKey("ark_domestic_customers.id"), nullable=False, index=True, comment="客户ID")
    ship_time = Column(DateTime, nullable=False, comment="实际发货时间，北京时间")
    received_date = Column(Date, comment="客户确认收货日期")
    total_amount = Column(Numeric(14, 2), nullable=False, comment="批次货款合计")
    remark = Column(String(500), comment="说明")
    request_id = Column(String(64), nullable=False, unique=True, comment="来源申请ID或客户端幂等键")
    request_hash = Column(String(64), nullable=False, comment="发货内容指纹")
    created_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="经办人ID")
    received_by = Column(_UINT, ForeignKey("ark_users.id"), comment="收货登记人ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间，北京时间")
    received_at = Column(DateTime, comment="收货登记时间，北京时间")
    cancelled_at = Column(DateTime, comment="批次取消时间，北京时间")
    cancelled_by = Column(_UINT, ForeignKey("ark_users.id"), comment="批次取消人ID")
    cancelled_units = Column(JSON, comment="取消时各批次明细的件ID和件号快照")
    __table_args__ = (CheckConstraint("total_amount >= 0", name="ck_dom_shipment_amount"),)


class DomesticShipmentLine(Base):
    __tablename__ = "ark_domestic_shipment_lines"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    shipment_id = Column(BigInteger, ForeignKey("ark_domestic_shipments.id"), nullable=False, index=True, comment="发货批次ID")
    item_id = Column(Integer, ForeignKey("ark_domestic_order_items.id"), nullable=False, index=True, comment="订单明细ID")
    order_no = Column(String(64), nullable=False, comment="客户订单号快照")
    domestic_no = Column(String(32), nullable=False, comment="系统订单号快照")
    line_code = Column(String(24), nullable=False, comment="订单明细序号快照")
    guest_name = Column(String(120), comment="顾客名称快照")
    product_name = Column(String(255), nullable=False, comment="产品名称快照")
    attrs_snapshot = Column(JSON, comment="交付时产品规格快照")
    quantity = Column(Integer, nullable=False, comment="本批发货数量")
    unit_price = Column(Numeric(14, 2), nullable=False, comment="交付时成交单价")
    amount = Column(Numeric(14, 2), nullable=False, comment="货款或核销金额")
    ship_weight = Column(Numeric(10, 2), comment="发货克重")
    __table_args__ = (
        UniqueConstraint("shipment_id", "item_id", name="uq_dom_shipment_item"),
        CheckConstraint("quantity > 0 AND unit_price >= 0 AND amount >= 0", name="ck_dom_ship_line_amount"),
    )


class DomesticShipmentUnit(Base):
    __tablename__ = "ark_domestic_shipment_units"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    line_id = Column(BigInteger, ForeignKey("ark_domestic_shipment_lines.id"), nullable=False, index=True, comment="批次明细ID")
    unit_id = Column(BigInteger, ForeignKey("ark_domestic_item_units.id"), nullable=False, unique=True, comment="已交付具体件ID")


class DomesticReceiptAllocation(Base):
    __tablename__ = "ark_domestic_receipt_allocations"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id = Column(BigInteger, ForeignKey("ark_domestic_customer_requests.id"), nullable=False, index=True, comment="来源申请ID或客户端幂等键")
    shipment_id = Column(BigInteger, ForeignKey("ark_domestic_shipments.id"), nullable=False, index=True, comment="发货批次ID")
    amount = Column(Numeric(14, 2), nullable=False, comment="货款或核销金额")
    ledger_id = Column(BigInteger, ForeignKey("ark_domestic_customer_ledger.id"), comment="已入账证据；待审核为空")
    business_key = Column(String(128), nullable=False, unique=True, comment="核销增量幂等键，保存每次分配历史")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间，北京时间")
    created_by = Column(_UINT, ForeignKey("ark_users.id"), nullable=False, comment="经办人ID")
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_dom_receipt_allocation_amount"),
    )
