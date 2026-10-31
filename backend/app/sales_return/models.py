"""Append-only effects keep returns independent of the remote receipt outbox."""
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, event

from app.core.database import Base
from app.core.time import beijing_now


class SalesReturn(Base):
    __tablename__ = "ark_sales_returns"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_no = Column(String(64), nullable=False, unique=True, comment='退货单号')
    order_id = Column(String(64), nullable=False, index=True, comment='原小满订单 ID')
    order_no = Column(String(128), nullable=False, comment='原订单号快照')
    invoice_id = Column(BigInteger, ForeignKey("ark_invoices.id"), comment='可选关联方舟发票 ID')
    customer_id = Column(String(64), nullable=False, index=True, comment='原客户 ID')
    customer_name = Column(String(256), nullable=False, comment='原客户名称快照')
    owner_okki_user_id = Column(String(64), nullable=False, index=True, comment='原订单业务员 OKKI ID')
    sales_user_id = Column(Integer, comment='方舟业务员 ID 快照')
    return_type = Column(String(24), nullable=False, comment='退货退款或仅退款')
    currency = Column(String(16), nullable=False, comment='订单原币')
    reduction_amount = Column(Numeric(14, 2), nullable=False, default=0, comment='商品货款冲减原币金额')
    refund_amount = Column(Numeric(14, 2), nullable=False, default=0, comment='实际退款原币金额')
    waived_amount = Column(Numeric(14, 2), nullable=False, default=0, comment='未收款减免原币金额')
    reason_code = Column(String(32), nullable=False, comment='原因字典编码')
    reason = Column(Text, nullable=False, comment='原因说明')
    status = Column(String(16), nullable=False, default="draft", index=True, comment='退货业务状态')
    cash_status = Column(String(16), nullable=False, default="not_paid", comment='实际资金执行状态')
    cash_evidence = Column(JSON, nullable=False, default=list, comment='资金支付及收回证据')
    snapshot = Column(JSON, nullable=False, default=dict, comment='原单与资金冻结证据')
    request_key = Column(String(64), nullable=False, unique=True, comment='提交幂等键')
    request_hash = Column(String(64), nullable=False, comment='提交内容摘要')
    activate_key = Column(String(64), unique=True, comment='生效幂等键')
    activate_hash = Column(String(64), comment='生效提交内容摘要')
    reverse_key = Column(String(64), unique=True, comment='反向更正幂等键')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')
    created_by = Column(Integer, nullable=False, comment='创建人方舟 ID')
    activated_by = Column(Integer, comment='生效操作人方舟 ID')
    effective_date = Column(Date, index=True, comment='生效业务日，北京时间')
    effective_at = Column(DateTime, comment='生效时间，北京时间')
    reversed_at = Column(DateTime, comment='反向更正时间，北京时间')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment='更新时间，北京时间')


class ReturnItem(Base):
    __tablename__ = "ark_sales_return_items"
    __table_args__ = (UniqueConstraint("return_id", "source_key", name="uq_sales_return_source_line"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_id = Column(BigInteger, ForeignKey("ark_sales_returns.id"), nullable=False, index=True, comment='关联退货单 ID')
    source_key = Column(String(160), nullable=False, comment='原出库行稳定身份')
    outbound_id = Column(String(64), nullable=False, comment='原出库单 ID')
    outbound_line_id = Column(String(64), nullable=False, comment='原出库明细 ID')
    order_line_id = Column(String(64), nullable=False, comment='原订单明细 ID')
    product_id = Column(String(64), nullable=False, comment='原产品 ID')
    sku_id = Column(String(64), nullable=False, comment='原 SKU ID')
    product_name = Column(String(256), nullable=False, comment='产品名称快照')
    specification = Column(String(500), nullable=False, default="", comment='产品规格快照')
    quantity = Column(Integer, nullable=False, comment='本次计划或实收数量')
    reduction_amount = Column(Numeric(14, 2), nullable=False, comment='商品货款冲减原币金额')
    reduction_usd = Column(Numeric(14, 2), nullable=False, comment='商品货款冲减美元金额')
    source_snapshot = Column(JSON, nullable=False, comment='原出库行冻结证据')


class ReturnOrderGuard(Base):
    __tablename__ = "ark_sales_return_order_guards"
    order_id = Column(String(64), primary_key=True, comment='原小满订单 ID')
    version = Column(Integer, nullable=False, default=1, comment='乐观并发版本')


class ReturnReceipt(Base):
    __tablename__ = "ark_return_receipts"
    __table_args__ = (UniqueConstraint("return_id", "effect_kind", name="uq_return_receipt_effect"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_id = Column(BigInteger, ForeignKey("ark_sales_returns.id"), nullable=False, index=True, comment='关联退货单 ID')
    receipt_no = Column(String(64), nullable=False, unique=True, comment='本地负数回款单号')
    effect_kind = Column(String(16), nullable=False, comment='生效或冲销事实类型')
    original_receipt_id = Column(BigInteger, ForeignKey("ark_return_receipts.id"), comment='关联原本地负数回款 ID')
    order_id = Column(String(64), nullable=False, index=True, comment='原小满订单 ID')
    customer_id = Column(String(64), nullable=False, index=True, comment='原客户 ID')
    currency = Column(String(16), nullable=False, comment='订单原币')
    amount = Column(Numeric(14, 2), nullable=False, comment='原币有符号金额')
    amount_usd = Column(Numeric(14, 2), nullable=False, comment='美元有符号金额')
    collection_date = Column(Date, nullable=False, index=True, comment='回款业务日期，北京时间')
    created_by = Column(Integer, nullable=False, comment='创建人方舟 ID')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')


class ReturnAllocation(Base):
    __tablename__ = "ark_sales_return_allocations"
    __table_args__ = (UniqueConstraint("return_id", "original_payment_id", name="uq_return_original_payment"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_id = Column(BigInteger, ForeignKey("ark_sales_returns.id"), nullable=False, index=True, comment='关联退货单 ID')
    original_payment_id = Column(String(64), nullable=False, index=True, comment='原回款稳定业务 ID')
    original_principal = Column(Numeric(14, 2), nullable=False, comment='原可退款本金原币金额')
    original_principal_usd = Column(Numeric(14, 2), nullable=False, comment='原可退款本金美元金额')
    refund_amount = Column(Numeric(14, 2), nullable=False, comment='实际退款原币金额')
    refund_amount_usd = Column(Numeric(14, 2), nullable=False, comment='本次实际退款美元本金')
    basis = Column(JSON, nullable=False, default=dict, comment='原人员及实际提成依据快照')
    funding = Column(JSON, nullable=False, default=list, comment='原回款和预售批次资金分摊')


class ReturnEffect(Base):
    __tablename__ = "ark_sales_return_effects"
    __table_args__ = (UniqueConstraint("return_id", "effect_kind", name="uq_sales_return_effect"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_id = Column(BigInteger, ForeignKey("ark_sales_returns.id"), nullable=False, index=True, comment='关联退货单 ID')
    effect_kind = Column(String(16), nullable=False, comment='生效或冲销事实类型')
    order_id = Column(String(64), nullable=False, index=True, comment='原小满订单 ID')
    owner_okki_user_id = Column(String(64), nullable=False, index=True, comment='原订单业务员 OKKI ID')
    customer_id = Column(String(64), nullable=False, comment='原客户 ID')
    currency = Column(String(16), nullable=False, comment='订单原币')
    amount = Column(Numeric(14, 2), nullable=False, comment='原币有符号金额')
    amount_usd = Column(Numeric(14, 2), nullable=False, comment='美元有符号金额')
    effective_date = Column(Date, nullable=False, index=True, comment='生效业务日，北京时间')
    gmv_eligible = Column(Integer, nullable=False, comment='原 GMV 计入资格')
    order_role = Column(String(24), nullable=False, comment='原新签或复购分类')
    departments = Column(JSON, nullable=False, default=list, comment='原部门及分摊比例快照')
    snapshot = Column(JSON, nullable=False, default=dict, comment='原单与资金冻结证据')


class ReturnReceiving(Base):
    __tablename__ = "ark_sales_return_receivings"
    __table_args__ = (UniqueConstraint("request_key", name="uq_return_receiving_request"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_id = Column(BigInteger, ForeignKey("ark_sales_returns.id"), nullable=False, index=True, comment='关联退货单 ID')
    item_id = Column(BigInteger, ForeignKey("ark_sales_return_items.id"), nullable=False, comment='关联退货产品明细 ID')
    quantity = Column(Integer, nullable=False, comment='本次计划或实收数量')
    accepted_quantity = Column(Integer, nullable=False, comment='实收检验合格件数')
    rejected_quantity = Column(Integer, nullable=False, comment='实收检验不合格件数')
    pending_quantity = Column(Integer, nullable=False, comment='实收待检件数')
    stock_status = Column(String(24), nullable=False, default="not_stocked", comment='权威库存入账核验状态')
    stock_reference = Column(String(128), comment='权威入库单引用')
    version = Column(Integer, nullable=False, default=1, comment="收货检验乐观并发版本")
    evidence = Column(JSON, nullable=False, default=dict, comment='收货检验及入库证据')
    request_key = Column(String(64), nullable=False, comment='提交幂等键')
    request_hash = Column(String(64), nullable=False, comment='提交内容摘要')
    created_by = Column(Integer, nullable=False, comment='创建人方舟 ID')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')


class ReturnEvent(Base):
    __tablename__ = "ark_sales_return_events"
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='主键')
    return_id = Column(BigInteger, ForeignKey("ark_sales_returns.id"), nullable=False, index=True, comment='关联退货单 ID')
    action = Column(String(32), nullable=False, comment='审计动作编码')
    actor_id = Column(Integer, nullable=False, comment='操作人方舟 ID')
    data = Column(JSON, nullable=False, default=dict, comment='审计摘要')
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment='创建时间，北京时间')


@event.listens_for(ReturnEvent, "before_update")
@event.listens_for(ReturnEvent, "before_delete")
@event.listens_for(ReturnEffect, "before_update")
@event.listens_for(ReturnEffect, "before_delete")
@event.listens_for(ReturnReceipt, "before_update")
@event.listens_for(ReturnReceipt, "before_delete")
def immutable_effect(mapper, connection, row):
    raise ValueError("Return audit and financial effects are append-only; create a reversal instead")
