"""SQLAlchemy models for order invoice management."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class Invoice(Base):
    """Invoice header stored in the Ark database."""

    __tablename__ = "ark_invoices"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_no = Column(String(64), nullable=False, unique=True, comment="Invoice number")
    customer_id = Column(String(64), nullable=False, comment="customer_info.company_id")
    customer_name = Column(String(256), nullable=False)
    invoice_date = Column(Date, nullable=False)
    currency = Column(String(16), nullable=False, default="USD")
    status = Column(String(32), nullable=False, default="draft", comment="draft/ready/synced/sync_failed")
    total_amount = Column(Numeric(14, 2), nullable=False, default=0)
    remark = Column(Text, nullable=True)
    xiaoman_order_id = Column(String(64), nullable=True)
    xiaoman_order_no = Column(String(64), nullable=True)
    sync_status = Column(String(32), nullable=False, default="not_synced")
    sync_error = Column(Text, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceItem.sort_order",
    )

    __table_args__ = (
        Index("idx_ark_invoices_customer", "customer_id"),
        Index("idx_ark_invoices_status", "status"),
        Index("idx_ark_invoices_created_at", "created_at"),
    )


class InvoiceItem(Base):
    """Invoice product line."""

    __tablename__ = "ark_invoice_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="CASCADE"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    product_id = Column(BigInteger, nullable=False, comment="okki_products.product_id")
    sku_id = Column(BigInteger, nullable=True, comment="okki_inventory.sku_id")
    product_name = Column(String(512), nullable=False)
    product_display = Column(String(256), nullable=False)
    net_weight_grams = Column(String(64), nullable=False, comment="Mapped from okki_products.unit")
    curl = Column(String(64), nullable=True)
    model = Column(String(128), nullable=False)
    color = Column(String(128), nullable=False)
    length = Column(String(128), nullable=False, comment="Mapped from okki_products.size")
    quantity = Column(Integer, nullable=False)
    price_per_piece = Column(Numeric(12, 4), nullable=True)
    total_price = Column(Numeric(14, 2), nullable=False, default=0)
    price_source = Column(String(32), nullable=False, default="manual")
    xiaoman_unique_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="items")

    __table_args__ = (
        Index("idx_ark_invoice_items_invoice", "invoice_id"),
        Index("idx_ark_invoice_items_product", "product_id"),
    )

