"""Durable, at-most-one concurrent sender. Unknown outcomes are never retried."""
import logging
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import update

from app.core.time import beijing_now
from app.core.queue_scan import take
from app.invoice import okki_client
from app.invoice.models import Invoice
from app.invoice.settlement_guard import ensure_receipt_sendable
from app.invoice.settlement_models import Receivable
from app.receipt import attachments, balance, fees, remote, service, recovery
from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttempt
from app.receipt.schemas import ReceiptFields

logger = logging.getLogger(__name__)


def release_targets(db):
    """Turn a presale component into a sendable row only after exact target binding."""
    ids = take(db.query(Receipt.id).filter(
        Receipt.status == "active", Receipt.sync_status == "waiting_target",
        Receipt.batch_id.isnot(None)), Receipt.id, "receipt_waiting_target", 20)
    db.commit()
    for identity in ids:
        row = db.get(Receipt, identity)
        if not row:
            continue
        db.query(Invoice.id).filter(Invoice.id == row.invoice_id).with_for_update().one()
        db.refresh(row, with_for_update=True)
        try:
            ensure_receipt_sendable(db, row)
        except ValueError:
            db.rollback()
            continue
        target = db.get(Receivable, row.receivable_id) if row.receivable_id else None
        if (row.sync_status == "waiting_target" and row.status == "active"
                and target and target.invoice_id == row.invoice_id
                and target.remote_status == "bound" and target.remote_order_id):
            row.xiaoman_order_id = target.remote_order_id
            row.sync_status = "pending"
            row.last_error = None
            row.version += 1
            service.log(db, row, "target_bound", "小满应收目标已核验，待发送回款")
        db.commit()


def generate_ready(db):
    ids = take(db.query(ReceiptIntent.invoice_id).filter(ReceiptIntent.status == "ready"),
               ReceiptIntent.invoice_id, "receipt_intent_ready", 20)
    for invoice_id in ids:
        try:
            invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
            intent = db.query(ReceiptIntent).filter(ReceiptIntent.invoice_id == invoice_id).with_for_update().one()
            if invoice.status in {"cancel_pending", "cancelled"} or invoice.linked_sync_id or intent.status != "ready" or not intent.eligible:
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
    recovery.recover_expired(db)


def deliver(db, receipt_id):
    row = db.get(Receipt, receipt_id)
    if row is None:
        return
    invoice_id = row.invoice_id
    db.commit()  # End the lookup snapshot before the invoice locking read.
    # Lock order then row, same ordering used by edit/void/create.
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
    db.refresh(invoice)
    db.refresh(row, with_for_update=True)
    if invoice.status in {"cancel_pending", "cancelled"} or invoice.linked_sync_id:
        db.rollback()
        return
    try:
        ensure_receipt_sendable(db, row)
    except ValueError:
        db.rollback()
        return
    target = None
    if invoice.order_type == "presale" and row.batch_id:
        target = db.get(Receivable, row.receivable_id) if row.receivable_id else None
        if (target is None or target.invoice_id != invoice.id
                or target.remote_status != "bound" or not target.remote_order_id
                or row.xiaoman_order_id != target.remote_order_id):
            row.sync_status = "waiting_target"
            row.last_error = "小满应收目标尚未核验，回款等待目标绑定"
            db.commit()
            return
    token = uuid4().hex
    count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.status == "active",
        Receipt.sync_status == "pending", Receipt.xiaoman_receipt_id.is_(None)).values(
        sync_status="syncing", send_phase="preparing", recovery_kind=None, next_attempt_at=None, attempt_token=token,
        lease_until=beijing_now() + timedelta(minutes=30), attempts=Receipt.attempts + 1,
        version=Receipt.version + 1)).rowcount
    if count:
        db.add(ReceiptAttempt(token=token, receipt_id=receipt_id))
    db.commit()
    if not count:
        return
    sent = False
    def before_send(payload):
        nonlocal sent
        # Token refresh and all remote reads may commit/release the initial locks.
        # Recheck the frozen local inputs under the normal invoice -> receipt lock order.
        db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().one()
        db.refresh(invoice)
        db.refresh(row, with_for_update=True)
        service.ensure_order_ready(db, invoice)
        ensure_receipt_sendable(db, row)
        if db.query(ReceiptAttempt.token).filter(ReceiptAttempt.receipt_id == receipt_id,
                ReceiptAttempt.remote_id.isnot(None)).with_for_update().first():
            raise ValueError("已有发送任务取得小满 ID，等待恢复原单，禁止再次创建")
        if row.version != prepared_version or remote.invoice_binding(invoice) != prepared_binding:
            raise ValueError("发送前订单或回款已变化，停止发送，请重新核验")
        if target:
            db.refresh(target, with_for_update=True)
            if target.kind == "freight":
                balance.calculate_target(db, target, snapshot, exclude_receipt=row.id)
            elif target.remote_status != "bound" or row.xiaoman_order_id != target.remote_order_id:
                raise ValueError("回款目标已变化，停止发送")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        attempt = db.get(ReceiptAttempt, token)
        if attempt.payload_hash and attempt.payload_hash != digest:
            raise ValueError("发送内容已变化，停止发送")
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.attempt_token == token,
            Receipt.sync_status == "syncing", Receipt.lease_until > beijing_now()).values(
            send_phase="sending", lease_until=beijing_now() + timedelta(minutes=5))).rowcount
        if not count:
            db.rollback()
            raise ValueError("回款同步任务已失效，停止发送并等待核对")
        attempt.payload_hash = digest
        db.commit()  # A crash from this point onwards has an unknown POST outcome.
        sent = True
    try:
        db.expire_all()
        row = db.get(Receipt, receipt_id)
        invoice = db.get(Invoice, row.invoice_id)
        service.ensure_order_ready(db, invoice)
        ensure_receipt_sendable(db, row)
        if row.source == "auto" and row.bank_charge == 0 and invoice.surcharge_amount:
            if fees.allocate(db, invoice, row.amount, exclude_receipt=row.id) != 0:
                raise ValueError("旧自动回款尚未分摊手续费，请重试原单后同步")
        snapshot = (remote.target_snapshot(db, target) if target and target.kind == "freight"
                    else remote.order_snapshot(db, invoice))
        summary = (balance.calculate_target(db, target, snapshot, exclude_receipt=row.id)
                   if target and target.kind == "freight"
                   else balance.calculate(db, invoice, snapshot, exclude_receipt=row.id))
        balance.ensure_available(summary, row.amount)
        if row.batch_id:
            from app.receipt.batch_service import validate_bound_proofs
            validate_bound_proofs(db, row)
        else:
            attachments.bind(db, row.attachment_ids, row.created_by, invoice.id, row.id)
        db.commit()
        prepared_version, prepared_binding = row.version, remote.invoice_binding(invoice)
        result = remote.push(db, row, snapshot, before_send)
        # Remote ID is persisted immediately; any DB failure leaves syncing,
        # which expires to uncertain rather than invoking the POST again.
        attempt = db.get(ReceiptAttempt, token)
        attempt.remote_id, attempt.remote_no = str(result["cash_collection_id"]), str(result["cash_collection_no"])
        db.commit()  # Preserve identity evidence even if accepting its unique mapping fails.
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.attempt_token == token,
            Receipt.sync_status == "syncing").values(xiaoman_receipt_id=str(result["cash_collection_id"]),
            xiaoman_receipt_no=str(result["cash_collection_no"]), sync_status="synced", last_error=None,
            send_phase="accepted", recovery_kind="verify", next_attempt_at=beijing_now(), recovery_attempts=0,
            collect_status=None, synced_at=beijing_now(), version=Receipt.version + 1)).rowcount
        if not count:
            service.log(db, row, "late_result", f"旧任务返回小满回款 ID {result['cash_collection_id']}，请核对，未覆盖当前处理结果")
            db.commit()
            return
        attempt.handled_at = beijing_now()
        service.log(db, row, "synced", "小满已返回回款编号；截图仅方舟留存")
        db.commit()
        refresh_accepted(db, receipt_id)
    except Exception as exc:
        db.rollback()
        logger.warning("receipt delivery failed id=%s (%s)", receipt_id, type(exc).__name__)
        print(f"[receipt] delivery failed id={receipt_id} ({type(exc).__name__})", flush=True)
        current = db.get(Receipt, receipt_id)
        sent = sent or current.send_phase == "sending"
        uncertain = isinstance(exc, okki_client.OkkiOutcomeUncertainError) or (sent and not isinstance(exc, okki_client.OkkiApiError))
        state = "uncertain" if uncertain else "failed"
        # API responses may contain customer data; do not persist raw payloads.
        retryable = not sent and recovery.transient_preparation(exc)
        message = ("小满结果待核对，禁止重新创建；请在小满核验" if uncertain else
                   "发送前临时故障，等待自动恢复；尚未发送回款" if retryable else
                   str(exc)[:500] if isinstance(exc, ValueError) and not isinstance(exc, okki_client.OkkiApiError)
                   else "小满拒绝回款请求，请检查应用权限和回款字段后重试")
        values = recovery.retry_values(current.recovery_attempts, "prepare_retry") if retryable else dict(
            recovery_kind="unknown" if uncertain else "blocked", next_attempt_at=None)
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.attempt_token == token,
            Receipt.sync_status == "syncing").values(sync_status=state, last_error=message,
            send_phase="sending" if uncertain else "preparing" if not sent else "rejected", **values,
            version=Receipt.version + 1)).rowcount
        if count:
            service.log(db, db.get(Receipt, receipt_id), state, message)
        db.commit()


def refresh_accepted(db, receipt_id):
    # Once an ID is committed, a failed read must never requeue the POST.
    identity, version = None, None
    try:
        row = db.get(Receipt, receipt_id)
        if not row or row.status != "active" or not row.xiaoman_receipt_id:
            db.rollback()
            return
        identity, version = row.xiaoman_receipt_id, row.version
        data = remote.receipt_info(db, identity)
        db.query(Invoice).filter(Invoice.id == row.invoice_id).with_for_update().one()
        db.refresh(row, with_for_update=True)
        if row.status != "active" or row.xiaoman_receipt_id != identity or row.version != version:
            db.rollback()
            return
        if not matches(row, data):
            row.sync_status = "uncertain"
            row.recovery_kind, row.next_attempt_at = "blocked", None
            row.version += 1
            row.last_error = "小满已创建回款，但金额、手续费、实到账金额、币种或关联订单不匹配，请核对远端原单"
            service.log(db, row, "uncertain", row.last_error)
        else:
            bind_remote(db, row, data, None)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("receipt read-back failed id=%s (%s)", receipt_id, type(exc).__name__)
        print(f"[receipt] read-back failed id={receipt_id} ({type(exc).__name__})", flush=True)
        if identity is None:
            return
        current = db.get(Receipt, receipt_id)
        if current is None:
            return
        conflict = isinstance(exc, service.ReturnedIdentityConflict)
        values = dict(sync_status="uncertain", recovery_kind="blocked", next_attempt_at=None) if conflict else recovery.retry_values(
            current.recovery_attempts, "verify")
        count = db.execute(update(Receipt).where(Receipt.id == receipt_id, Receipt.xiaoman_receipt_id == identity,
            Receipt.version == version, Receipt.status == "active").values(**values,
            last_error=str(exc) if conflict else "小满已返回单号，详情核验暂未完成；仅回读核验，不重新创建", version=Receipt.version + 1)).rowcount
        if count and conflict:
            service.log(db, current, "identity_conflict", str(exc))
        db.commit()


def candidate_matches(row, data):
    return (str(data.get("order_id")) == row.xiaoman_order_id
            and data.get("currency") == row.currency
            # Include old gross-amount candidates: an uncertain legacy POST
            # must never be mistaken for absence and sent a second time.
            and remote.money(data.get("amount")) in {row.amount, remote.net_amount(row)}
            and str(data.get("collection_date"))[:10] == row.collection_date.isoformat())


def matches(row, data):
    try:
        if not candidate_matches(row, data) or data.get("bank_charge") is None or data.get("real_amount") is None:
            return False
        return (remote.money(data["amount"]) == remote.net_amount(row)
                and remote.money(data["bank_charge"]) == 0
                and remote.money(data["real_amount"]) == remote.net_amount(row)
                and all(remote.money(data[key]) == 0 for key in
                        ("bank_charge_rmb", "bank_charge_usd") if key in data))
    except ValueError:
        logger.warning("receipt read-back contains invalid money")
        print("[receipt] read-back contains invalid money", flush=True)
        return False


def bind_remote(db, row, data, actor):
    if not matches(row, data):
        raise ValueError("小满回款的订单、金额、手续费、实到账金额、币种或日期不匹配，禁止绑定")
    identity = str(data["cash_collection_id"])
    service.ensure_result_identity(db, row, identity)
    if row.xiaoman_receipt_id and row.xiaoman_receipt_id != identity:
        raise ValueError("已取得小满回款 ID，不能改绑其他回款，请核对远端原单")
    other = db.query(Receipt.id).filter(Receipt.xiaoman_receipt_id == identity, Receipt.id != row.id).with_for_update().first()
    if other:
        raise ValueError("该小满回款已经绑定其他方舟单据")
    row.xiaoman_receipt_id, row.xiaoman_receipt_no = identity, str(data.get("cash_collection_no") or "")
    if str(data.get("collect_status")) not in {"0", "1"}:
        raise ValueError("小满财务状态缺失或异常，请稍后核对")
    row.collect_status = int(data["collect_status"])
    row.sync_status, row.last_error, row.synced_at = "synced", None, beijing_now()
    row.send_phase, row.recovery_attempts = "verified", 0
    row.recovery_kind = "verify" if row.collect_status == 0 else None
    row.next_attempt_at = beijing_now() + timedelta(minutes=30) if row.collect_status == 0 else None
    row.version += 1
    service.log(db, row, "reconciled", "已核对并绑定小满回款", actor)


def _reconcile(db, row, evidence, actor):
    if row.status != "active" or row.sync_status not in {"synced", "uncertain"}:
        raise ValueError("当前状态无需核对")
    if row.xiaoman_receipt_id:
        bind_remote(db, row, evidence, actor)
        return []
    candidates = [r for r in evidence if candidate_matches(row, r)]
    # Conservative: no automatic bind until OKKI's custom-number preservation
    # has been verified for this tenant; even one same-day amount is ambiguous.
    return [{"xiaoman_receipt_id": str(r["cash_collection_id"]),
             "xiaoman_receipt_no": r.get("cash_collection_no"), "amount": str(r["amount"])} for r in candidates]


def _resolve(db, row, body, evidence, actor):
    if row.status != "active" or row.sync_status != "uncertain":
        raise ValueError("只有待核对回款可以人工处理")
    if body.resolution == "bind_receipt":
        if not body.xiaoman_receipt_id:
            raise ValueError("请填写小满回款 ID")
        bind_remote(db, row, evidence, actor)
    else:
        if row.xiaoman_receipt_id:
            raise ValueError("已取得小满回款 ID，不能确认未创建，请核对远端原单")
        service.ensure_no_returned_result(db, row)
        candidates = [r for r in evidence if candidate_matches(row, r)]
        if candidates:
            raise ValueError("小满存在同订单同额回款候选，不能确认未创建，请核对后绑定")
        row.sync_status, row.last_error = "pending", None
        row.send_phase, row.recovery_kind, row.next_attempt_at, row.recovery_attempts = None, None, None, 0
        row.version += 1
    service.log(db, row, body.resolution, body.reason, actor)
