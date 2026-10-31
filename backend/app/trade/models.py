"""Small read-side checkpoints; invoices remain the only sales order ledger."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.dialects import mysql
from app.core.database import Base
from app.core.time import beijing_now


class TradeProjection(Base):
    __tablename__ = "ark_trade_projections"
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), primary_key=True, comment="唯一订单主账 ID")
    customer_order_id = Column(BigInteger, ForeignKey("ark_customer_orders.id"), nullable=False, unique=True, comment="唯一客户订单事实投影")
    invoice_version = Column(Integer, nullable=False, comment="已处理订单版本")
    finance_event_id = Column(BigInteger, nullable=False, default=0, comment="该订单已处理资金事件水位")
    aftersales_execution_id = Column(BigInteger, nullable=False, default=0, comment="该订单已处理售后执行水位")
    content_hash = Column(String(64), nullable=False, comment="已投影业务内容摘要")
    projected_at = Column(DateTime, nullable=False, default=beijing_now, comment="真实投影完成北京时间")


class SalesRoster(Base):
    __tablename__ = "ark_sales_roster"
    ark_user_id = Column(Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"), ForeignKey("ark_users.id"), primary_key=True, comment="本地业务员 ID")
    legacy_user_id = Column(String(64), nullable=True, unique=True, comment="经核验的历史小满业务员 ID；非本地交易前提")
    department_id = Column(Integer, ForeignKey("sys_dict.id", ondelete="RESTRICT"), nullable=True, comment="本地销售部门字典稳定ID")
    english_name = Column(String(128), nullable=True, comment="英文展示名")
    team = Column(String(100), nullable=False, default="", comment="经营统计分队")
    camp = Column(String(100), nullable=False, default="", comment="活动阵营")
    new_customer_target = Column(Integer, nullable=False, default=0, comment="新签目标")
    amount_target = Column(Numeric(16, 2), nullable=False, default=0, comment="经营目标 USD")
    active = Column(Boolean, nullable=False, default=True, comment="是否在统计名册内")
    version = Column(Integer, nullable=False, default=1, comment="名册并发版本")
    updated_by = Column(Integer, nullable=False, comment="维护人 ID")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="维护北京时间")
