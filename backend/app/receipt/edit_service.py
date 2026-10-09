"""Current-authorized receipt edits with immutable order/file evidence outside locks."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.storage.cos import StorageError
from app.invoice import okki_client
from app.receipt import access, attachments, authority, remote, retry_service, service


@dataclass(frozen=True)
class OrderTarget:
    id: int
    xiaoman_order_id: str
    customer_id: str
    currency: str
    total_amount: Decimal
    surcharge_amount: Decimal


@dataclass(frozen=True)
class OrderEvidence:
    binding: tuple
    rows: tuple
    payment_types: tuple

    def snapshot(self):
        return {"invoice_binding": list(self.binding), "rows": [
            {"cash_collection_id": identity, "currency": currency, "amount": amount,
             "collect_status": status} for identity, currency, amount, status in self.rows]}


def _binding(row, invoice):
    data = [[getattr(value, column.name) for column in value.__table__.columns] for value in (row, invoice)]
    return hashlib.sha256(json.dumps(data, default=str).encode()).hexdigest()


def _check(db, row, invoice, body):
    if row.batch_id or row.purpose in {"presale_deposit", "presale_advance"}:
        raise ValueError("关联预售或批次的回款不能单独修改/作废，请核对原批次")
    if row.status != "active" or row.sync_status not in {"pending", "failed"} or row.xiaoman_receipt_id:
        raise ValueError("仅未发送或明确失败的回款可修改")
    if row.version != body.version:
        raise HTTPException(409, "回款已被修改，请刷新后重试")
    service.ensure_order_ready(db, invoice, current=True)


def _evidence(db, target):
    snapshot = remote.order_snapshot(db, target)
    binding = tuple(remote.invoice_binding(target))
    if not isinstance(snapshot, dict) or snapshot.get("invoice_binding") != list(binding):
        raise ValueError("订单余额证据目标不完整")
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("订单余额证据格式不完整")
    frozen, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("订单回款证据格式不完整")
        identity = str(row.get("cash_collection_id") or "")
        if not identity or identity in seen or row.get("currency") != target.currency:
            raise ValueError("订单回款证据身份不完整")
        seen.add(identity)
        amount = row.get("amount")
        remote.money(amount)  # Validate numerically without changing the balance digest representation.
        frozen.append((identity, row["currency"], str(amount), str(row.get("collect_status"))))
    payment_types = remote.receipt_types(db)
    if not isinstance(payment_types, list) or not payment_types or any(not isinstance(x, str) for x in payment_types):
        raise ValueError("回款方式证据格式不完整")
    return OrderEvidence(binding, tuple(frozen), tuple(payment_types))


def edit(db, identity, body, user):
    row, invoice, current, _, _ = authority.local_group(db, identity, user)
    _check(db, row, invoice, body)
    expected = _binding(row, invoice)
    target = OrderTarget(invoice.id, invoice.xiaoman_order_id, invoice.customer_id, invoice.currency,
        invoice.total_amount, invoice.surcharge_amount)
    files = attachments.capture_binding(db, body.attachment_ids, access.user_id(current), invoice.id, row.id)
    db.commit()  # No commercial mutation: release every business lock before external evidence.
    try:
        evidence = _evidence(db, target)
        proof_evidence = attachments.verify_storage(files)
        db.commit()  # Only provider token/cache updates belong to this phase.
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, OSError, StorageError, HTTPException) as error:
        retry_service._unavailable(error, message="回款修改证据暂不可用，请核对原单")
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    row, invoice, current, _, _ = authority.local_group(db, identity, user)
    _check(db, row, invoice, body)
    if _binding(row, invoice) != expected:
        raise HTTPException(409, "回款或订单在核验期间已变化，请重新读取")
    service._change(db, row, invoice, body, access.user_id(current), evidence.snapshot(),
        evidence.payment_types, proof_evidence)
    return row, invoice


def result_unavailable(error):
    retry_service._unavailable(error, message="回款修改结果暂不能确认，请刷新原单核对")
