"""Audit trail for explicit single-product inventory synchronization."""
from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON
from app.core.database import Base
from app.core.time import beijing_now


class InventorySyncLog(Base):
    __tablename__ = 'ark_inventory_sync_logs'

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    product_id = Column(BigInteger, nullable=False, comment='小满产品ID')
    created_by = Column(Integer, nullable=False, comment='操作人ID')
    observed_at = Column(DateTime, nullable=False, comment='库存拉取开始北京时间')
    before_data = Column(JSON, nullable=False, comment='同步前库存快照')
    after_data = Column(JSON, nullable=False, comment='同步后库存快照')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='审计创建北京时间')
    __table_args__ = (Index('ix_inventory_sync_product_time', 'product_id', 'created_at'),)
