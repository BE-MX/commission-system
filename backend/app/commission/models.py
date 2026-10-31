"""Frozen attribution belongs to the original allocation, never its current owner."""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String
from app.core.database import Base
from app.core.time import beijing_now


class CommissionBasis(Base):
    __tablename__ = "ark_commission_bases"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="核销提成依据 ID")
    event_id = Column(BigInteger, ForeignKey("ark_finance_events.id"), nullable=False, unique=True, comment="原核销事件，不用于历史回款重导")
    customer_id = Column(String(64), nullable=False, index=True, comment="明确身份的客户 ID")
    snapshot = Column(JSON, nullable=True, comment="冻结受益人、比例和名称；空值表示待人工补全")
    pending_reason = Column(String(256), nullable=True, comment="待补全原因")
    resolved_by = Column(Integer, nullable=True, comment="补全操作人 ID")
    resolved_at = Column(DateTime, nullable=True, comment="补全北京时间")
    resolution_reason = Column(String(1000), nullable=True, comment="补全原业务日期归属的依据")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="冻结北京时间")


class CommissionEventProjection(Base):
    __tablename__ = "ark_commission_event_projections"
    event_id = Column(BigInteger, ForeignKey("ark_finance_events.id"), primary_key=True, comment="唯一被消费资金事件")
    basis_id = Column(BigInteger, ForeignKey("ark_commission_bases.id"), nullable=False, index=True, comment="继承原核销提成依据")
    payment_id = Column(String(64), nullable=False, unique=True, comment="提成消费身份，与旧回款不重叠")
    salesperson_commission = Column(Numeric(14, 2), nullable=False, comment="冻结业务员提成，冲回为负")
    supervisor_commission = Column(Numeric(14, 2), nullable=False, comment="冻结一级主管提成，冲回为负")
    second_supervisor_commission = Column(Numeric(14, 2), nullable=False, comment="冻结二级主管提成，冲回为负")
    salesperson_commission_rmb = Column(Numeric(14, 2), nullable=True, comment="冻结人民币业务员提成及累计冲回尾差")
    supervisor_commission_rmb = Column(Numeric(14, 2), nullable=True, comment="冻结人民币一级主管提成及累计冲回尾差")
    second_supervisor_commission_rmb = Column(Numeric(14, 2), nullable=True, comment="冻结人民币二级主管提成及累计冲回尾差")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="投影北京时间")
