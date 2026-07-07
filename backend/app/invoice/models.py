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
    SmallInteger,
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
    order_type = Column(String(16), nullable=False, default="stock", comment="stock/production")
    customer_id = Column(String(64), nullable=False, comment="customer_info.company_id")
    customer_name = Column(String(256), nullable=False)
    contact_name = Column(String(256), nullable=True)
    contact_phone = Column(String(100), nullable=True)
    contact_email = Column(String(256), nullable=True)
    delivery_address = Column(Text, nullable=True)
    sales_user_id = Column(Integer, nullable=True)
    sales_user_name = Column(String(100), nullable=True)
    sales_phone = Column(String(100), nullable=True)
    sales_email = Column(String(256), nullable=True)
    invoice_date = Column(Date, nullable=False)
    currency = Column(String(16), nullable=False, default="USD")
    status = Column(String(32), nullable=False, default="draft", comment="draft/ready/synced/sync_failed")
    express_channel = Column(String(64), nullable=True)
    shipping_fee = Column(Numeric(14, 2), nullable=False, default=0)
    surcharge_name = Column(String(128), nullable=True)
    surcharge_amount = Column(Numeric(14, 2), nullable=False, default=0)
    payment_term = Column(String(256), nullable=True)
    product_amount = Column(Numeric(14, 2), nullable=False, default=0)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0)
    internal_payment_method = Column(String(64), nullable=True)
    internal_discount = Column(Numeric(14, 2), nullable=True)
    internal_accessory = Column(Numeric(14, 2), nullable=True)
    internal_received = Column(Numeric(14, 2), nullable=True)
    internal_balance = Column(Numeric(14, 2), nullable=True)
    internal_shipping_type = Column(String(64), nullable=True)
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
    item_type = Column(String(16), nullable=False, default="stock", comment="stock/custom")
    product_id = Column(BigInteger, nullable=True, comment="okki_products.product_id; NULL for custom lines")
    sku_id = Column(BigInteger, nullable=True, comment="okki_inventory.sku_id")
    custom_product_id = Column(BigInteger, nullable=True, comment="ark_custom_products.id")
    product_name = Column(String(512), nullable=False)
    product_display = Column(String(256), nullable=False)
    net_weight_grams = Column(String(64), nullable=False, comment="Mapped from okki_products.unit")
    curl = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)
    color = Column(String(128), nullable=False)
    length = Column(String(128), nullable=False, comment="Mapped from okki_products.size")
    quantity = Column(Integer, nullable=False)
    standard_price = Column(Numeric(12, 4), nullable=True, comment="matrix std price snapshot")
    customer_price = Column(Numeric(12, 4), nullable=True, comment="rule-adjusted price snapshot")
    price_per_piece = Column(Numeric(12, 4), nullable=True)
    total_price = Column(Numeric(14, 2), nullable=False, default=0)
    price_source = Column(String(32), nullable=False, default="manual", comment="customer_rule/manual/missing_std")
    xiaoman_unique_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="items")

    __table_args__ = (
        Index("idx_ark_invoice_items_invoice", "invoice_id"),
        Index("idx_ark_invoice_items_product", "product_id"),
        Index("idx_ark_invoice_items_custom", "custom_product_id"),
    )


class CustomProduct(Base):
    """Non-standard product sunk from production-order entry.

    Lives in the Ark DB on purpose: okki_products is a read-only projection
    maintained by the OKKI sync job, and product_id is cloud-assigned.
    """

    __tablename__ = "ark_custom_products"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    match_key = Column(String(512), nullable=False, unique=True, comment="normalize(display|model|color|size|unit)")
    product_display = Column(String(256), nullable=False)
    product_name = Column(String(512), nullable=False)
    model = Column(String(200), nullable=True)
    color = Column(String(128), nullable=False)
    size = Column(String(128), nullable=False)
    unit = Column(String(64), nullable=False)
    okki_product_id = Column(BigInteger, nullable=True, comment="backfilled once OKKI creates the real product")
    okki_sku_id = Column(BigInteger, nullable=True)
    use_count = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceColorType(Base):
    """Color code -> pricing color type (solid/piano/ombre/balayage)."""

    __tablename__ = "ark_price_color_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    color_code = Column(String(64), nullable=False, unique=True)
    color_type = Column(String(16), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class StdPrice(Base):
    """Standard reference price matrix (series+grade x length x weight x color type)."""

    __tablename__ = "ark_std_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_grade = Column(String(128), nullable=False)
    length = Column(String(32), nullable=False)
    weight_unit = Column(String(32), nullable=False)
    color_type = Column(String(16), nullable=False)
    price = Column(Numeric(12, 4), nullable=False)
    currency = Column(String(8), nullable=False, default="USD")
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CustomerPriceRule(Base):
    """Per-customer price adjustment: fixed delta or percent, exactly one mode."""

    __tablename__ = "ark_customer_price_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(64), nullable=False, unique=True, comment="customer_info.company_id")
    customer_name = Column(String(256), nullable=True)
    adjust_type = Column(String(16), nullable=False, comment="fixed/percent")
    adjust_value = Column(Numeric(12, 4), nullable=False, comment="signed")
    enabled = Column(SmallInteger, nullable=False, default=1)
    preferred_template = Column(String(8), nullable=True)
    remark = Column(String(512), nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class InvoiceSyncLog(Base):
    """Audit log for OKKI order push attempts."""

    __tablename__ = "ark_invoice_sync_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(16), nullable=False, comment="create/update/retry")
    success = Column(SmallInteger, nullable=False, default=0)
    request_digest = Column(Text, nullable=True)
    response_body = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    operator_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("idx_ark_invoice_sync_logs_inv", "invoice_id"),)


class XiaomanSettings(Base):
    """Single-row OKKI push settings, managed on the admin page."""

    __tablename__ = "ark_xiaoman_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generic_product_no = Column(String(64), nullable=True)
    generic_product_id = Column(BigInteger, nullable=True)
    generic_sku_id = Column(BigInteger, nullable=True)
    default_order_status = Column(String(64), nullable=True)
    default_currency = Column(String(8), nullable=False, default="USD")
    access_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

