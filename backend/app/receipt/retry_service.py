"""Current-authorized local retries with immutable fee evidence outside locks."""
import hashlib
import json
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import okki_client
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement
from app.invoice.settlement_guard import SENDABLE_STATES
from app.receipt import access, authority, fees, remote, service

logger = logging.getLogger(__name__)


def _values(row):
    return None if row is None else [getattr(row, column.name) for column in row.__table__.columns]


def _settlement(db, row):
    if not row.batch_id or row.purpose not in {"presale_goods", "freight"}:
        return None
    application = db.scalars(select(SettlementApplication).where(
        SettlementApplication.receipt_id == row.id, SettlementApplication.status != "released")
        .with_for_update().execution_options(populate_existing=True)).one_or_none()
    if application is None:
        raise ValueError("预售回款未关联有效结算，暂停发送")
    settlement = db.scalar(select(ShipmentSettlement).where(ShipmentSettlement.id == application.settlement_id)
        .with_for_update().execution_options(populate_existing=True))
    if settlement is None or settlement.invoice_id != row.invoice_id:
        raise ValueError("预售回款结算身份异常，暂停发送")
    if settlement.state not in SENDABLE_STATES:
        raise ValueError("本批结算已暂停或进入出库流程，回款不能继续发送")
    return (_values(application), _values(settlement))


def _binding(row, invoice, batch, children, settlement):
    invoice_fields = ("id", "sales_user_id", "portal_document_version", "order_type", "status",
        "sync_status", "linked_sync_id", "xiaoman_order_id", "customer_id", "currency",
        "total_amount", "surcharge_amount")
    captured = [_values(row), [getattr(invoice, name) for name in invoice_fields], _values(batch),
        [_values(child) for child in children] if batch else None, settlement]
    return hashlib.sha256(json.dumps(captured, sort_keys=True, default=str).encode()).hexdigest()


def _check(row):
    if row.status != "active" or row.sync_status != "failed" or row.xiaoman_receipt_id:
        raise ValueError("仅明确失败且未取得小满单号的回款可重试；待核对不能重发")


def _unavailable(error, *, message="回款手续费证据暂不可用，请稍后核对"):
    diagnostics = []
    try:
        logger.warning("Receipt retry fee evidence unavailable (%s)", type(error).__name__)
    except Exception as failure:
        diagnostics.append(failure)
    try:
        print("[receipt] retry fee evidence unavailable", flush=True)
    except Exception as failure:
        diagnostics.append(failure)
    response = HTTPException(503, message,
        headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"})
    if diagnostics:
        raise response from ExceptionGroup("Retry evidence diagnostics failed", diagnostics)
    raise response from None


def retry(db, identity, user):
    row, invoice, current, batch, children = authority.local_group(db, identity, user)
    _check(row)
    settlement = _settlement(db, row)
    needs_fee = row.source == "auto" and row.purpose not in {"presale_deposit", "presale_advance"} and row.bank_charge == 0 and bool(invoice.surcharge_amount)
    evidence = None
    if needs_fee:
        expected = _binding(row, invoice, batch, children, settlement)
        target = tuple(remote.invoice_binding(invoice))  # Independent scalar values, no ORM outside phase.
        db.commit()  # Capture has no commercial changes; release all locks before IO.
        try:
            evidence = fees.read_evidence(db, target)
            db.commit()  # Persist only this phase's provider token/cache updates.
        except (ValueError, okki_client.OkkiApiError, SQLAlchemyError) as error:
            _unavailable(error)
        finally:
            transaction = db.get_transaction()
            if transaction is not None and not transaction.is_active:
                db.close()  # Failed or committed callback state cannot be rolled back.
            else:
                db.rollback()
            db.expire_all()
        row, invoice, current, batch, children = authority.local_group(db, identity, user)
        _check(row)
        settlement = _settlement(db, row)
        if _binding(row, invoice, batch, children, settlement) != expected:
            raise HTTPException(409, "回款在手续费核对期间已变化，请重新读取")
    service._retry(db, row, invoice, access.user_id(current), evidence)
    return row, invoice


def result_unavailable(error):
    """Do not label a possibly committed retry as failed or resend automatically."""
    _unavailable(error, message="回款重试结果暂不能确认，请刷新原单核对")
