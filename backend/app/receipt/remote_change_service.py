"""Current-authorized remote changes; financial evidence never holds business locks."""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
<<<<<<< HEAD

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import lifecycle_remote, okki_client
from app.receipt import access, authority, receipt_index, reconciliation_service, remote, service
from app.receipt.models import ReceiptLog
=======
from datetime import date, timedelta
from app.core.time import beijing_now
from app.invoice import lifecycle_remote
from app.invoice.service import get_invoice
from app.receipt import remote, service
>>>>>>> origin/main


@dataclass(frozen=True)
class RemoteTarget:
    receipt_id: str
    order_id: str | None
    currency: str
    version: int
    before: tuple


@dataclass(frozen=True)
class RemoteEvidence:
    detail: tuple | None
    index: tuple = ()


def _check(row, body=None):
    if row.status != "active" or not row.xiaoman_receipt_id or row.sync_status not in {"synced", "uncertain"}:
        raise ValueError("仅已绑定小满的有效回款可核实远端变更")
<<<<<<< HEAD
    if body is not None:
        if row.batch_id or row.purpose == "presale_deposit":
            raise ValueError("预售及汇总回款的远端变更需先核对整批资金，不能单独调整")
        if not body.confirmed or len(body.reason.strip()) < 10:
            raise ValueError("请确认已核实实际收款及退款，并填写至少10字依据")
        if row.version != body.version:
            raise ValueError("回款或远端证据已变化，请重新预览后确认")


def _target(row):
    _check(row)
    return RemoteTarget(str(row.xiaoman_receipt_id), row.xiaoman_order_id, row.currency, row.version,
        tuple((key, str(getattr(row, key))) for key in ("amount", "bank_charge", "collection_date", "collect_status")))


def _order(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("回款远端订单关联不可验证")
    text = str(value)
    if not text or text != text.strip() or len(text) > 64 or isinstance(value, int) and value < 1:
        raise ValueError("回款远端订单关联不可验证")
    return text


def _read(db, target):
    data = lifecycle_remote.read(db, "receipt", target.receipt_id)
    if data is not None:
        if not isinstance(data, dict):
            raise ValueError("回款远端证据不可验证")
        _order(data.get("order_id"))
        return RemoteEvidence(reconciliation_service._record(data, target.receipt_id))
    # The same receipt may have moved to a different order. An order-filtered
    # index cannot prove its deletion. verified_rows verifies the global index.
    rows = receipt_index.verified_rows(db)
    if not isinstance(rows, list):
        raise ValueError("回款删除索引不完整")
    values, seen = [], set()
    for record in rows:
        if not isinstance(record, dict):
            raise ValueError("回款删除索引不完整")
        identity = str(record.get("cash_collection_id") or "")
        if not identity.isascii() or not identity.isdecimal() or len(identity) > 64 or identity in seen:
            raise ValueError("回款删除索引身份不完整")
        seen.add(identity)
        order = record.get("order_id")
        # A known ID is sufficient to reject deletion, even if its order field
        # is absent. Other rows must have valid associations to prove absence.
        values.append((identity, None if identity == target.receipt_id and order is None else _order(order)))
    return RemoteEvidence(None, tuple(values))


def _evidence(target, evidence):
    if evidence.detail is None:
        if any(identity == target.receipt_id for identity, _ in evidence.index):
            raise ValueError("小满完整索引仍存在原回款，删除证据不一致，请核对原关联")
=======
    service.ensure_result_identity(db, row, row.xiaoman_receipt_id)
    data = lifecycle_remote.read(db, "receipt", row.xiaoman_receipt_id)
    if data is None:
        # Verify the active index as well: a transient detail absence alone must
        # never release the reservation of a still-indexed receipt.
        if any(str(r["cash_collection_id"]) == row.xiaoman_receipt_id
               for r in remote.order_receipts(db, row.xiaoman_order_id)):
            raise ValueError("小满列表仍存在原回款，删除证据不一致，请稍后核对")
>>>>>>> origin/main
        current = None
    else:
        data = dict(evidence.detail)
        if str(data.get("order_id")) != target.order_id or data.get("currency") != target.currency:
            raise ValueError("远端回款已改关联订单或币种，请在小满恢复原关联后再处理")
        amount, charge = remote.money(data.get("amount")), remote.money(data.get("bank_charge"))
        if charge > amount or remote.money(data.get("real_amount")) != amount - charge:
            raise ValueError("远端回款金额、手续费或实到账不一致")
        if str(data.get("collect_status")) not in {"0", "1"}:
            raise ValueError("远端财务状态无效")
        if charge != 0 or any(key in data and remote.money(data[key]) != 0 for key in ("bank_charge_rmb", "bank_charge_usd")):
            raise ValueError("小满回款手续费非零，请按净额规则核对原单后处理")
        local_charge = remote.money(dict(target.before)["bank_charge"])
        if amount + local_charge <= 0:
            raise ValueError("核对后的含费回款金额必须大于零")
        current = {"amount": str(amount + local_charge), "bank_charge": str(local_charge),
            "collection_date": date.fromisoformat(str(data.get("collection_date"))[:10]).isoformat(),
            "collect_status": int(data["collect_status"])}
    result = {"remote_id": target.receipt_id, "version": target.version, "before": dict(target.before), "after": current}
    result["evidence_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def _capture(db, identity, user, body):
    row, invoice, current, batch, children = authority.local_group(db, identity, user, "receipt:admin")
    _check(row, body)  # Scope of every original member is checked before batch guards.
    logs = db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id.in_([child.id for child in children]))
        .order_by(ReceiptLog.id).with_for_update().execution_options(populate_existing=True)).all()
    values = [reconciliation_service._values(row), reconciliation_service._values(invoice),
        reconciliation_service._values(batch), [reconciliation_service._values(child) for child in children],
        [reconciliation_service._values(log) for log in logs]]
    binding = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    return row, invoice, current, binding, _target(row)


def _apply(db, row, body, proof, actor):
    _check(row, body)
    if proof["version"] != row.version or proof["evidence_hash"] != body.evidence_hash:
        raise ValueError("回款或远端证据已变化，请重新预览后确认")
<<<<<<< HEAD
=======
    if row.status != "active" or row.sync_status not in {"synced", "uncertain"}:
        raise ValueError("回款状态已变化，请刷新")
    service.ensure_result_identity(db, row, row.xiaoman_receipt_id)
>>>>>>> origin/main
    if proof["after"] is None:
        row.status = "remote_deleted"
        row.collect_status = None
        row.last_error = "已核实小满删除；原ID与凭证保留。此操作不代表资金退款"
    else:
        data = proof["after"]
        row.amount, row.bank_charge = remote.money(data["amount"]), remote.money(data["bank_charge"])
        row.collection_date = date.fromisoformat(data["collection_date"])
        row.collect_status = data["collect_status"]
        row.sync_status, row.last_error = "synced", None
        row.send_phase, row.recovery_attempts = "verified", 0
        row.recovery_kind = "verify" if row.collect_status == 0 else None
        row.next_attempt_at = beijing_now() + timedelta(minutes=30) if row.collect_status == 0 else None
    row.version += 1
    service.log(db, row, "remote_change", json.dumps({"evidence": proof, "reason": body.reason.strip()}, ensure_ascii=False), actor)


def preview(db, identity, user):
    current = authority.read_user(db, user, "receipt:admin")
    row, _ = service.get(db, identity, current)  # Ordinary read, no business locks across GET.
    target = _target(row)
    try:
        evidence = _read(db, target)
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, HTTPException, OSError) as error:
        reconciliation_service.unavailable(error)
    return _evidence(target, evidence)


def accept(db, identity, body, user):
    row, invoice, current, expected, target = _capture(db, identity, user, body)
    db.commit()  # Explicitly release all business locks before remote GET.
    try:
        evidence = _read(db, target)
        db.commit()  # Caller owns token DB writes; global index cache is a file snapshot.
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, HTTPException, OSError) as error:
        reconciliation_service.unavailable(error)
    finally:
        transaction = db.get_transaction()
        if transaction is not None and not transaction.is_active:
            db.close()
        else:
            db.rollback()
        db.expire_all()
    row, invoice, current, actual, actual_target = _capture(db, identity, user, body)
    if actual != expected or actual_target != target:
        raise HTTPException(409, "回款关联或已知发送结果在取证期间变化，请重新读取")
    proof = _evidence(target, evidence)  # Only disclose commercial evidence after final authorization.
    _apply(db, row, body, proof, access.user_id(current))
    return row, invoice
