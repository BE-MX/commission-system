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
    handling_amount = Column(Numeric(14, 2), nullable=False, default=0)
    currency = Column(String(16), nullable=False)
    customer_id = Column(String(64), nullable=False)
    remote_order_id = Column(String(64), nullable=True, unique=True)
    remote_status = Column(String(24), nullable=False, default="unverified")
    created_at = Column(DateTime, nullable=False, default=beijing_now)


class ReceiptBatch(Base):
    __tablename__ = "ark_receipt_batches"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    batch_no = Column(String(64), nullable=False, unique=True)
    customer_id = Column(String(64), nullable=False)
    currency = Column(String(16), nullable=False)
    gross_amount = Column(Numeric(14, 2), nullable=False)
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
    status = Column(String(16), nullable=False, default="reserved")
    created_at = Column(DateTime, nullable=False, default=beijing_now)
    __table_args__ = (UniqueConstraint("settlement_id", "receipt_id", "component", name="uq_settlement_application"),)


class ShipmentOutbound(Base):
    __tablename__ = "ark_shipment_outbounds"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, unique=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), nullable=False)
    outbound_no = Column(String(96), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    payload = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    remote_id = Column(String(64), nullable=True, unique=True)
    attempt_token = Column(String(64), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=beijing_now)
    verified_at = Column(DateTime, nullable=True)


class SettlementEvent(Base):
    __tablename__ = "ark_settlement_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    settlement_id = Column(BigInteger, ForeignKey("ark_shipment_settlements.id"), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    reason = Column(String(500), nullable=False, default="")
    actor_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=beijing_now)
