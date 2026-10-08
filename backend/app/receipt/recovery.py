"""Bounded recovery based on durable send evidence, never blind POST replay."""
import logging
from datetime import timedelta

import httpx
from sqlalchemy import or_, update

from app.core.queue_scan import take
from app.core.time import beijing_now
from app.receipt import service
from app.receipt.models import Receipt, ReceiptAttempt
from app.receipt.receipt_index import IndexNotReady

logger = logging.getLogger(__name__)
PREPARE_LIMIT = 5
VERIFY_LIMIT = 8


def transient_preparation(exc):
    return isinstance(exc, (IndexNotReady, httpx.TimeoutException, httpx.NetworkError)) or isinstance(
        exc.__cause__, (httpx.TimeoutException, httpx.NetworkError))


def retry_values(attempts, kind):
    attempts += 1
    limit = PREPARE_LIMIT if kind == "prepare_retry" else VERIFY_LIMIT
    return dict(recovery_attempts=attempts,
                recovery_kind=kind if attempts < limit else "exhausted",
                next_attempt_at=(beijing_now() + timedelta(seconds=min(1800, 60 * 2 ** (attempts - 1))))
                if attempts < limit else None)


def recover_expired(db):
    candidates = db.query(Receipt.id).filter(Receipt.sync_status == "syncing",
        or_(Receipt.lease_until.is_(None), Receipt.lease_until < beijing_now())).all()
    db.commit()
    for (identity,) in candidates:
        row = db.get(Receipt, identity)
        db.query(Receipt).filter(Receipt.id == identity).with_for_update().one()
        db.refresh(row)
        if row.sync_status != "syncing" or (row.lease_until and row.lease_until >= beijing_now()):
            db.rollback()
            continue
        if row.xiaoman_receipt_id:
            row.sync_status, row.recovery_kind = "synced", "verify"
            row.next_attempt_at = beijing_now()
        elif row.send_phase == "preparing":
            values = retry_values(row.recovery_attempts, "prepare_retry")
            for key, value in values.items():
                setattr(row, key, value)
            row.sync_status = "failed"
            row.last_error = "发送前任务中断，等待自动恢复" if row.next_attempt_at else "发送前恢复次数已用尽，请检查后重试"
        else:
            row.sync_status, row.recovery_kind = "uncertain", "unknown"
            row.next_attempt_at = None
            row.last_error = "任务中断且无法证明未发送，结果待核对，禁止重复发送"
        row.attempt_token, row.lease_until = None, None
        row.version += 1
        service.log(db, row, "lease_recovered", row.last_error or "已取得远端 ID，等待详情核验")
        db.commit()


def prepare_due(db):
    """Only failures explicitly classified as pre-POST transient can requeue."""
    ids = take(db.query(Receipt.id).filter(Receipt.status == "active", Receipt.sync_status == "failed",
        Receipt.xiaoman_receipt_id.is_(None), Receipt.send_phase == "preparing",
        Receipt.recovery_kind == "prepare_retry", Receipt.next_attempt_at <= beijing_now()),
        Receipt.id, "receipt_prepare_recovery", 10)
    db.commit()
    for identity in ids:
        count = db.execute(update(Receipt).where(Receipt.id == identity, Receipt.status == "active",
            Receipt.sync_status == "failed", Receipt.send_phase == "preparing",
            Receipt.xiaoman_receipt_id.is_(None), Receipt.recovery_kind == "prepare_retry",
            Receipt.next_attempt_at <= beijing_now()).values(sync_status="pending", next_attempt_at=None,
                version=Receipt.version + 1)).rowcount
        if count:
            service.log(db, db.get(Receipt, identity), "auto_retry", "发送前临时故障已到恢复时间，重试原单")
        db.commit()


def verify_due(db):
    """Known ID read-back is independent of the receipt creation switch/index."""
    from app.receipt.sync_service import refresh_accepted
    ids = take(db.query(Receipt.id).filter(Receipt.status == "active",
        Receipt.sync_status.in_(["synced", "uncertain"]), Receipt.xiaoman_receipt_id.isnot(None),
        or_(Receipt.recovery_kind == "verify",
            (Receipt.recovery_kind.is_(None) & (Receipt.collect_status.is_(None) | (Receipt.collect_status == 0)))),
        or_(Receipt.next_attempt_at.is_(None), Receipt.next_attempt_at <= beijing_now())),
        Receipt.id, "receipt_verify_recovery", 10)
    db.commit()
    for identity in ids:
        refresh_accepted(db, identity)


def recover_late_results(db):
    """Recover exact attempt result identities, never amount/date guesses."""
    ids = take(db.query(Receipt.id).join(ReceiptAttempt, ReceiptAttempt.receipt_id == Receipt.id).filter(
        Receipt.status == "active", ReceiptAttempt.handled_at.is_(None),
        ReceiptAttempt.remote_id.isnot(None)).distinct(), Receipt.id, "receipt_late_result", 10)
    db.commit()
    for identity in ids:
        row = db.query(Receipt).filter(Receipt.id == identity).with_for_update().one()
        db.refresh(row)
        if row.status != "active":
            db.rollback()
            continue
        results = db.query(ReceiptAttempt).filter(ReceiptAttempt.receipt_id == identity,
            ReceiptAttempt.remote_id.isnot(None)).all()
        identities = {r.remote_id for r in results}
        for result in results:
            result.handled_at = beijing_now()
        if row.xiaoman_receipt_id and identities == {row.xiaoman_receipt_id}:
            db.commit()
            continue
        row.sync_status, row.send_phase = "uncertain", "accepted"
        row.attempt_token, row.lease_until = None, None
        if row.xiaoman_receipt_id:
            row.recovery_kind, row.next_attempt_at = "blocked", None
            row.last_error = "旧任务与当前绑定返回不同小满 ID，请人工核对重复回款"
        elif len(identities) == 1:
            remote_id = results[0].remote_id
            if not db.query(Receipt.id).filter(Receipt.xiaoman_receipt_id == remote_id).first():
                row.xiaoman_receipt_id, row.xiaoman_receipt_no = remote_id, results[0].remote_no
                row.recovery_kind, row.next_attempt_at = "verify", beijing_now()
                row.last_error = "迟到响应已恢复小满 ID，等待严格详情核验"
            else:
                row.recovery_kind, row.next_attempt_at = "blocked", None
                row.last_error = "迟到回款 ID 已被其他单据绑定，请人工核对"
        else:
            row.recovery_kind, row.next_attempt_at = "blocked", None
            row.last_error = "多个发送任务返回不同回款 ID，请人工核对"
        row.version += 1
        service.log(db, row, "late_result_recovered", row.last_error)
        db.commit()
