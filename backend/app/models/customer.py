"""客户提成归属快照模型"""

from sqlalchemy import (
    Column, BigInteger, String, Date, Boolean, DateTime, Enum,
    DECIMAL, Text, Index, func,
)
from app.core.database import Base


class CustomerCommissionSnapshot(Base):
    """客户提成归属快照表"""
    __tablename__ = "customer_commission_snapshot"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, comment="客户ID")
    first_order_id = Column(String(64), nullable=True, comment="首单订单ID")
    first_order_date = Column(Date, nullable=True, comment="首单生效日期")
    salesperson_id = Column(String(64), nullable=False, comment="归属业务员ID")
    salesperson_attribute = Column(
        Enum("develop", "distribute", name="sp_attribute_enum"),
        nullable=True, comment="业务员属性快照，NULL表示待补充",
    )
    salesperson_rate = Column(DECIMAL(5, 4), nullable=True, comment="业务员提成比例")
    supervisor_id = Column(String(64), nullable=True, comment="归属业务主管ID")
    supervisor_attribute = Column(
        Enum("develop", "distribute", name="sv_attribute_enum"),
        nullable=True, comment="主管属性快照",
    )
    supervisor_rate = Column(DECIMAL(5, 4), nullable=True, comment="主管提成比例")
    is_complete = Column(Boolean, default=False, comment="是否完整（有比例即完整）")
    is_current = Column(Boolean, default=True, comment="是否当前有效")
    source = Column(
        Enum("auto", "manual", "import", "init", name="snapshot_source_enum"),
        server_default="auto", comment="来源：自动/手工/导入/初始化",
    )
    is_manual_reset = Column(Boolean, default=False, comment="是否人工重置产生")
    reset_reason = Column(Text, nullable=True, comment="重置原因")
    operator = Column(String(64), nullable=True, comment="操作人")
    operated_at = Column(DateTime, nullable=True, comment="操作时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_snapshot_customer_current", "customer_id", "is_current"),
        Index("ix_snapshot_is_complete", "is_complete"),
    )
