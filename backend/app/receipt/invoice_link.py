"""Invoice hooks: draft proof, preflight, successful-commit intent and recovery."""
from decimal import Decimal
from datetime import timedelta
from uuid import uuid4

from app.core.time import beijing_now

from app.invoice.models import Invoice
from app.receipt import attachments, balance, remote
from app.receipt.models import Receipt, ReceiptIntent
from app.receipt.schemas import ReceiptFields


def get_intent(db, invoice_id):
    return db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice_id).first()


def save_draft(db, invoice, draft, actor, *, new=False):
    if invoice.order_type not in {"stock", "presale"}:
        return
    row = get_intent(db, invoice.id)
    if row is None:
        # New application-created invoices enter the flow. Historical invoices
        # may attach evidence, but are never automatically backfilled.
        row = ReceiptIntent(invoice_id=invoice.id, eligible=int(new), created_by=actor,
                            attachment_ids=[], status="draft")
        db.add(row)
    if draft is None:
        return
    if row.status != "draft":
        # Generic invoice editor round-trips the frozen draft; disallow changes.
        if (draft.amount != row.amount or draft.collection_date != row.collection_date
                or draft.payment_type != row.payment_type or draft.attachment_ids != row.attachment_ids
                or draft.remark != (row.remark or "")):
            raise ValueError("本次回款已提交，不能随订单修改，请在回款单中处理")
        return
    if draft.attachment_ids:
        attachments.bind(db, draft.attachment_ids, actor, invoice.id)
    for key in ("amount", "collection_date", "payment_type", "remark", "attachment_ids"):
        setattr(row, key, getattr(draft, key))
    row.currency, row.customer_id = invoice.currency, invoice.customer_id


def preflight(db, invoice, actor):
    if invoice.order_type not in {"stock", "presale"}:
        return
    row = get_intent(db, invoice.id)
    if not row or not row.attachment_ids:
        raise ValueError("请上传回款截图后再同步小满。库存单可以先保存")
    attachments.bind(db, row.attachment_ids, actor, invoice.id, row.receipt_id)
    if row.status == "converted" or not row.eligible:
        return
    if row.currency != invoice.currency or row.customer_id != invoice.customer_id:
        raise ValueError("回款资料与订单客户或币种不一致，请重新核对")
    ReceiptFields(amount=row.amount, collection_date=row.collection_date, payment_type=row.payment_type,
                  attachment_ids=row.attachment_ids, remark=row.remark or "")
    if invoice.order_type == "presale":
        from app.receipt.fees import proportional
        charge = proportional(invoice.total_amount, invoice.surcharge_amount or 0, row.amount)
        if row.amount - charge <= 0 or row.amount - charge > invoice.product_amount:
            raise ValueError("预付款净额必须大于零且不能超过商品净额")
    if row.amount > invoice.total_amount:
        raise ValueError("本次回款不能超过订单金额")


def arm(db, invoice, actor):
    if invoice.order_type not in {"stock", "presale"}:
        return None
    preflight(db, invoice, actor)
    row = get_intent(db, invoice.id)
    if row.attempt_token:
        raise ValueError("库存单正在同步或上次任务待恢复，请勿重复提交")
    if invoice.sync_status == "sync_uncertain":
        raise ValueError("上次小满建单结果待核对，请管理员先处理")
    if row and row.eligible and row.status == "draft":
        row.status = "armed"
    row.attempt_token, row.lease_until = uuid4().hex, beijing_now() + timedelta(minutes=30)
    row.created_by = row.created_by or actor
    row.last_error = None
    db.flush()
    return row.attempt_token


def finish_attempt(db, invoice, token):
    row = get_intent(db, invoice.id)
    if row and token and row.attempt_token == token:
        row.attempt_token, row.lease_until = None, None


def ensure_attempt(db, invoice, token):
    if token:
        row = get_intent(db, invoice.id)
        db.refresh(row)
        if row.attempt_token != token or not row.lease_until or row.lease_until <= beijing_now():
            raise ValueError("库存单同步任务已失效，请核对后重新操作")


def recover_expired(db):
    ids = [i for (i,) in db.query(ReceiptIntent.invoice_id).filter(
        ReceiptIntent.attempt_token.isnot(None), ReceiptIntent.lease_until < beijing_now())]
    for invoice_id in ids:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
        row = get_intent(db, invoice_id)
        db.refresh(row, with_for_update=True)
        if row.attempt_token and row.lease_until < beijing_now():
            row.attempt_token, row.lease_until = None, None
            row.last_error = "库存单同步中断，请核对小满订单后重新同步"
            if not invoice.xiaoman_order_id:
                invoice.sync_status = "sync_uncertain"
                invoice.status = "sync_uncertain"
    db.commit()


def mark_success(db, invoice, token=None):
    row = get_intent(db, invoice.id)
    if token and (not row or row.attempt_token != token or not row.lease_until or row.lease_until <= beijing_now()):
        return {"receipt_generation_status": "waiting_recovery", "receipt_id": row.receipt_id if row else None}
    if row and row.eligible and row.status == "armed":
        row.status = "ready"
    return {"receipt_generation_status": row.status if row else "not_applicable",
            "receipt_id": row.receipt_id if row else None}


def release_rejected(db, invoice, token=None):
    row = get_intent(db, invoice.id)
    if token and (not row or row.attempt_token != token):
        return
    if row and row.status == "armed" and not invoice.xiaoman_order_id and invoice.sync_status != "sync_uncertain":
        row.status = "draft"


def guard_edit(db, invoice, body):
    row = get_intent(db, invoice.id)
    if row and (row.attempt_token or row.status == "ready" or invoice.sync_status == "sync_uncertain"):
        raise ValueError("订单回款正在处理或等待恢复，暂不能编辑")
    if invoice.order_type == "presale" and row and row.status != "draft":
        raise ValueError("预售首款已提交，商业合同已冻结；发货地址和备注请在批次中处理")
    local = db.query(Receipt).filter(Receipt.invoice_id == invoice.id, Receipt.status == "active").count()
    snapshot = {"rows": remote.order_receipts(db, invoice.xiaoman_order_id) if invoice.xiaoman_order_id else []}
    if local or snapshot["rows"] or (row and row.status in {"armed", "converted"}):
        if body.customer_id != invoice.customer_id or body.currency != invoice.currency or body.order_type != invoice.order_type:
            raise ValueError("已有回款的订单不能更换客户、币种或类型")
    if local or snapshot["rows"] or (row and row.status == "armed"):
        return Decimal(balance.calculate(db, invoice, snapshot)["registered_amount"])
    return Decimal("0")



def guard_fee_basis(db, invoice, previous):
    if previous == (invoice.total_amount, invoice.surcharge_amount):
        return
    pending = db.query(Receipt.id).filter(Receipt.invoice_id == invoice.id,
        Receipt.status == "active", Receipt.sync_status != "synced").first()
    if pending:
        raise ValueError("存在待处理回款，不能更改订单总额或手续费，请先处理或作废原回款")


def guard_delete(db, invoice):
    if db.query(Receipt.id).filter(Receipt.invoice_id == invoice.id).first():
        raise ValueError("存在回款记录的订单不允许删除")
    row = get_intent(db, invoice.id)
    if row and row.status != "draft":
        raise ValueError("订单回款意图等待恢复，不允许删除")
    from app.receipt.models import ReceiptAttachment
    db.query(ReceiptAttachment).filter(ReceiptAttachment.invoice_id == invoice.id).update({"invoice_id": None})
    if row:
        db.delete(row)


def describe(db, invoice):
    row = get_intent(db, invoice.id)
    if not row:
        return None
    return {"amount": str(row.amount) if row.amount is not None else None,
            "collection_date": row.collection_date, "payment_type": row.payment_type,
            "remark": row.remark or "", "attachment_ids": row.attachment_ids,
            "status": row.status, "eligible": bool(row.eligible), "receipt_id": row.receipt_id,
            "last_error": row.last_error}
