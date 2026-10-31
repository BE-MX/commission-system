"""Local production responsibility and material movement facts."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint, CheckConstraint
from app.core.database import Base
from app.core.time import beijing_now


class ProductionEvent(Base):
    __tablename__ = "ark_production_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="本地生产事件ID")
    request_key = Column(String(64), nullable=False, unique=True, comment="命令幂等键")
    request_hash = Column(String(64), nullable=False, comment="操作人及完整命令摘要")
    action = Column(String(32), nullable=False, comment="创建/完工/验收入库/供货规划/领退料/损耗")
    order_id = Column(Integer, ForeignKey("ark_production_orders.id"), nullable=True, index=True, comment="生产订单ID")
    item_id = Column(Integer, ForeignKey("ark_production_order_items.id"), nullable=True, index=True, comment="生产明细ID")
    supply_id = Column(BigInteger, ForeignKey("ark_production_supplies.id"), nullable=True, comment="销售供货关系ID")
    stock_document_id = Column(BigInteger, ForeignKey("ark_stock_documents.id"), nullable=True, comment="验收入库库存单据ID")
    reverses_event_id = Column(BigInteger, ForeignKey("ark_production_events.id"), nullable=True, unique=True, comment="冲销的原生产事件ID，只允许一次")
    payload = Column(JSON, nullable=False, comment="生产操作不可变快照")
    created_by = Column(Integer, nullable=False, comment="操作人ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间，北京时间")


class ProductionSupply(Base):
    __tablename__ = "ark_production_supplies"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="生产供货关系ID")
    production_item_id = Column(Integer, ForeignKey("ark_production_order_items.id"), nullable=False, index=True, comment="生产明细ID")
    invoice_item_id = Column(BigInteger, ForeignKey("ark_invoice_items.id"), nullable=False, index=True, comment="销售明细ID")
    quantity = Column(Integer, nullable=False, comment="原始计划供货件数")
    received_quantity = Column(Integer, nullable=False, default=0, comment="已验收入库并预占给销售的件数")
    released_quantity = Column(Integer, nullable=False, default=0, comment="已释放的计划供货件数")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间，北京时间")
    __table_args__ = (CheckConstraint("quantity > 0 AND received_quantity >= 0 AND released_quantity >= 0 AND received_quantity + released_quantity <= quantity", name="ck_production_supply_quantities"),)


class ProductionMaterial(Base):
    __tablename__ = "ark_production_materials"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="生产领料累计ID")
    production_item_id = Column(Integer, ForeignKey("ark_production_order_items.id"), nullable=False, comment="生产明细ID")
    material_id = Column(BigInteger, ForeignKey("ark_semifinished_materials.id"), nullable=False, comment="半成品物料ID")
    issued_grams = Column(Numeric(14, 3), nullable=False, default=0, comment="实际领用累计克数")
    returned_grams = Column(Numeric(14, 3), nullable=False, default=0, comment="实物退回累计克数")
    loss_grams = Column(Numeric(14, 3), nullable=False, default=0, comment="已领用中的确认损耗，不重复扣库存")
    __table_args__ = (
        UniqueConstraint("production_item_id", "material_id", name="uq_production_material"),
        CheckConstraint("issued_grams >= 0 AND returned_grams >= 0 AND loss_grams >= 0 AND returned_grams + loss_grams <= issued_grams", name="ck_production_material_quantities"),
    )
