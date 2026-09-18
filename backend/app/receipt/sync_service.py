"""Durable, at-most-one concurrent sender. Unknown outcomes are never retried."""
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import update

from app.core.time import beijing_now
from app.invoice import okki_client
from app.invoice.models import Invoice
from app.receipt import attachments, balance, fees, remote, service
from app.receipt.models import Receipt, ReceiptIntent
from app.receipt.schemas import ReceiptFields

logger = logging.getLogger(__name__)


def generate_ready(db):
    ids = [i for (i,) in db.query(ReceiptIntent.invoice_id).filter(ReceiptIntent.status == "ready")
           .order_by(ReceiptIntent.updated_at, ReceiptIntent.id).limit(20)]
    for invoice_id in ids:
        try:
            invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
            intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice_id).with_for_update().one()
            if invoice.linked_sync_id or intent.status != "ready" or not intent.eligible:
                db.rollback()
                continue
            service.ensure_order_ready(db, invoice)
            fields = ReceiptFields(amount=intent.amount, collection_date=intent.collection_date,
                                   payment_type=intent.payment_type, attachment_ids=intent.attachment_ids,
                                   remark=intent.remark or "")
            row = service.new_row(db, invoice, fields, intent.created_by, f"auto_invoice_{invoice.id}",
                                  f"auto_invoice_{invoice.id}", source="auto")
            intent.status, intent.receipt_id = "converted", row.id
            intent.last_error = None
            db.commit()  # atomic transfer from intent reservation to receipt reservation
        except Exception as exc:
            db.rollback()
            intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice_id).first()
            if intent and intent.status == "ready":
                intent.last_error = str(exc)[:500] if isinstance(exc, ValueError) else "自动回款生成暂未完成，请核查凭证与订单状态"
                intent.updated_at = beijing_now()
                db.commit()
            logger.warning("receipt intent generation failed invoice=%s (%s)", invoice_id, type(exc).__name__)
            print(f"[receipt] intent generation failed invoice={invoice_id} ({type(exc).__name__})", flush=True)


def recover_expired(db):
    rows = db.query(Receipt).filter(Receipt.sync_status == "syncing", Receipt.lease_until < beijing_now()).all()
    for candidate in rows:
        count = db.execute(update(Receipt).where(Receipt.id == candidate.id, Receipt.sync_status == "syncing",
                             Receipt.lease_until < beijing_now()).values(sync_status="uncertain",
                             last_error="同步进程中断，结果待核对，禁止重复发送", version=Receipt.version + 1)).rowcount
        if count:
            service.log(db, candidate, "uncertain", "任务租约过期，需要核对小满结果")
    db.commit()


def deliver(db, receipt_id):
    row = db.get(Receipt, receipt_id)
    if row is None:
        return
    # Lock order then row, same ordering used by edit/void/create.
    invoice = db.query(Invoice).filter(Invoice.id == row.invoice_id).with_for_update().one()
    db.refresh(invoice)
    if invoice.linked_sync_id:
        db.rollback()
        return
    token = uuid4().hex
    count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.status == "active",
        Receipt.sync_status == "pending").values(sync_status="syncing", attempt_token=token,
        lease_until=beijing_now() + timedelta(minutes=30), attempts=Receipt.attempts + 1,
        version=Receipt.version + 1)).rowcount
    db.commit()
    if not count:
        return
    sent = False
    def before_send():
        nonlocal sent
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.attempt_token == token,
            Receipt.sync_status == "syncing", Receipt.lease_until > beijing_now()).values(
            lease_until=beijing_now() + timedelta(minutes=5))).rowcount
        db.commit()
        if not count:
            raise ValueError("回款同步任务已失效，停止发送并等待核对")
        sent = True
    try:
        db.expire_all()
        row = db.get(Receipt, receipt_id)
        invoice = db.get(Invoice, row.invoice_id)
        service.ensure_order_ready(db, invoice)
        if row.source == "auto" and row.bank_charge == 0 and invoice.surcharge_amount:
            if fees.allocate(db, invoice, row.amount, exclude_receipt=row.id) != 0:
                raise ValueError("旧自动回款尚未分摊手续费，请重试原单后同步")
        snapshot = remote.order_snapshot(db, invoice)
        summary = balance.calculate(db, invoice, snapshot, exclude_receipt=row.id)
        balance.ensure_available(summary, row.amount)
        attachments.bind(db, row.attachment_ids, row.created_by, invoice.id, row.id)
        db.commit()
        result = remote.push(db, row, snapshot, before_send)
        # Remote ID is persisted immediately; any DB failure leaves syncing,
        # which expires to uncertain rather than invoking the POST again.
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.attempt_token == token,
            Receipt.sync_status == "syncing").values(xiaoman_receipt_id=str(result["cash_collection_id"]),
            xiaoman_receipt_no=str(result["cash_collection_no"]), sync_status="synced", last_error=None,
            collect_status=None, synced_at=beijing_now(), version=Receipt.version + 1)).rowcount
        if not count:
            service.log(db, row, "late_result", f"旧任务返回小满回款 ID {result['cash_collection_id']}，请核对，未覆盖当前处理结果")
            db.commit()
            return
        service.log(db, row, "synced", "小满已返回回款编号；截图仅方舟留存")
        db.commit()
        refresh_accepted(db, receipt_id)
    except Exception as exc:
        db.rollback()
        logger.warning("receipt delivery failed id=%s (%s)", receipt_id, type(exc).__name__)
        print(f"[receipt] delivery failed id={receipt_id} ({type(exc).__name__})", flush=True)
        uncertain = isinstance(exc, okki_client.OkkiOutcomeUncertainError) or (sent and not isinstance(exc, (ValueError, okki_client.OkkiApiError)))
        state = "uncertain" if uncertain else "failed"
        # API responses may contain customer data; do not persist raw payloads.
        message = ("小满结果待核对，禁止重新创建；请在小满核验" if uncertain else
                   str(exc)[:500] if isinstance(exc, ValueError) and not isinstance(exc, okki_client.OkkiApiError)
                   else "小满拒绝回款请求，请检查应用权限和回款字段后重试")
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.attempt_token == token,
            Receipt.sync_status == "syncing").values(sync_status=state, last_error=message,
            version=Receipt.version + 1)).rowcount
        if count:
            service.log(db, db.get(Receipt, receipt_id), state, message)
        db.commit()


def refresh_accepted(db, receipt_id):
    # Once an ID is committed, a failed read must never requeue the POST.
    try:
        row = db.get(Receipt, receipt_id)
        data = remote.receipt_info(db, row.xiaoman_receipt_id)
        db.query(Invoice).filter(Invoice.id == row.invoice_id).with_for_update().one()
        db.refresh(row, with_for_update=True)
        if not matches(row, data):
            row.sync_status = "uncertain"
            row.last_error = "小满已创建回款，但金额、手续费、实到账金额、币种或关联订单不匹配，请核对远端原单"
            service.log(db, row, "uncertain", row.last_error)
        else:
            bind_remote(db, row, data, None)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("receipt read-back failed id=%s (%s)", receipt_id, type(exc).__name__)
        print(f"[receipt] read-back failed id={receipt_id} ({type(exc).__name__})", flush=True)
        db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.sync_status == "synced").values(
            last_error="小满已返回单号，但详情核验暂未完成，请刷新小满结果", version=Receipt.version + 1))
        db.commit()


def candidate_matches(row, data):
    return (str(data.get("order_id")) == row.xiaoman_order_id
            and data.get("currency") == row.currency and remote.money(data.get("amount")) == row.amount
            and str(data.get("collection_date"))[:10] == row.collection_date.isoformat())


def matches(row, data):
    try:
        if not candidate_matches(row, data) or data.get("bank_charge") is None or data.get("real_amount") is None:
            return False
        return (remote.money(data["bank_charge"]) == row.bank_charge
                and remote.money(data["real_amount"]) == row.amount - row.bank_charge)
    except ValueError:
        logger.warning("receipt read-back contains invalid money")
        print("[receipt] read-back contains invalid money", flush=True)
        return False


def bind_remote(db, row, data, actor):
    if not matches(row, data):
        raise ValueError("小满回款的订单、金额、手续费、实到账金额、币种或日期不匹配，禁止绑定")
    identity = str(data["cash_collection_id"])
    if row.xiaoman_receipt_id and row.xiaoman_receipt_id != identity:
        raise ValueError("已取得小满回款 ID，不能改绑其他回款，请核对远端原单")
    other = db.query(Receipt.id).filter(Receipt.xiaoman_receipt_id == identity, Receipt.id != row.id).first()
    if other:
        raise ValueError("该小满回款已经绑定其他方舟单据")
    row.xiaoman_receipt_id, row.xiaoman_receipt_no = identity, str(data.get("cash_collection_no") or "")
    if str(data.get("collect_status")) not in {"0", "1"}:
        raise ValueError("小满财务状态缺失或异常，请稍后核对")
    row.collect_status = int(data["collect_status"])
    row.sync_status, row.last_error, row.synced_at = "synced", None, beijing_now()
    row.version += 1
    service.log(db, row, "reconciled", "已核对并绑定小满回款", actor)


def reconcile(db, row, actor):
    if row.status != "active" or row.sync_status not in {"synced", "uncertain"}:
        raise ValueError("当前状态无需核对")
    if row.xiaoman_receipt_id:
        bind_remote(db, row, remote.receipt_info(db, row.xiaoman_receipt_id), actor)
        return []
    candidates = [r for r in remote.order_receipts(db, row.xiaoman_order_id) if candidate_matches(row, r)]
    # Conservative: no automatic bind until OKKI's custom-number preservation
    # has been verified for this tenant; even one same-day amount is ambiguous.
    return [{"xiaoman_receipt_id": str(r["cash_collection_id"]),
             "xiaoman_receipt_no": r.get("cash_collection_no"), "amount": str(r["amount"])} for r in candidates]


def resolve(db, row, body, actor):
    if row.status != "active" or row.sync_status != "uncertain":
        raise ValueError("只有待核对回款可以人工处理")
    if body.resolution == "bind_receipt":
        if not body.xiaoman_receipt_id:
            raise ValueError("请填写小满回款 ID")
        bind_remote(db, row, remote.receipt_info(db, body.xiaoman_receipt_id), actor)
    else:
        if row.xiaoman_receipt_id:
            raise ValueError("已取得小满回款 ID，不能确认未创建，请核对远端原单")
        candidates = [r for r in remote.order_receipts(db, row.xiaoman_order_id) if candidate_matches(row, r)]
        if candidates:
            raise ValueError("小满存在同订单同额回款候选，不能确认未创建，请核对后绑定")
        row.sync_status, row.last_error = "pending", None
        row.version += 1
    service.log(db, row, body.resolution, body.reason, actor)
