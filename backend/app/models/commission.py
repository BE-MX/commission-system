"""提成批次、提成明细、已同步回款、回款提成状态模型"""

from sqlalchemy import (
    Column, BigInteger, String, Date, Boolean, DateTime, Enum,
    DECIMAL, ForeignKey, Index, func,
)
from app.core.database import Base


class SyncedPayment(Base):
    """已同步回款记录表"""
    __tablename__ = "synced_payment"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    payment_id = Column(String(64), nullable=False, unique=True, comment="业务库回款ID")
    order_id = Column(String(64), nullable=False, comment="关联订单ID")
    customer_id = Column(String(64), nullable=False, comment="关联客户ID")
    payment_date = Column(Date, nullable=False, comment="回款日期")
    payment_amount = Column(DECIMAL(12, 2), nullable=False, comment="回款金额")
    synced_at = Column(DateTime, server_default=func.now(), comment="同步时间")

    __table_args__ = (
        Index("ix_synced_payment_date", "payment_date"),
        Index("ix_synced_payment_customer", "customer_id"),
    )


class CommissionBatch(Base):
    """提成批次表"""
    __tablename__ = "commission_batch"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_name = Column(String(128), nullable=False, comment="批次名称")
    period_type = Column(
        Enum("monthly", "quarterly", "semi_annual", "annual", name="period_type_enum"),
        server_default="quarterly",
    )
    period_start = Column(Date, nullable=False, comment="周期开始日期")
    period_end = Column(Date, nullable=False, comment="周期结束日期")
    status = Column(
        Enum("draft", "calculated", "confirmed", "voided", name="batch_status_enum"),
        server_default="draft",
    )
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(String(64), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    confirmed_by = Column(String(64), nullable=True)


class CommissionDetail(Base):
    """提成明细表"""
    __tablename__ = "commission_detail"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_id = Column(BigInteger, ForeignKey("commission_batch.id"), nullable=False)
    payment_id = Column(String(64), nullable=False, comment="回款单ID")
    order_id = Column(String(64), nullable=False, comment="订单ID")
    customer_id = Column(String(64), nullable=False, comment="客户ID")
    payment_amount = Column(DECIMAL(12, 2), nullable=False, comment="本条回款金额")
    salesperson_id = Column(String(64), nullable=False)
    salesperson_rate = Column(DECIMAL(5, 4), nullable=False)
    salesperson_commission = Column(DECIMAL(12, 2), nullable=False, comment="业务员提成金额")
    supervisor_id = Column(String(64), nullable=True)
    supervisor_rate = Column(DECIMAL(5, 4), nullable=True)
    supervisor_commission = Column(DECIMAL(12, 2), server_default="0", comment="主管提成金额")
    calc_rule_note = Column(String(256), nullable=True, comment="计算规则说明")
    calculated_at = Column(DateTime, server_default=func.now())
    status = Column(
        Enum("pending", "confirmed", "paid", "voided", name="detail_status_enum"),
        server_default="pending",
    )

    __table_args__ = (
        Index("ix_detail_batch", "batch_id"),
        Index("ix_detail_payment", "payment_id"),
        Index("ix_detail_order", "order_id"),
        Index("ix_detail_salesperson", "salesperson_id"),
        Index("ix_detail_supervisor", "supervisor_id"),
    )


class PaymentCommissionStatus(Base):
    """回款提成状态表：标记哪些回款已参与提成计算"""
    __tablename__ = "payment_commission_status"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    payment_id = Column(String(64), nullable=False, unique=True, comment="回款单ID")
    batch_id = Column(BigInteger, ForeignKey("commission_batch.id"), nullable=False)
    calculated_at = Column(DateTime, server_default=func.now(), comment="计算时间")
