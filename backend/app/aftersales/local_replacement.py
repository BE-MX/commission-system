"""Approved free replacements use regular order, production and inspection flows."""
import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.aftersales.models import AfterSalesCase, AfterSalesExecution, AfterSalesReview
from app.catalog.models import CatalogSku
from app.finance import service as finance
from app.invoice import commerce_service as commerce
from app.invoice.commerce_schemas import LocalInvoiceDraft, LocalInvoiceAction
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.access import ensure_invoice, user_id


class ReplacementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    action_index: int = Field(ge=0)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    order_type: Literal["stock", "production"] = "stock"
    warehouse_id: int | None = Field(None, gt=0)
    business_date: date
    reason: str = Field(min_length=1, max_length=500)


def validate_actions(db, case, actions):
    if case.local_invoice_item_id is None:
        return
    seen = set()
    for action in actions:
        if action.get("code") not in {"replacement", "resend"}:
            continue
        identity = action.get("local_sku_id")
        if isinstance(identity, bool) or not isinstance(identity, int) or identity <= 0:
            raise ValueError("本地换货或补发方案必须选择本地 SKU")
        sku = db.get(CatalogSku, identity)
        if sku is None or not sku.active or sku.unit != "piece":
            raise ValueError("本地换货或补发 SKU 不存在、已停用或单位不符")
        quantity = Decimal(str(action.get("quantity", 0)))
        if not quantity.is_finite() or quantity <= 0 or quantity != int(quantity):
            raise ValueError("换货或补发数量必须是正整数件")
        key = (action["code"], identity)
        if key in seen:
            raise ValueError("同种措施的同一 SKU 请合并填写")
        seen.add(key)


def create_replacement(db, case_id, body, user):
    with db.begin_nested():
        ledger = finance.book(db)
        identity = db.get(AfterSalesCase, case_id)
        if identity is None or identity.local_invoice_item_id is None:
            raise ValueError("本地售后单不存在")
        original_line = db.get(InvoiceItem, identity.local_invoice_item_id)
        original = finance.lock(db, Invoice, original_line.invoice_id)
        ensure_invoice(db, original, user, invoice_context=True)
        case = finance.lock(db, AfterSalesCase, case_id)
        payload = {"case_id": case.id, "actor_id": user_id(user), "operation": "replacement_order", "body": body.model_dump(mode="json")}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prior = db.scalar(select(AfterSalesExecution).where(AfterSalesExecution.request_key == body.request_key)
                          .with_for_update().execution_options(populate_existing=True))
        if prior:
            if prior.request_hash != digest:
                raise ValueError("幂等键已用于不同售后执行")
            return prior
        finance.open_date(ledger, body.business_date)
        if case.version != body.expected_version or case.deleted_at is not None:
            raise ValueError("售后单已变化，请刷新")
        if case.current_status not in {"approved", "processing"} or body.business_date < case.feedback_date:
            raise ValueError("须审批完成且执行日期不早于反馈日期")
        review = db.scalar(select(AfterSalesReview).where(AfterSalesReview.case_id == case.id,
            AfterSalesReview.workflow_round == case.workflow_round, AfterSalesReview.decision == "approve",
            AfterSalesReview.reviewer_role == "director").order_by(AfterSalesReview.id.desc()).limit(1).with_for_update())
        actions = (review.compensation_snapshot_json or {}).get("actions", []) if review else []
        if body.action_index >= len(actions):
            raise ValueError("缺少最终批准的补发方案")
        if body.business_date < review.created_at.date():
            raise ValueError("补发执行日期不能早于最终批准日期")
        action = actions[body.action_index]
        if action.get("code") not in {"replacement", "resend"}:
            raise ValueError("所选措施不是换货或补发")
        validate_actions(db, case, [action])
        facts = db.scalars(select(AfterSalesExecution).where(AfterSalesExecution.case_id == case.id,
            AfterSalesExecution.related_invoice_id.isnot(None)).with_for_update().execution_options(populate_existing=True)).all()
        used = 0
        for fact in facts:
            related = finance.lock(db, Invoice, fact.related_invoice_id)
            if (fact.action == action["code"] and fact.payload["local_sku_id"] == action["local_sku_id"]
                    and related.commerce_status != "cancelled"):
                used += fact.quantity
        if used + body.quantity > Decimal(str(action["quantity"])):
            raise ValueError("补发超过批准数量")
        row = AfterSalesExecution(case_id=case.id, action=action["code"], quantity=body.quantity,
            business_date=body.business_date, request_key=body.request_key, request_hash=digest,
            payload={**payload, "local_sku_id": action["local_sku_id"], "approval_id": review.id,
                     "approved_action": action}, created_by=user_id(user))
        db.add(row)
        db.flush()
        draft = LocalInvoiceDraft(request_key=f"aftersales-order:{row.id}", local_customer_id=original.local_customer_id,
            sales_user_id=original.sales_user_id, merchandiser_id=original.merchandiser_id,
            order_type=body.order_type, invoice_date=body.business_date, currency=original.currency,
            contact_name=original.contact_name, contact_phone=original.contact_phone, contact_email=original.contact_email,
            delivery_address=original.delivery_address, express_channel=original.express_channel,
            remark=f"售后免费{action['code']}：{case.case_no} / {body.reason}",
            items=[dict(local_sku_id=action["local_sku_id"], quantity=body.quantity, price_per_piece=0)])
        invoice = commerce.create_draft(db, draft, user)
        commerce.confirm(db, invoice.id, LocalInvoiceAction(request_key=f"aftersales-confirm:{row.id}",
            expected_version=invoice.commerce_version, warehouse_id=body.warehouse_id, reason=body.reason), user)
        row.related_invoice_id = invoice.id
        case.current_status = "processing"
        case.version += 1
        db.flush()
        return row


def ensure_regular_amendment(db, invoice_id):
    if db.scalar(select(AfterSalesExecution.id).where(AfterSalesExecution.related_invoice_id == invoice_id)
                 .limit(1).with_for_update()) is not None:
        raise ValueError("售后补发订单由批准方案冻结；需先取消未发订单，再从售后批准方案重新安排")
