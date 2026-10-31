"""Accounting reference data and append-only economic command journal."""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from app.core.database import Base
from app.core.time import beijing_now


class FinanceBook(Base):
    __tablename__ = "ark_finance_books"
    id = Column(Integer, primary_key=True, comment="唯一账簿 ID，固定为1")
    closed_through = Column(Date, nullable=True, comment="含当日已结账日期，不允许回写")
    version = Column(Integer, nullable=False, default=1, comment="账簿版本")


class Currency(Base):
    __tablename__ = "ark_finance_currencies"
    code = Column(String(16), primary_key=True, comment="币种代码")
    name = Column(String(64), nullable=False, comment="币种名称")
    rate_to_cny = Column(Numeric(18, 8), nullable=False, comment="一单位原币对应人民币，登记付款时冻结")
    active = Column(Integer, nullable=False, default=1, comment="是否启用")


class BankAccount(Base):
    __tablename__ = "ark_bank_accounts"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="银行账户 ID")
    code = Column(String(64), nullable=False, unique=True, comment="账户内部编码，不存储完整银行卡号")
    name = Column(String(128), nullable=False, comment="账户显示名称")
    currency = Column(String(16), ForeignKey("ark_finance_currencies.code"), nullable=False, comment="账户结算币种")
    active = Column(Integer, nullable=False, default=1, comment="是否启用")


class FinanceEvent(Base):
    __tablename__ = "ark_finance_events"
    __table_args__ = (UniqueConstraint("bank_account_id", "bank_reference", name="uq_finance_event_bank_reference"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="资金事件 ID")
    request_key = Column(String(64), nullable=False, unique=True, comment="命令幂等键")
    request_hash = Column(String(64), nullable=False, comment="命令内容与操作人摘要")
    action = Column(String(32), nullable=False, comment="登记、确认、核销、核销冲回、退款、应收调整、结账")
    batch_id = Column(BigInteger, ForeignKey("ark_receipt_batches.id"), index=True, comment="关联收款批次")
    receipt_id = Column(BigInteger, ForeignKey("ark_receipts.id"), index=True, comment="关联订单核销")
    receivable_id = Column(BigInteger, ForeignKey("ark_receivables.id"), index=True, comment="关联应收")
    bank_account_id = Column(BigInteger, ForeignKey("ark_bank_accounts.id"), comment="退款银行账户")
    bank_reference = Column(String(128), comment="退款银行流水号，账户内不可重复")
    business_date = Column(Date, nullable=False, comment="记账业务日期，北京时间")
    amount = Column(Numeric(14, 2), nullable=False, default=0, comment="事件原币金额，冲回为负数")
    commission_amount_usd = Column(Numeric(14, 2), nullable=False, default=0, comment="核销或冲回对应美元提成基数，不重复扣银行费用")
    payload = Column(JSON, nullable=False, comment="命令快照及业务依据")
    created_by = Column(Integer, nullable=False, comment="操作人 ID")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="事件创建北京时间")
