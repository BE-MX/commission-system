"""Immutable order snapshots and permanent invoice lineage."""

from sqlalchemy import (BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Integer, JSON, Numeric, String, UniqueConstraint)

from app.core.database import Base
from app.portal.model_base import ID, PREFIX, Record, Versioned, employee, reference


class Quote(Record, Base):
    __tablename__ = PREFIX + "quotes"
    access_id = reference("customer_access")
    account_id = reference("accounts")
    membership_id = reference("memberships")
    status = Column(String(16), nullable=False, default="valid", comment='受服务层状态机约束的业务状态')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    authority_versions_json = Column(JSON, nullable=False, comment='报价与提案依赖的权威版本快照')
    input_hash = Column(String(64), nullable=False, comment='规范化请求载荷摘要')
    result_hash = Column(String(64), nullable=False, comment='服务端报价结果摘要')
    currency = Column(String(3), nullable=False, comment='结算币种')
    product_amount = Column(Numeric(14, 2), nullable=False, comment='商品合计，不含费用')
    fees_status = Column(String(16), nullable=False, default="pending", comment='费用待确认或已确认')
    total_amount = Column(Numeric(14, 2), comment='总金额，费用未知时必须为空')
    lines_json = Column(JSON, nullable=False, comment='标准SKU和客户展示的报价明细快照')
    delivery_json = Column(JSON, nullable=False, comment='已确认收货资料快照')
    payment_terms_snapshot = Column(JSON, nullable=False, comment='受控付款条款快照')
    customer_po = Column(String(80), nullable=False, default="", comment='客户采购单号')
    remark = Column(String(1000), nullable=False, default="", comment='对外订单备注')
    __table_args__ = (
        UniqueConstraint("id", "access_id", "account_id", name="uq_op_quote_identity"),
        ForeignKeyConstraint(["membership_id", "access_id", "account_id"], [PREFIX + "memberships.id", PREFIX + "memberships.access_id", PREFIX + "memberships.account_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('valid','consumed','expired')", name="ck_op_quote_state"),
        CheckConstraint("fees_status IN ('pending','confirmed')", name="ck_op_quote_fees"),
    )


class OrderRequest(Record, Versioned, Base):
    __tablename__ = PREFIX + "requests"
    access_id = reference("customer_access")
    account_id = reference("accounts")
    customer_id_snapshot = Column(ID, nullable=False, comment='提交时方舟客户ID快照')
    okki_company_id_snapshot = Column(String(64), nullable=False, comment='提交时小满客户ID快照')
    sales_user_id_snapshot = employee()
    servicing_user_id = employee()
    public_no = Column(String(64), nullable=False, unique=True, comment='门户可读请求单号')
    idempotency_key = Column(String(36), nullable=False, comment='客户提交意图UUID')
    client_payload_hash = Column(String(64), nullable=False, comment='同键载荷冲突校验摘要')
    quote_id = reference("quotes", unique=True)
    status = Column(String(24), nullable=False, default="submitted", comment='受服务层状态机约束的业务状态')
    active_revision_id = reference("revisions", nullable=True)
    accepted_revision_id = reference("revisions", nullable=True)
    invoice_id = Column(ID, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), unique=True, comment='唯一关联方舟发票，不允许破坏引用删除')
    customer_po = Column(String(80), nullable=False, default="", comment='客户采购单号')
    submitted_at = Column(DateTime, nullable=False, comment='客户请求提交时间')
    __table_args__ = (
        UniqueConstraint("access_id", "account_id", "idempotency_key", name="uq_op_request_key"),
        UniqueConstraint("id", "access_id", name="uq_op_request_access"),
        ForeignKeyConstraint(["quote_id", "access_id", "account_id"], [PREFIX + "quotes.id", PREFIX + "quotes.access_id", PREFIX + "quotes.account_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["active_revision_id", "id"], [PREFIX + "revisions.id", PREFIX + "revisions.request_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["accepted_revision_id", "id"], [PREFIX + "revisions.id", PREFIX + "revisions.request_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["id", "invoice_id"], [PREFIX + "conversions.request_id", PREFIX + "conversions.invoice_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('submitted','awaiting_customer','ready_for_review','invoice_created','rejected','cancelled')", name="ck_op_request_status"),
        Index("ix_op_request_access_submitted", "access_id", "submitted_at", "id"),
        Index("ix_op_request_servicing_status", "servicing_user_id", "status", "id"),
    )


class Revision(Record, Base):
    __tablename__ = PREFIX + "revisions"
    request_id = reference("requests")
    revision_no = Column(Integer, nullable=False, comment='单请求内递增修订编号')
    kind = Column(String(16), nullable=False, comment='首次请求、提案或PI后续修订')
    currency = Column(String(3), nullable=False, comment='结算币种')
    product_amount = Column(Numeric(14, 2), nullable=False, comment='商品合计，不含费用')
    shipping_amount = Column(Numeric(14, 2), comment='确认运费，未知为空')
    packaging_amount = Column(Numeric(14, 2), comment='确认包装费，数量不乘金额')
    surcharge_amount = Column(Numeric(14, 2), comment='确认附加费')
    surcharge_name = Column(String(100), nullable=False, default="", comment='附加费对外名称')
    total_amount = Column(Numeric(14, 2), comment='总金额，费用未知时必须为空')
    fees_status = Column(String(16), nullable=False, comment='费用待确认或已确认')
    delivery_json = Column(JSON, nullable=False, comment='已确认收货资料快照')
    payment_terms_snapshot = Column(JSON, nullable=False, comment='受控付款条款快照')
    expires_at = Column(DateTime, nullable=False, comment='有效期截止，北京时间')
    authority_versions_json = Column(JSON, nullable=False, comment='报价与提案依赖的权威版本快照')
    remark = Column(String(1000), nullable=False, default="", comment='对外订单备注')
    mapping_version = Column(BigInteger, nullable=False, comment='客户展示映射版本')
    pricing_fingerprint = Column(String(64), nullable=False, comment='定价依据快照摘要')
    content_hash = Column(String(64), nullable=False, comment='不可变交易内容摘要')
    bound_invoice_document_version = Column(BigInteger, comment='PI后续提案绑定的文档版本')
    invoice_presentation_json = Column(JSON, nullable=True, comment='PI后续修订的客户可见商业抬头快照')
    customer_accepted_by = reference("accounts", nullable=True)
    customer_accepted_at = Column(DateTime, comment='客户首次接受本修订的时间')
    created_by = employee(nullable=True)
    __table_args__ = (
        UniqueConstraint("request_id", "revision_no", name="uq_op_revision_number"),
        UniqueConstraint("id", "request_id", name="uq_op_revision_request"),
        CheckConstraint("kind IN ('submitted','proposal','pi_amendment')", name="ck_op_revision_kind"),
        CheckConstraint("fees_status IN ('pending','confirmed')", name="ck_op_revision_fees"),
        CheckConstraint("(customer_accepted_by IS NULL AND customer_accepted_at IS NULL) OR (customer_accepted_by IS NOT NULL AND customer_accepted_at IS NOT NULL)", name="ck_op_revision_acceptance"),
    )


class RequestLine(Record, Base):
    __tablename__ = PREFIX + "request_lines"
    revision_id = reference("revisions")
    line_key = Column(String(36), nullable=False, comment='跨发布快照的稳定明细UUID')
    catalog_item_id = reference("catalog_items")
    product_kind = Column(String(16), nullable=False, comment='标准商品类别，发品或配件')
    product_id = Column(String(64), nullable=False, comment='标准商品ID，按字符串存储')
    sku_id = Column(String(64), nullable=False, comment='标准规格ID，按字符串存储')
    standard_json = Column(JSON, nullable=False, comment='不可被客户别名覆盖的标准属性')
    customer_display_json = Column(JSON, nullable=False, comment='客户型号颜色货号展示快照')
    mapping_version = Column(BigInteger, nullable=False, comment='客户展示映射版本')
    qty = Column(Integer, nullable=False, comment='标准销售单位数量')
    unit_price = Column(Numeric(12, 4), nullable=False, comment='四位精度标准单价')
    discount_amount = Column(Numeric(14, 2), nullable=False, default=0, comment='非正折扣金额')
    line_amount = Column(Numeric(14, 2), nullable=False, comment='先舍入毛额再加折扣的行额')
    unit_weight_grams = Column(Numeric(14, 6), comment='每销售单位标准克重')
    price_source = Column(String(64), nullable=False, comment='服务器定价来源')
    price_fingerprint = Column(String(64), nullable=False, comment='本行定价依据摘要')
    __table_args__ = (
        UniqueConstraint("revision_id", "line_key", name="uq_op_line_key"),
        UniqueConstraint("revision_id", "catalog_item_id", name="uq_op_line_item"),
        UniqueConstraint("revision_id", "product_id", "sku_id", name="uq_op_line_sku"),
        CheckConstraint("qty > 0 AND qty <= 10000 AND unit_price > 0 AND discount_amount <= 0 AND line_amount >= 0", name="ck_op_line_values"),
    )


class Conversion(Record, Base):
    __tablename__ = PREFIX + "conversions"
    request_id = reference("requests", unique=True)
    approved_revision_id = reference("revisions")
    operation_key = Column(String(64), nullable=False, unique=True, comment='永久建票操作键')
    payload_hash = Column(String(64), nullable=False, comment='命令规范化载荷摘要')
    invoice_id = Column(ID, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), unique=True, comment='唯一关联方舟发票，不允许破坏引用删除')
    invoice_document_version = Column(BigInteger, comment='对应发票portal_document_version')
    status = Column(String(16), nullable=False, default="pending", comment='受服务层状态机约束的业务状态')
    created_by = employee()
    __table_args__ = (
        UniqueConstraint("request_id", "invoice_id", name="uq_op_conversion_binding"),
        ForeignKeyConstraint(["approved_revision_id", "request_id"], [PREFIX + "revisions.id", PREFIX + "revisions.request_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('pending','created','tombstoned')", name="ck_op_conversion_status"),
    )


class PiAmendment(Record, Versioned, Base):
    __tablename__ = PREFIX + "pi_amendments"
    request_id = reference("requests", unique=True)
    invoice_id = Column(ID, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), nullable=False, unique=True, comment='唯一关联方舟发票，不允许破坏引用删除')
    status = Column(String(24), nullable=False, default="current", comment='受服务层状态机约束的业务状态')
    active_revision_id = reference("revisions", nullable=True)
    accepted_revision_id = reference("revisions", nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["request_id", "invoice_id"], [PREFIX + "conversions.request_id", PREFIX + "conversions.invoice_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["active_revision_id", "request_id"], [PREFIX + "revisions.id", PREFIX + "revisions.request_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["accepted_revision_id", "request_id"], [PREFIX + "revisions.id", PREFIX + "revisions.request_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('current','withdrawn','pending_customer','accepted')", name="ck_op_amendment_state"),
    )


class Publication(Record, Base):
    __tablename__ = PREFIX + "publications"
    request_id = reference("requests")
    invoice_id = Column(ID, ForeignKey("ark_invoices.id", ondelete="RESTRICT"), nullable=False, comment='唯一关联方舟发票，不允许破坏引用删除')
    invoice_document_version = Column(BigInteger, nullable=False, comment='对应发票portal_document_version')
    revision_id = reference("revisions")
    content_hash = Column(String(64), nullable=False, comment='不可变交易内容摘要')
    customer_snapshot_json = Column(JSON, nullable=False, comment='获准对外提供的PI不可变快照')
    render_template_version = Column(String(32), nullable=False, comment='PI渲染模板版本')
    status = Column(String(16), nullable=False, default="published", comment='受服务层状态机约束的业务状态')
    published_by = employee()
    published_at = Column(DateTime, nullable=False, comment='正式发布的北京时间')
    __table_args__ = (
        UniqueConstraint("invoice_id", "invoice_document_version", name="uq_op_publication_version"),
        ForeignKeyConstraint(["request_id", "invoice_id"], [PREFIX + "conversions.request_id", PREFIX + "conversions.invoice_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["revision_id", "request_id"], [PREFIX + "revisions.id", PREFIX + "revisions.request_id"], ondelete="RESTRICT"),
        CheckConstraint("status IN ('published','withdrawn')", name="ck_op_publication_status"),
    )


class CommandReceipt(Record, Base):
    __tablename__ = PREFIX + "command_receipts"
    action = Column(String(32), nullable=False, comment='受控操作类型')
    object_public_id = Column(String(36), nullable=False, comment='目标对象公开ID')
    command_key = Column(String(160), nullable=False, comment='成功命令稳定身份')
    payload_hash = Column(String(64), nullable=False, comment='命令规范化载荷摘要')
    result_reference_json = Column(JSON, nullable=False, comment='成功结果引用，不保存完整敏感响应')
    first_actor_type = Column(String(16), nullable=False, comment='首次成功操作者类型')
    first_actor_id = Column(ID, nullable=False, comment='首次成功操作者ID')
    completed_at = Column(DateTime, nullable=False, comment='命令成功完成时间')
    __table_args__ = (UniqueConstraint("action", "object_public_id", "command_key", name="uq_op_command_receipt"),)
