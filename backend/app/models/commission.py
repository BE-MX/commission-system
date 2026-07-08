"""提成批次、提成明细、已同步回款、回款提成状态模型"""

from sqlalchemy import (
    Column, BigInteger, String, Date, DateTime, Enum, DECIMAL, Text,
    ForeignKey, Index, func,
)
from app.core.database import Base


class SyncedPayment(Base):
    """已同步回款记录表"""
    __tablename__ = "synced_payment"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    payment_id = Column(String(64), nullable=False, unique=True, comment="业务库回款ID")
    order_id = Column(String(64), nullable=False, comment="关联订单ID")
    customer_id = Column(String(64), nullable=False, comment="关联客户ID")
    payment_date = Column(Date, nullable=False, comment="回款日期")
    payment_amount = Column(DECIMAL(12, 2), nullable=False, comment="回款金额（USD，来源 okki_receipts.amount_usd）")
    service_fee = Column(DECIMAL(15, 2), server_default="0", comment="服务费（USD，来源 service_fee_amount_usd）")
    exchange_rate = Column(DECIMAL(12, 6), nullable=True, comment="汇率")
    real_amount_rmb = Column(DECIMAL(15, 2), nullable=True, comment="回款金额(RMB)")
    synced_at = Column(DateTime, server_default=func.now(), comment="同步时间")

    __table_args__ = (
        Index("ix_synced_payment_date", "payment_date"),
        Index("ix_synced_payment_customer", "customer_id"),
        {"comment": "已同步回款记录表：从业务库同步的回款，提成计算数据源"},
    )


class CommissionBatch(Base):
    """提成批次表"""
    __tablename__ = "commission_batch"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_name = Column(String(128), nullable=False, comment="批次名称")
    period_type = Column(
        Enum("monthly", "quarterly", "semi_annual", "annual", name="period_type_enum"),
        server_default="quarterly",
        comment="计提周期类型 monthly/quarterly/semi_annual/annual",
    )
    period_start = Column(Date, nullable=False, comment="周期开始日期")
    period_end = Column(Date, nullable=False, comment="周期结束日期")
    status = Column(
        Enum("draft", "calculated", "confirming", "confirmed", "voided", name="batch_status_enum"),
        server_default="draft",
        comment="批次状态 draft/calculated/confirming/confirmed/voided",
    )
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    created_by = Column(String(64), nullable=True, comment="创建人ID")
    confirmed_at = Column(DateTime, nullable=True, comment="管理员确认时间")
    confirmed_by = Column(String(64), nullable=True, comment="确认人ID")

    __table_args__ = {"comment": "提成批次表：按周期汇总计算业务员提成"}


class CommissionDetail(Base):
    """提成明细表"""
    __tablename__ = "commission_detail"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("commission_batch.id"), nullable=False, comment="所属提成批次ID")
    payment_id = Column(String(64), nullable=False, comment="回款单ID")
    order_id = Column(String(64), nullable=False, comment="订单ID")
    customer_id = Column(String(64), nullable=False, comment="客户ID")
    payment_amount = Column(DECIMAL(12, 2), nullable=False, comment="回款金额（USD）")
    salesperson_id = Column(String(64), nullable=False, comment="业务员ID")
    salesperson_rate = Column(DECIMAL(5, 4), nullable=False, comment="业务员提成比例（小数，0.02=2%，统一2%不分开发/分配）")
    salesperson_commission = Column(DECIMAL(12, 2), nullable=False, comment="业务员提成（USD）")
    supervisor_id = Column(String(64), nullable=True, comment="一级主管ID")
    supervisor_rate = Column(DECIMAL(5, 4), nullable=True, comment="一级主管提成比例（小数，如0.01=1%）")
    supervisor_commission = Column(DECIMAL(12, 2), server_default="0", comment="一级主管提成（USD）")
    second_supervisor_id = Column(String(64), nullable=True, comment="二级主管ID")
    second_supervisor_rate = Column(DECIMAL(5, 4), nullable=True, comment="二级主管提成比例（小数）")
    second_supervisor_commission = Column(DECIMAL(12, 2), server_default="0", comment="二级主管提成（USD）")
    calc_rule_note = Column(String(256), nullable=True, comment="计算规则说明")
    calculated_at = Column(DateTime, server_default=func.now(), comment="计算时间")
    status = Column(
        Enum("pending", "confirmed", "paid", "voided", name="detail_status_enum"),
        server_default="pending",
        comment="明细状态 pending/confirmed/paid/voided",
    )

    __table_args__ = (
        Index("ix_detail_batch", "batch_id"),
        Index("ix_detail_payment", "payment_id"),
        Index("ix_detail_order", "order_id"),
        Index("ix_detail_salesperson", "salesperson_id"),
        Index("ix_detail_supervisor", "supervisor_id"),
        Index("ix_detail_second_supervisor", "second_supervisor_id"),
        {"comment": "提成明细表：每条回款按业务员/主管拆分的提成记录"},
    )


class PaymentCommissionStatus(Base):
    """回款提成状态表：标记哪些回款已参与提成计算"""
    __tablename__ = "payment_commission_status"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    payment_id = Column(String(64), nullable=False, unique=True, comment="回款单ID")
    batch_id = Column(BigInteger, ForeignKey("commission_batch.id"), nullable=False, comment="参与计算的提成批次ID")
    calculated_at = Column(DateTime, server_default=func.now(), comment="计算时间")

    __table_args__ = {"comment": "回款提成状态表：标记回款是否已参与提成计算，防重复计提"}


class CommissionBatchFeedback(Base):
    """业务员对提成批次的独立反馈消息"""
    __tablename__ = "commission_batch_feedback"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("commission_batch.id"), nullable=False, comment="提成批次ID")
    ark_user_id = Column(String(64), nullable=False, comment="方舟用户ID")
    user_name = Column(String(128), nullable=True, comment="反馈人姓名")
    business_user_ids = Column(String(255), nullable=True, comment="匹配到的业务库用户ID，逗号分隔")
    content = Column(Text, nullable=False, comment="反馈内容")
    created_at = Column(DateTime, server_default=func.now(), comment="反馈时间")

    __table_args__ = (
        Index("ix_commission_feedback_batch", "batch_id"),
        Index("ix_commission_feedback_user", "ark_user_id"),
        {"comment": "提成批次反馈表：业务员对批次的异议/留言"},
    )


class CommissionBatchConfirmation(Base):
    """业务员个人维度的提成批次确认记录"""
    __tablename__ = "commission_batch_confirmation"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(BigInteger, ForeignKey("commission_batch.id"), nullable=False, comment="提成批次ID")
    ark_user_id = Column(String(64), nullable=False, comment="方舟用户ID")
    user_name = Column(String(128), nullable=True, comment="确认人姓名")
    business_user_ids = Column(String(255), nullable=True, comment="确认人匹配到的业务库用户ID，逗号分隔")
    confirmation_text = Column(String(32), nullable=False, comment="确认输入文本")
    status = Column(String(32), nullable=False, server_default="confirmed", comment="confirmed/revoked")
    confirmed_at = Column(DateTime, server_default=func.now(), comment="确认时间")

    __table_args__ = (
        Index("ix_commission_confirmation_batch", "batch_id"),
        Index("ix_commission_confirmation_user", "ark_user_id"),
        Index("uq_commission_confirmation_user", "batch_id", "ark_user_id", unique=True),
        {"comment": "提成批次确认表：业务员个人维度的批次确认记录"},
    )
