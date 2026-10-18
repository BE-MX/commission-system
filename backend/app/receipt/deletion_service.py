"""Single-receipt deletion: durable intent before one POST, GET-only recovery."""
import hashlib
import json
import logging
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.invoice import lifecycle_remote, okki_client
from app.invoice.settlement_models import SettlementApplication
from app.receipt import access, authority, deletion_evidence, service, sync_service
from app.receipt.models import ReceiptIntent, ReceiptLog

logger = logging.getLogger(__name__)
STARTED = "delete_started"
EVIDENCE_FIELDS = ("cash_collection_id", "cash_collection_no", "order_id", "currency", "amount",
    "bank_charge", "real_amount", "bank_charge_rmb", "bank_charge_usd", "collection_date",
    "collect_status", "update_time")


def workflow(db, row):
    record = db.scalar(select(ReceiptLog).where(ReceiptLog.receipt_id == row.id,
        ReceiptLog.action == STARTED).order_by(ReceiptLog.id.desc())
        .execution_options(populate_existing=True).limit(1))
    if record is None:
        return None
    try:
        value = json.loads(record.message)
        if (not isinstance(value, dict) or not value.get("token") or not value.get("target")
                or not isinstance(value.get("reason"), str) or len(value["reason"].strip()) < 2
                or str(value["target"]) != str(row.xiaoman_receipt_id)):
            raise ValueError("Invalid deletion intent")
        return value
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(409, "原回款删除记录异常，请管理员核对；禁止重新发送删除") from error


def pending(db, row):
    return row.status == "active" and workflow(db, row) is not None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _values(row):
    return None if row is None else {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _capture(db, identity, user):
    row, invoice, current, _, _ = authority.local_group(db, identity, user, "receipt:delete")
    flow = workflow(db, row)
    if row.status not in {"active", "voided", "remote_deleted"}:
        raise ValueError("当前回款状态不能删除")
    if row.status == "active":
        if row.batch_id or row.receivable_id or row.purpose != "ordinary" or invoice.order_type == "presale":
            raise ValueError("预售、发货结算或整笔回款不能单独删除，请先核对原批次资金")
        service.ensure_order_ready(db, invoice, current=True)
        if row.currency != invoice.currency or row.customer_id != invoice.customer_id:
            raise ValueError("回款与订单客户或币种不一致，请核对原单")
        if row.xiaoman_order_id != invoice.xiaoman_order_id:
            raise ValueError("回款关联小满订单已变化，请核对原单")
        if db.scalar(select(SettlementApplication.id).where(SettlementApplication.receipt_id == row.id,
                SettlementApplication.status != "released").limit(1)):
            raise ValueError("原回款仍有发货资金分配，不能单独删除")
        if flow is None:
            if row.xiaoman_receipt_id:
                if row.sync_status != "synced":
                    raise ValueError("回款正在发送或原结果待核对，请先核实原单")
                service.ensure_result_identity(db, row, row.xiaoman_receipt_id)
            else:
                service._ensure_editable(row, row.version)
                service.ensure_no_returned_result(db, row)
    intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id)
        .with_for_update().execution_options(populate_existing=True))
    if intent and (intent.attempt_token or intent.status in {"armed", "ready"}):
        raise ValueError("订单自动回款正在处理，请稍后核对")
    stamp = _hash([_values(row), _values(invoice), _values(intent), flow])
    target = SimpleNamespace(**_values(row))
    return row, invoice, current, flow, stamp, target


def _read(db, target):
    if not target.xiaoman_receipt_id:
        return {"status": "local", "detail": None}
    proof = deletion_evidence.verified_state(db, target.xiaoman_order_id,
        target.xiaoman_receipt_id, target.currency)
    if proof["detail"] is not None and not sync_service.matches(target, proof["detail"]):
        raise ValueError("小满回款金额、手续费、日期或订单关联已变化，请先核对原单")
    return proof


def _audit_proof(proof):
    # Provider details may contain private file URLs; keep only the financial deletion facts.
    detail = proof["detail"]
    return {"status": proof["status"], "detail": None if detail is None else {
        key: detail[key] for key in EVIDENCE_FIELDS if key in detail}}


def _warn(error):
    logger.warning("Receipt deletion result unavailable (%s)", type(error).__name__)
    print(f"[receipt-delete] result unavailable ({type(error).__name__})", flush=True)


def _rollback(db):
    transaction = db.get_transaction()
    if transaction is not None and not transaction.is_active:
        db.close()
    else:
        db.rollback()
    db.expire_all()


def preview(db, identity, user):
    row, invoice, current, flow, stamp, target = _capture(db, identity, user)
    terminal = row.status != "active"
    db.commit()  # Authorization and business locks never span evidence I/O.
    try:
        proof = {"status": "deleted", "detail": None} if terminal else _read(db, target)
        db.commit()  # Provider token writes only.
    finally:
        _rollback(db)
    row, invoice, _, fresh_flow, actual, _ = _capture(db, identity, user)
    if actual != stamp:
        raise HTTPException(409, "回款或订单在预览期间变化，请重新预览")
    return {"receipt_id": row.id, "receipt_no": row.receipt_no, "invoice_no": invoice.invoice_no,
        "currency": row.currency, "amount": str(row.amount), "bank_charge": str(row.bank_charge),
        "net_amount": str(row.amount - row.bank_charge), "remote_id": row.xiaoman_receipt_id,
        "remote_state": proof["status"], "expected_version": _hash([stamp, proof]),
        "can_delete": not terminal and flow is None, "can_resume": not terminal and flow is not None,
        "reason": fresh_flow["reason"] if fresh_flow else "",
        "receipt": service.describe(db, row, invoice, detail=True) if terminal else None}


def _result(db, row, invoice, status):
    return {"status": status, "message": (
        "原回款已删除，凭证与审计保留；刷新资金汇总后可重新登记回款" if status == "deleted" else
        "原删除结果仍待核对，登记额度继续冻结；请继续核验，系统不会重复发送删除"),
        "receipt": service.describe(db, row, invoice, detail=True)}


def _finish(db, identity, user):
    row, invoice, _, flow, expected, target = _capture(db, identity, user)
    if row.status != "active":
        return _result(db, row, invoice, "deleted")
    if flow is None:
        raise HTTPException(409, "未找到原删除记录，未继续操作")
    db.commit()
    try:
        proof = _read(db, target)
        db.commit()
    except (ValueError, okki_client.OkkiApiError, SQLAlchemyError, HTTPException, OSError) as error:
        _warn(error)
        proof = None
    finally:
        _rollback(db)
    row, invoice, current, actual_flow, actual, _ = _capture(db, identity, user)
    if row.status != "active":
        return _result(db, row, invoice, "deleted")
    if actual != expected or actual_flow != flow:
        raise HTTPException(409, "回款或删除记录已变化，请重新读取原单继续核验")
    if not proof or proof["status"] != "deleted":
        return _result(db, row, invoice, "uncertain")
    service.ensure_result_identity(db, row, row.xiaoman_receipt_id)
    row.status, row.collect_status = "remote_deleted", None
    row.sync_status, row.recovery_kind, row.next_attempt_at = "synced", None, None
    row.last_error = "原小满回款已核实删除，凭证及审计保留；请重新登记回款，此操作不代表退款"
    row.version += 1
    service.log(db, row, "remote_deleted", f"删除原回款已核实；原因：{flow['reason']}；原金额、手续费与凭证保留，不执行退款", access.user_id(current))
    return _result(db, row, invoice, "deleted")


def remove(db, identity, body, user):
    if not body.confirmed or len(body.reason.strip()) < 2:
        raise ValueError("请确认删除范围并填写删除原因")
    row, invoice, current, flow, expected, target = _capture(db, identity, user)
    if row.status != "active":
        return _result(db, row, invoice, "deleted")
    if flow is not None:
        db.rollback()
        return _finish(db, identity, user)  # Original intent is immutable; GET only, even after timeout.
    db.commit()
    try:
        proof = _read(db, target)
        api_token = okki_client.ensure_access_token(db) if proof["status"] == "active" else None
        db.commit()
    finally:
        _rollback(db)
    row, invoice, current, flow, actual, _ = _capture(db, identity, user)
    if actual != expected or _hash([actual, proof]) != body.expected_version:
        raise HTTPException(409, "回款或远端资料已变化，请重新预览后确认")
    if flow is not None:
        raise HTTPException(409, "已有原删除记录，请继续核验")
    if proof["status"] == "local":
        service._void(db, row, body.reason.strip() + "；删除本地未发送回款，凭证与审计保留", access.user_id(current))
        return _result(db, row, invoice, "deleted")
    # Committed before external POST. No other flow may re-send or reclaim this intent.
    row.sync_status, row.recovery_kind, row.next_attempt_at = "uncertain", "blocked", None
    row.last_error = "回款删除结果待核对，请继续核验；确认删除前不能重新登记"
    row.version += 1
    service.log(db, row, STARTED, json.dumps({"token": uuid4().hex, "target": row.xiaoman_receipt_id,
        "reason": body.reason.strip(), "before": vars(target), "remote_before": _audit_proof(proof),
        "message": "已请求删除原回款；原金额、手续费与凭证保留，不执行退款"}, ensure_ascii=False, default=str), access.user_id(current))
    db.commit()
    if proof["status"] == "active":
        try:
            lifecycle_remote.request(api_token, "receipt", target.xiaoman_receipt_id, remove=True)
        except (okki_client.OkkiApiError, ValueError) as error:
            _warn(error)  # A rejected/unknown response never permits another destructive POST.
    return _finish(db, identity, user)
