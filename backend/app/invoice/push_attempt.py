"""Durable fencing for ordinary and linked order POSTs."""
from datetime import datetime, timedelta
from uuid import uuid4
from app.core.time import beijing_now
from app.invoice.models import Invoice


def begin(db, invoice):
    with db.no_autoflush:
        current_status = db.query(Invoice.status).filter(Invoice.id == invoice.id).with_for_update().scalar()
    if current_status in {"cancel_pending", "cancelled"}:
        from app.invoice.linked_sync_service import LostExecution
        raise LostExecution("订单已进入取消流程，停止发送")
    allow_recovery(invoice)
    token = uuid4().hex
    invoice.sync_attempt = {"token": token, "lease_until": (beijing_now() + timedelta(minutes=5)).isoformat()}
    invoice.sync_status, invoice.status = "sync_uncertain", "sync_uncertain"
    db.commit()
    return token


def ensure(db, invoice, token):
    from app.invoice.linked_sync_service import LostExecution
    with db.no_autoflush:
        current = db.query(Invoice.sync_attempt, Invoice.status).filter(Invoice.id == invoice.id).with_for_update().one()
    attempt = current[0] or {}
    if (attempt.get("token") != token or not attempt.get("lease_until")
            or datetime.fromisoformat(attempt["lease_until"]) <= beijing_now()
            or current[1] in {"cancel_pending", "cancelled"}):
        raise LostExecution("原推送执行权已失效，请核对原单，禁止旧任务继续发送")


def allow_recovery(invoice):
    attempt = invoice.sync_attempt or {}
    if attempt.get("lease_until") and datetime.fromisoformat(attempt["lease_until"]) > beijing_now():
        raise ValueError("原订单推送租约尚未结束，请稍后核对")


def finish(invoice):
    invoice.sync_attempt = None
