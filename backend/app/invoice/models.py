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

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    invoice_no = Column(String(64), nullable=False, unique=True, comment="Invoice number")
    order_type = Column(String(16), nullable=False, default="stock", comment="stock/production")
    customer_id = Column(String(64), nullable=False, comment="customer_info.company_id")
    customer_name = Column(String(256), nullable=False, comment="客户名称")
    contact_name = Column(String(256), nullable=True, comment="联系人姓名快照")
    contact_phone = Column(String(100), nullable=True, comment="联系人电话快照")
    contact_email = Column(String(256), nullable=True, comment="联系人邮箱快照")
    delivery_address = Column(Text, nullable=True, comment="收货地址")
    sales_user_id = Column(Integer, nullable=True, comment="业务员用户ID（ark_users.id）")
    sales_user_name = Column(String(100), nullable=True, comment="业务员姓名快照")
    sales_phone = Column(String(100), nullable=True, comment="业务员电话快照")
    sales_email = Column(String(256), nullable=True, comment="业务员邮箱快照")
    invoice_date = Column(Date, nullable=False, comment="发票日期")
    currency = Column(String(16), nullable=False, default="USD", comment="币种，默认 USD")
    status = Column(String(32), nullable=False, default="draft", comment="draft/ready/synced/sync_failed")
    express_channel = Column(String(64), nullable=True, comment="DHL/FedEx...")
    shipping_fee = Column(Numeric(14, 2), nullable=False, default=0, comment="运费（发票币种，计入总额）")
    surcharge_name = Column(String(128), nullable=True, comment="e.g. Paypal Surcharge")
    surcharge_amount = Column(Numeric(14, 2), nullable=False, default=0, comment="附加费金额（发票币种，计入总额）")
    payment_term = Column(String(256), nullable=True, comment="付款条款")
    product_amount = Column(Numeric(14, 2), nullable=False, default=0, comment="sum of item totals, before fees")
    total_amount = Column(Numeric(14, 2), nullable=False, default=0, comment="发票总额=产品金额+运费+附加费（发票币种）")
    internal_payment_method = Column(String(64), nullable=True, comment="内部结算-付款方式（不出现在发票）")
    internal_discount = Column(Numeric(14, 2), nullable=True, comment="内部结算-折扣金额（发票币种）")
    internal_accessory = Column(Numeric(14, 2), nullable=True, comment="内部结算-配件金额（发票币种）")
    internal_received = Column(Numeric(14, 2), nullable=True, comment="内部结算-已收金额（发票币种）")
    internal_balance = Column(Numeric(14, 2), nullable=True, comment="内部结算-尾款金额（发票币种）")
    internal_shipping_type = Column(String(64), nullable=True, comment="内部结算-发货方式")
    remark = Column(Text, nullable=True, comment="备注")
    xiaoman_order_id = Column(String(64), nullable=True, comment="OKKI 订单ID")
    xiaoman_order_no = Column(String(64), nullable=True, comment="OKKI 订单编号")
    sync_status = Column(String(32), nullable=False, default="not_synced", comment="OKKI 推单状态 not_synced/synced/sync_failed")
    xiaoman_removed_lines = Column(Text, nullable=True, comment="已推OKKI后本地删除的明细快照JSON[{unique_id,product_id,sku_id}]，下次推单发remove:1，成功后清空")
    sync_error = Column(Text, nullable=True, comment="最近一次推单失败信息")
    synced_at = Column(DateTime, nullable=True, comment="最近成功推单时间")
    created_by = Column(Integer, nullable=True, comment="创建人 user_id")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

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
        {"comment": "订单发票主表（库存单/生产单，含 OKKI 推单状态）"},
    )


class InvoiceItem(Base):
    """Invoice product line."""

    __tablename__ = "ark_invoice_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="CASCADE"), nullable=False, comment="关联发票ID（ark_invoices.id）")
    sort_order = Column(Integer, nullable=False, default=0, comment="明细行排序号")
    item_type = Column(String(16), nullable=False, default="stock", comment="stock/custom")
    product_id = Column(BigInteger, nullable=True, comment="okki_products.product_id; NULL for custom lines")
    sku_id = Column(BigInteger, nullable=True, comment="okki_inventory.sku_id")
    custom_product_id = Column(BigInteger, nullable=True, comment="ark_custom_products.id, no FK by design")
    product_name = Column(String(512), nullable=False, comment="产品全名（display/size/color/unit 组合）")
    product_display = Column(String(256), nullable=False, comment="发票 Product 列展示名（series+grade）")
    net_weight_grams = Column(String(64), nullable=False, comment="Mapped from okki_products.unit")
    curl = Column(String(64), nullable=True, comment="卷度")
    model = Column(String(128), nullable=True, comment="production model; optional for custom lines")
    color = Column(String(128), nullable=False, comment="颜色/色号")
    length = Column(String(128), nullable=False, comment="Mapped from okki_products.size")
    quantity = Column(Integer, nullable=False, comment="数量（件）")
    standard_price = Column(Numeric(12, 4), nullable=True, comment="matrix std price snapshot")
    customer_price = Column(Numeric(12, 4), nullable=True, comment="rule-adjusted price snapshot")
    price_per_piece = Column(Numeric(12, 4), nullable=True, comment="成交单价/件（发票币种，最终计价口径）")
    total_price = Column(Numeric(14, 2), nullable=False, default=0, comment="行小计=成交单价×数量（发票币种）")
    price_source = Column(String(32), nullable=False, default="manual", comment="customer_rule/manual/missing_std")
    xiaoman_unique_id = Column(String(64), nullable=True, comment="OKKI 明细行唯一ID")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    invoice = relationship("Invoice", back_populates="items")

    __table_args__ = (
        Index("idx_ark_invoice_items_invoice", "invoice_id"),
        Index("idx_ark_invoice_items_product", "product_id"),
        Index("idx_ark_invoice_items_custom", "custom_product_id"),
        {"comment": "发票产品明细行（标准价/客户价双价快照）"},
    )


class CustomProduct(Base):
    """Non-standard product sunk from production-order entry.

    Lives in the Ark DB on purpose: okki_products is a read-only projection
    maintained by the OKKI sync job, and product_id is cloud-assigned.
    """

    __tablename__ = "ark_custom_products"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    match_key = Column(String(512), nullable=False, unique=True, comment="normalize(display|model|color|size|unit)")
    product_display = Column(String(256), nullable=False, comment="series+grade, invoice Product column")
    product_name = Column(String(512), nullable=False, comment="display/size/color/unit, mirrors okki naming")
    model = Column(String(200), nullable=True, comment="型号")
    color = Column(String(128), nullable=False, comment="颜色/色号")
    size = Column(String(128), nullable=False, comment="尺寸/长度")
    unit = Column(String(64), nullable=False, comment="单位（克重，如 20g）")
    okki_product_id = Column(BigInteger, nullable=True, comment="OKKI 建品后回填的真实产品ID")
    okki_sku_id = Column(BigInteger, nullable=True, comment="OKKI SKU ID（对账回填）")
    use_count = Column(Integer, nullable=False, default=1, comment="被引用次数")
    created_by = Column(Integer, nullable=True, comment="创建人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = ({"comment": "非标产品沉淀表（生产单录入沉淀，OKKI 建品后回填 ID）"},)


class PriceColorType(Base):
    """Color code -> pricing color type (solid/piano/ombre/balayage)."""

    __tablename__ = "ark_price_color_types"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    color_code = Column(String(64), nullable=False, unique=True, comment="色号，唯一")
    color_type = Column(String(16), nullable=False, comment="solid/piano/ombre/balayage")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = ({"comment": "色号→计价颜色类型映射表"},)


class StdPrice(Base):
    """Standard reference price matrix (series+grade x length x weight x color type)."""

    __tablename__ = "ark_std_prices"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    series_grade = Column(String(128), nullable=False, comment="e.g. Super Double Drawn Genius")
    length = Column(String(32), nullable=False, comment="normalized, inch mark stripped")
    weight_unit = Column(String(32), nullable=False, comment="e.g. 20g")
    color_type = Column(String(16), nullable=False, comment="计价颜色类型 solid/piano/ombre/balayage")
    price = Column(Numeric(12, 4), nullable=False, comment="标准参考单价/件（currency 币种，客户价调整前基准）")
    currency = Column(String(8), nullable=False, default="USD", comment="币种，默认 USD")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = ({"comment": "标准价格矩阵（系列档次×长度×克重×颜色类型）"},)


class CustomerPriceRule(Base):
    """Per-customer price adjustment: fixed delta or percent, exactly one mode."""

    __tablename__ = "ark_customer_price_rules"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(String(64), nullable=False, unique=True, comment="customer_info.company_id")
    customer_name = Column(String(256), nullable=True, comment="客户名称快照")
    adjust_type = Column(String(16), nullable=False, comment="fixed/percent")
    adjust_value = Column(Numeric(12, 4), nullable=False, comment="有符号调价值：fixed=差价金额(发票币种,+2=加2/-3=减3)；percent=百分数(5=+5%)——与提成 0.02=2% 的小数口径不同")
    enabled = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=禁用")
    preferred_template = Column(String(8), nullable=True, comment="invoice export template A/B")
    remark = Column(String(512), nullable=True, comment="备注")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = ({"comment": "客户价格调整规则（固定差价/百分比二选一，作用于标准价）"},)


class InvoiceSyncLog(Base):
    """Audit log for OKKI order push attempts."""

    __tablename__ = "ark_invoice_sync_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id", ondelete="CASCADE"), nullable=False, comment="关联发票ID（ark_invoices.id）")
    action = Column(String(16), nullable=False, comment="create/update/retry")
    success = Column(SmallInteger, nullable=False, default=0, comment="1=成功,0=失败")
    request_digest = Column(Text, nullable=True, comment="sanitized request summary")
    response_body = Column(Text, nullable=True, comment="OKKI 响应原文")
    error_message = Column(Text, nullable=True, comment="失败错误信息")
    operator_id = Column(Integer, nullable=True, comment="操作人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_ark_invoice_sync_logs_inv", "invoice_id"),
        {"comment": "OKKI 推单审计日志"},
    )


class ReceiptRepairLog(Base):
    """Audit trail for collection_date fixes written into the read-only business
    mirror (lsordertest.okki_receipts).

    Business rule: okki_receipts is externally synced and treated read-only; this
    tool is the only writer of collection_date. We record old_date → new_date per
    receipt so every write is reversible. A batch_id groups one apply run.
    """

    __tablename__ = "ark_receipt_repair_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    batch_id = Column(String(40), nullable=False, comment="uuid per apply run")
    cash_collection_id = Column(String(64), nullable=False, comment="okki_receipts PK")
    order_no = Column(String(64), nullable=True, comment="订单编号（辅助核对）")
    company_name = Column(String(256), nullable=True, comment="客户公司名称（辅助核对）")
    old_date = Column(Date, nullable=True, comment="collection_date before fix")
    new_date = Column(Date, nullable=False, comment="collection_date after fix")
    source_file = Column(String(256), nullable=True, comment="uploaded workbook name")
    operator_id = Column(Integer, nullable=True, comment="操作人 user_id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_ark_receipt_repair_batch", "batch_id"),
        Index("idx_ark_receipt_repair_ccid", "cash_collection_id"),
        {"comment": "回款日期修复审计日志（okki_receipts.collection_date 每次改写可回溯）"},
    )


class XiaomanSettings(Base):
    """Single-row OKKI push settings, managed on the admin page."""

    __tablename__ = "ark_xiaoman_settings"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    generic_product_no = Column(String(64), nullable=True, comment="OKKI product_no of the generic product")
    generic_product_id = Column(BigInteger, nullable=True, comment="resolved from okki_products")
    generic_sku_id = Column(BigInteger, nullable=True, comment="通用产品 SKU ID（OKKI）")
    default_order_status = Column(String(64), nullable=True, comment="from orderEnums")
    default_currency = Column(String(8), nullable=False, default="USD", comment="推单默认币种，默认 USD")
    access_token = Column(Text, nullable=True, comment="OKKI API access token")
    token_expires_at = Column(DateTime, nullable=True, comment="access_token 过期时间")
    updated_by = Column(Integer, nullable=True, comment="最后修改人 user_id")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="最后修改时间")

    __table_args__ = ({"comment": "OKKI 推单设置（单行表，后台管理页维护）"},)

