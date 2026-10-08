"""Current-authorized recovery; remote GET evidence never holds business locks."""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import okki_client
from app.receipt import access, authority, remote, sync_service
from app.receipt.models import ReceiptLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteTarget:
    receipt_id: str | None
    order_id: str | None


@dataclass(frozen=True)
class RemoteEvidence:
    detail: bool
    records: tuple

    def payload(self):
        values = [dict(record) for record in self.records]
        return values[0] if self.detail else values


def _record(data, expected=None):
    if not isinstance(data, dict):
        raise ValueError('Invalid remote receipt record')
    identity = str(data.get('cash_collection_id') or '')
    if not identity.isascii() or not identity.isdecimal() or len(identity) > 64:
        raise ValueError('Invalid remote receipt identity')
    if expected is not None and identity != expected:
        raise ValueError('Mismatched remote receipt identity')
    if not isinstance(data.get('order_id'), (str, int)) or not isinstance(data.get('currency'), str):
        raise ValueError('Invalid remote receipt association')
    currency = data['currency']
    if not currency or currency != currency.strip() or len(currency) > 16:
        raise ValueError('Invalid remote receipt currency')
    stamp = data.get('collection_date')
    if not isinstance(stamp, str) or len(stamp) < 10:
        raise ValueError('Invalid remote receipt date')
    if date.fromisoformat(stamp[:10]).isoformat() != stamp[:10]:
        raise ValueError('Noncanonical remote receipt date')
    remote.money(data.get('amount'))
    keys = ('cash_collection_id', 'cash_collection_no', 'order_id', 'currency', 'amount',
        'bank_charge', 'real_amount', 'bank_charge_rmb', 'bank_charge_usd',
        'collection_date', 'collect_status')
    record = []
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if value is not None and not isinstance(value, (str, int, float)):
            # Decimal is supported by controlled financial evidence as well.
            from decimal import Decimal
            if not isinstance(value, Decimal):
                raise ValueError('Non-scalar remote receipt evidence')
        if key in ('bank_charge', 'real_amount', 'bank_charge_rmb', 'bank_charge_usd') and value is not None:
            remote.money(value)
        record.append((key, value))
    return tuple(record)


def _read(db, target):
    if target.receipt_id:
        return RemoteEvidence(True, (_record(remote.receipt_info(db, target.receipt_id), target.receipt_id),))
    rows = remote.order_receipts(db, target.order_id)
    if not isinstance(rows, list):
        raise ValueError('Invalid remote receipt candidates')
    records = tuple(_record(row) for row in rows)
    identities = [str(dict(record)['cash_collection_id']) for record in records]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate remote receipt candidates')
    return RemoteEvidence(False, records)


def _values(row):
    return None if row is None else [getattr(row, column.name) for column in row.__table__.columns]


def _capture(db, identity, user, body):
    permissions = ('receipt:write', 'receipt:admin') if body is None else ('receipt:admin',)
    row, invoice, current, batch, children = authority.local_group(db, identity, user,
        *permissions, any_permission=body is None)
    logs = db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id.in_([child.id for child in children]))
        .order_by(ReceiptLog.id).with_for_update().execution_options(populate_existing=True)).all()
    if row.status != 'active' or row.sync_status not in ({'synced', 'uncertain'} if body is None else {'uncertain'}):
        raise ValueError('当前状态无需核对' if body is None else '只有待核对回款可以人工处理')
    if body is not None:
        if body.resolution == 'bind_receipt':
            if not body.xiaoman_receipt_id:
                raise ValueError('请填写小满回款 ID')
        else:
            if row.xiaoman_receipt_id:
                raise ValueError('已取得小满回款 ID，不能确认未创建，请核对远端原单')
            if any(log.receipt_id == row.id and log.action == 'late_result' for log in logs):
                raise ValueError('已记录迟到的小满创建结果，不能确认未创建，请核对远端原单')
    values = [_values(row), _values(invoice), _values(batch),
        [_values(child) for child in children], [_values(log) for log in logs]]
    binding = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    target_id = body.xiaoman_receipt_id if body is not None and body.resolution == 'bind_receipt' else row.xiaoman_receipt_id
    target = RemoteTarget(str(target_id) if target_id else None, row.xiaoman_order_id)
    return row, invoice, current, binding, target


def unavailable(error, *, result=False):
    failures = []
    try:
        logger.warning('Receipt recovery unavailable (%s)', type(error).__name__)
    except Exception as failure:
        failures.append(failure)
    try:
        print('[receipt] recovery unavailable', flush=True)
    except Exception as failure:
        failures.append(failure)
    message = ('回款处理结果暂不能确认，请刷新原单核对，勿重复发送' if result
        else '回款远端证据暂不可用，请稍后核对原单')
    response = HTTPException(503, message, headers={'Cache-Control':'private, no-store', 'Pragma':'no-cache'})
    if failures:
        raise response from ExceptionGroup('Receipt recovery diagnostics failed', failures)
    raise response from None


def recover(db, identity, user, body=None):
    row, invoice, current, expected, target = _capture(db, identity, user, body)
    db.commit()  # No commercial writes: release all business locks before GET.
    try:
        evidence = _read(db, target)
        db.commit()  # End provider token DB writes; index cache is a separate file snapshot.
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, HTTPException, OSError) as error:
        unavailable(error)
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    row, invoice, current, actual, actual_target = _capture(db, identity, user, body)
    if actual != expected or actual_target != target:
        raise HTTPException(409, '回款或已知发送结果在核对期间已变化，请重新读取')
    actor = access.user_id(current)
    if body is None:
        candidates = sync_service._reconcile(db, row, evidence.payload(), actor)
    else:
        sync_service._resolve(db, row, body, evidence.payload(), actor)
        candidates = []
    return row, invoice, candidates
