"""Presale fulfillment and funding ledgers; business mirrors remain read-only."""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now


class ShipmentSettlement(Base):
    __tablename__ = "ark_shipment_settlements"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    settlement_no = Column(String(96), nullable=False, unique=True)
    state = Column(String(32), nullable=False, default="awaiting_payment")
    is_final = Column(Integer, nullable=False)
    quote = Column(JSON, nullable=False)
    quote_hash = Column(String(64), nullable=False)
    request_key = Column(String(64), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=beijing_now)
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now)
    __table_args__ = (UniqueConstraint("invoice_id", "sequence", name="uq_shipment_sequence"),)


class SettlementItem(Base):
    __tablename__ = "ark_shipment_settlement_items"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, index=True)
    invoice_item_id = Column(BigInteger, ForeignKey("ark_invoice_items.id", ondelete="RESTRICT"), nullable=False)
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Numeric(14, 2), nullable=False)
    snapshot = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("settlement_id", "invoice_item_id", name="uq_shipment_item"),)


class Receivable(Base):
    __tablename__ = "ark_receivables"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False, index=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=True)
    business_key = Column(String(96), nullable=False, unique=True)
    kind = Column(String(16), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    paid_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="本地有效核销累计金额")
    adjustment_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="本地应收调整累计金额，贷项为负")
    due_date = Column(Date, nullable=True, comment="约定到期日，北京业务日期")
    handling_amount = Column(Numeric(14, 2), nullable=False, default=0)
    currency = Column(String(16), nullable=False)
    customer_id = Column(String(64), nullable=False)
    remote_order_id = Column(String(64), nullable=True, unique=True)
    remote_order_name = Column(String(96), nullable=True, unique=True)
    remote_payload = Column(JSON, nullable=True)
    remote_payload_hash = Column(String(64), nullable=True)
    remote_status = Column(String(24), nullable=False, default="unverified")
    attempt_token = Column(String(64), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, nullable=False, default=beijing_now)


class ReceiptBatch(Base):
    __tablename__ = "ark_receipt_batches"
    __table_args__ = (UniqueConstraint("bank_account_id", "bank_reference", name="uq_receipt_batch_bank_reference"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_no = Column(String(64), nullable=False, unique=True)
    customer_id = Column(String(64), nullable=False)
    currency = Column(String(16), nullable=False)
    gross_amount = Column(Numeric(14, 2), nullable=False)
    transaction_mode = Column(String(16), nullable=False, default="legacy", server_default="legacy", comment="legacy历史或local本地资金")
    local_customer_id = Column(BigInteger, ForeignKey("ark_customer_accounts.id"), nullable=True, comment="本地稳定客户 ID")
    bank_account_id = Column(BigInteger, ForeignKey("ark_bank_accounts.id"), nullable=True, comment="本地收款银行账户")
    bank_reference = Column(String(128), nullable=True, comment="账户内唯一收款流水号")
    finance_status = Column(String(16), nullable=False, default="registered", server_default="registered", comment="registered/confirmed/voided")
    actual_bank_fee = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="银行实际扣费，与客户附加费用分开")
    net_amount = Column(Numeric(14, 2), nullable=True, comment="银行实际到账金额")
    allocated_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="有效核销金额累计")
    refunded_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="实际退款金额累计")
    rate_to_cny = Column(Numeric(18, 8), nullable=True, comment="登记时冻结原币兑人民币汇率")
    rate_to_usd = Column(Numeric(18, 8), nullable=True, comment="登记时冻结原币兑美元汇率，用于提成")
    confirmed_by = Column(Integer, nullable=True, comment="财务确认人 ID")
    confirmed_at = Column(DateTime, nullable=True, comment="财务确认北京时间")
    confirmed_date = Column(Date, nullable=True, comment="财务确认业务日；核销退款不得早于此日")
    bank_charge_total = Column(Numeric(14, 2), nullable=False, default=0)
    collection_date = Column(Date, nullable=False)
    payment_type = Column(String(64), nullable=False)
    remark = Column(String(500), nullable=False, default="")
    status = Column(String(16), nullable=False, default="active")
    request_key = Column(String(64), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=beijing_now)


class BatchAttachment(Base):
    __tablename__ = "ark_receipt_batch_attachments"
    batch_id = Column(BigInteger, ForeignKey("ark_receipt_batches.id"), primary_key=True)
    attachment_id = Column(String(32), ForeignKey("ark_receipt_attachments.id"), primary_key=True, unique=True)


class SettlementApplication(Base):
    __tablename__ = "ark_settlement_applications"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, index=True)
    receipt_id = Column(BigInteger, ForeignKey("ark_receipts.id"), nullable=False, index=True)
    component = Column(String(16), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    bank_charge = Column(Numeric(14, 2), nullable=False, default=0)
    released_amount = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="售后累计释放占用金额，保留原占用事实")
    released_bank_charge = Column(Numeric(14, 2), nullable=False, default=0, server_default="0", comment="售后累计释放客户附加费用")
    status = Column(String(16), nullable=False, default="reserved")
    created_at = Column(DateTime, nullable=False, default=beijing_now)
    __table_args__ = (UniqueConstraint("settlement_id", "receipt_id", "component", name="uq_settlement_application"),)

    @property
    def effective_amount(self):
        return 0 if self.status == "released" else self.amount - (self.released_amount or 0)

    @property
    def effective_bank_charge(self):
        return 0 if self.status == "released" else self.bank_charge - (self.released_bank_charge or 0)


class ShipmentOutbound(Base):
    __tablename__ = "ark_shipment_outbounds"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, unique=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False)
    outbound_no = Column(String(96), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    remote_line_snapshot = Column(JSON, nullable=True)
    remote_id = Column(String(64), nullable=True, unique=True)
    attempt_token = Column(String(64), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=beijing_now)
    verified_at = Column(DateTime, nullable=True)
    last_check_attempt_at = Column(DateTime, nullable=True)


class SettlementEvent(Base):
    __tablename__ = "ark_settlement_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    reason = Column(String(500), nullable=False, default="")
    actor_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=beijing_now)


class SettlementFundingAmendment(Base):
    __tablename__ = "ark_settlement_funding_amendments"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, unique=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False, index=True)
    receipt_id = Column(BigInteger, ForeignKey("ark_receipts.id"), nullable=False)
    request_key = Column(String(64), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    before_snapshot = Column(JSON, nullable=False, comment="升级前原结算、现金与运费完整快照")
    after_snapshot = Column(JSON, nullable=False, comment="升级后结算与资金分配完整快照")
    evidence = Column(JSON, nullable=False, comment="主单、首款、运费单及出库核验摘要")
    actor_id = Column(Integer, nullable=False)
    reason = Column(String(500), nullable=False)
    created_at = Column(DateTime, nullable=False, default=beijing_now)
