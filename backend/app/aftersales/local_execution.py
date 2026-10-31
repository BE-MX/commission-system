"""Local aftersales evidence. Lock order: book -> order -> case -> warehouse.

Returns preserve shipment and order quantities as historical facts. Physical
returned goods enter quarantine, and cannot finance another shipment or sale.
"""
import hashlib
import json
from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.aftersales.models import AfterSalesCase, AfterSalesExecution
from app.finance import service as finance
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import SettlementItem, ShipmentSettlement
from app.invoice.local_funding import ensure_event_date
from app.inventory import service as stock
from app.receipt.access import ensure_invoice, user_id


class ReturnReceive(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    settlement_item_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    business_date: date
    reason: str = Field(min_length=1, max_length=500)


def validate_binding(db, payload, user):
    identity = payload.local_invoice_item_id
    if identity is None:
        if payload.order_id.startswith("local:"):
            raise ValueError("本地售后必须选择本地订单行")
        return payload
    if payload.product_id is not None:
        raise ValueError("本地售后不能混用小满产品 ID")
    line = db.get(InvoiceItem, identity)
    invoice = db.get(Invoice, line.invoice_id) if line else None
    ensure_invoice(db, invoice, user, invoice_context=True)
    if invoice.transaction_mode != "local" or not line.local_sku_id or line.stock_shipped_quantity <= 0:
        raise ValueError("售后必须关联本地已发货商品")
    if (payload.order_id != f"local:{invoice.id}" or payload.customer_id != invoice.customer_id
            or payload.affected_goods_currency != invoice.currency):
        raise ValueError("售后订单、客户或币种与本地订单不一致")
    if payload.feedback_date < invoice.invoice_date:
        raise ValueError("反馈日期不能早于本地订单日期")
    if payload.quantity != int(payload.quantity) or payload.quantity > line.stock_shipped_quantity:
        raise ValueError("售后数量必须为不超过已发货量的整数件")
    return payload.model_copy(update={"product_name_snapshot": line.product_name,
        "order_no_snapshot": invoice.invoice_no, "customer_name_snapshot": invoice.customer_name,
        "purchase_date": invoice.invoice_date})


def describe(row):
    return {key: getattr(row, key) for key in ("id", "case_id", "settlement_item_id", "action", "quantity",
        "stock_document_id", "related_invoice_id", "business_date", "payload", "created_by", "created_at")}


def receive_return(db, case_id, body, user):
    with db.begin_nested():
        ledger = finance.book(db)
        identity = db.get(AfterSalesCase, case_id)
        if identity is None or identity.local_invoice_item_id is None:
            raise HTTPException(404, "本地售后单不存在")
        line_identity = db.get(InvoiceItem, identity.local_invoice_item_id)
        invoice = finance.lock(db, Invoice, line_identity.invoice_id)
        ensure_invoice(db, invoice, user, invoice_context=True)
        case = finance.lock(db, AfterSalesCase, case_id)
        if case.deleted_at is not None or case.local_invoice_item_id != line_identity.id:
            raise ValueError("售后单关联已变化")
        payload = {"case_id": case.id, "actor_id": user_id(user), "action": "return_receive", "body": body.model_dump(mode="json")}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prior = db.scalar(select(AfterSalesExecution).where(AfterSalesExecution.request_key == body.request_key)
                          .with_for_update().execution_options(populate_existing=True))
        if prior:
            if prior.request_hash != digest:
                raise ValueError("幂等键已用于不同售后执行")
            return prior
        finance.open_date(ledger, body.business_date)
        if case.version != body.expected_version:
            raise ValueError("售后单已变化，请刷新")
        if case.current_status not in {"approved", "processing"}:
            raise ValueError("只有审批通过的售后单可以收货")
        codes = {action.get("code") for action in case.selected_actions_json or []}
        if not case.requires_return and not codes.intersection({"return_inspection", "replacement", "paid_rework", "free_rework"}):
            raise ValueError("审批方案未包含退回处理")
        item = finance.lock(db, SettlementItem, body.settlement_item_id)
        if item is None or item.invoice_item_id != case.local_invoice_item_id:
            raise ValueError("发货明细不属于售后商品")
        shipment = finance.lock(db, ShipmentSettlement, item.settlement_id)
        if shipment.state != "shipped":
            raise ValueError("仅已发货批次可以退货")
        ensure_event_date(db, invoice.id, body.business_date, shipment.id)
        if body.business_date < case.feedback_date:
            raise ValueError("退货日期不能早于售后反馈日期")
        facts = db.scalars(select(AfterSalesExecution).where(AfterSalesExecution.action == "return_receive",
            (AfterSalesExecution.settlement_item_id == item.id) | (AfterSalesExecution.case_id == case.id))
            .with_for_update().execution_options(populate_existing=True)).all()
        if any(fact.business_date > body.business_date for fact in facts):
            raise ValueError("退货日期不能早于既有退货记录")
        shipped_returned = sum(f.quantity for f in facts if f.settlement_item_id == item.id)
        case_returned = sum(f.quantity for f in facts if f.case_id == case.id)
        if body.quantity + shipped_returned > item.quantity or body.quantity + case_returned > case.quantity:
            raise ValueError("退货超过本批已发货数量或售后批准数量")
        line = finance.lock(db, InvoiceItem, item.invoice_item_id)
        row = AfterSalesExecution(case_id=case.id, settlement_item_id=item.id, action="return_receive",
            quantity=body.quantity, business_date=body.business_date, request_key=body.request_key,
            request_hash=digest, payload=payload, created_by=user_id(user))
        db.add(row)
        db.flush()
        doc, fresh = stock._claim_document(db, f"aftersales-return:{row.id}", payload,
            kind="sales_return", reason=body.reason, created_by=user_id(user), source_type="aftersales", source_id=str(case.id))
        if not fresh:
            raise ValueError("退货库存凭证身份冲突")
        stock._lock_warehouses(db, [body.warehouse_id])
        # Returning a discontinued product is allowed; the immutable shipped SKU
        # is used, never a caller-selected SKU or a currently editable catalog.
        bucket = stock._bucket(db, body.warehouse_id, line.local_sku_id, "quarantine")
        stock._move(db, doc, 1, bucket, body.quantity)
        row.stock_document_id = doc.id
        case.current_status = "processing"
        case.version += 1
        db.flush()
        return row
