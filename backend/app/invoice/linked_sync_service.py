"""Durable save-and-synchronize workflow with explicit partial and unknown outcomes."""
import hashlib
import json
import logging
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from app.core.time import beijing_now
from app.invoice import service, linked_outbound_service
from app.invoice.models import Invoice, InvoiceLinkedSync, OkkiOutboundTask
from app.receipt import balance, remote
from app.receipt.models import Receipt

logger = logging.getLogger(__name__)


def ensure_idle(invoice, linked_id=None):
    if invoice.linked_sync_id and invoice.linked_sync_id != linked_id:
        raise ValueError("订单关联同步尚未结束，请先查看处理结果")


def edit_version(invoice):
    fields = {*service._HEADER_FIELDS, *service._SOURCE_FIELDS, "invoice_no", "sales_user_id", "customer_grade"}
    values = {k: getattr(invoice, k) for k in sorted(fields)}
    values["items"] = [{c.name: getattr(i, c.name) for c in i.__table__.columns
        if c.name not in {"id", "invoice_id", "xiaoman_unique_id", "created_at", "updated_at"}} for i in invoice.items]
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def snapshot(invoice):
    return {"edit_version": edit_version(invoice), "invoice_no": invoice.invoice_no, "customer_id": invoice.customer_id, "currency": invoice.currency,
            "total_amount": str(invoice.total_amount), "surcharge_amount": str(invoice.surcharge_amount or 0),
            "remark": invoice.remark or "", "delivery_address": invoice.delivery_address or "",
            "items": [{"product_id": str(i.product_id), "sku_id": str(i.sku_id), "quantity": i.quantity,
                       "amount": str(i.total_price)} for i in invoice.items]}


def describe(row):
    if row is None:
        return None
    return {"id": row.id, "invoice_id": row.invoice_id, "status": row.status,
            "before": row.before, "after": row.after, "steps": row.steps,
            "created_at": row.created_at, "updated_at": row.updated_at}


def latest(db, invoice_id):
    return db.query(InvoiceLinkedSync).filter_by(invoice_id=invoice_id).order_by(
        InvoiceLinkedSync.created_at.desc(), InvoiceLinkedSync.id.desc()).first()


def create(db, invoice, body, actor):
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    existing = db.query(InvoiceLinkedSync).filter_by(request_key=body.request_key).first()
    if existing:
        if existing.invoice_id != invoice.id or existing.created_by != actor or existing.request_hash != digest:
            raise ValueError("该提交标识已用于其他修改，请刷新后重新提交")
        return existing
    ensure_idle(invoice)
    if not invoice.xiaoman_order_id:
        raise ValueError("请先使用普通同步创建小满订单")
    if edit_version(invoice) != body.expected_version:
        raise ValueError("订单已被他人修改，请刷新后重新编辑")
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).with_for_update().first()
    if task and task.status in {"running", "uncertain"}:
        raise ValueError("出库任务正在执行或结果待核对，暂不能修改订单")
    if db.query(Receipt.id).filter(Receipt.invoice_id == invoice.id,
            Receipt.sync_status.in_(["syncing", "uncertain"]), Receipt.status == "active").first():
        raise ValueError("回款正在发送或结果待核对，暂不能修改订单")
    if body.invoice and (body.invoice.customer_id != invoice.customer_id or body.invoice.currency != invoice.currency
                         or body.invoice.order_type != invoice.order_type):
        raise ValueError("关联同步不支持更换客户、币种或订单类型，请单独处理原单")
    before = snapshot(invoice)
    # Identity and receipt evidence remain frozen; only the amount floor and fee
    # basis restrictions are replaced by a preserved-payment reconciliation.
    service.update_invoice(db, invoice, body.invoice, actor, linked_change=True)
    row = InvoiceLinkedSync(id=beijing_now().strftime("%Y%m%d%H%M%S%f") + "_" + uuid4().hex, invoice_id=invoice.id, request_key=body.request_key,
        request_hash=digest, created_by=actor, status="pending", before=before, after=snapshot(invoice),
        steps={k: {"status": "pending", "message": "等待处理"} for k in ("order", "outbound", "receipt")})
    db.add(row)
    invoice.linked_sync_id = row.id
    db.flush()
    return row


def _lock(db, identity):
    candidate = db.get(InvoiceLinkedSync, identity)
    if candidate is None:
        raise ValueError("关联同步记录不存在")
    invoice = service.get_invoice(db, candidate.invoice_id, for_update=True)
    row = db.query(InvoiceLinkedSync).filter_by(id=identity).with_for_update().one()
    db.refresh(row)
    return invoice, row


def _save_step(db, identity, token, key, result):
    invoice, row = _lock(db, identity)
    if (row.run_token != token or row.status != "running" or invoice.linked_sync_id != identity
            or not row.lease_until or row.lease_until <= beijing_now()):
        raise ValueError("关联同步执行权已失效，请核对原任务")
    row.steps = {**row.steps, key: result}
    db.commit()


class LostExecution(ValueError):
    pass


def ensure_running(db, invoice, identity=None, token=None):
    # Lock survives the following HTTP request. A recovered old runner must
    # fail even when an administrator has already cleared the invoice pointer.
    with db.no_autoflush:
        pointer = db.query(Invoice.linked_sync_id).filter(Invoice.id == invoice.id).with_for_update().scalar()
        if identity is None:
            if pointer:
                raise LostExecution("订单关联同步尚未结束")
            return
        state = db.query(InvoiceLinkedSync.run_token, InvoiceLinkedSync.status, InvoiceLinkedSync.lease_until).filter_by(
            id=identity).with_for_update().one_or_none()
    if (pointer != identity or not state or state.run_token != token or state.status != "running"
            or not state.lease_until or state.lease_until <= beijing_now()):
        raise LostExecution("关联同步执行权已失效，停止发送并核对原任务")


def run(db, identity, actor, *, recheck=False):
    from app.invoice.sync_coordinator import synchronize
    invoice, row = _lock(db, identity)
    if row.status in {"done", "manual"} and recheck:
        ensure_idle(invoice)
        if row.steps["order"]["status"] != "done":
            raise ValueError("订单未确认同步成功，请重新编辑并发起新版本，不能沿用旧任务")
        if snapshot(invoice) != row.after or latest(db, invoice.id).id != identity:
            raise ValueError("订单已有新修改，请查看最新同步任务")
        row.status = "pending"
        row.steps = {**row.steps, "outbound": {"status": "pending", "message": "等待重新核对"},
                     "receipt": {"status": "pending", "message": "等待重新核对"}}
        invoice.linked_sync_id = identity
    elif row.status in {"done", "manual", "uncertain"}:
        return row
    if row.status == "running":
        if row.lease_until and row.lease_until <= beijing_now():
            row.status = "uncertain"
            db.commit()
        return row
    if invoice.linked_sync_id != row.id:
        raise ValueError("该修改版本已结束，请查看最新任务")
    token = uuid4().hex
    row.status, row.run_token, row.lease_until = "running", token, beijing_now() + timedelta(minutes=30)
    db.commit()
    key = "order"
    try:
        if row.steps[key]["status"] != "done":
            _save_step(db, identity, token, key, {"status": "sending", "message": "正在更新原小满订单"})
            invoice = service.get_invoice(db, row.invoice_id, for_update=True)
            result = synchronize(db, invoice, actor, linked_id=identity, linked_token=token)
            if not result.get("ok"):
                status = "uncertain" if result.get("okki_accepted") or result.get("inventory_pending") or invoice.sync_status == "sync_uncertain" else "failed"
                _save_step(db, identity, token, key, {"status": status, "message": result.get("message") or "订单同步未完成"})
                return _finish(db, identity, token, status)
            _save_step(db, identity, token, key, {"status": "done", "message": "原小满订单已更新，库存收尾完成"})
        invoice = service.get_invoice(db, row.invoice_id)
        # A successful step is never POSTed again, but the live binding is checked
        # before continuing after a partial failure.
        key = "outbound"
        live = remote.order_snapshot(db, invoice)
        db.refresh(row)
        if row.steps[key]["status"] not in {"done", "manual"}:
            order = remote.read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
            _save_step(db, identity, token, key, linked_outbound_service.summarize(db, invoice, order))
        key = "receipt"
        summary = balance.calculate(db, invoice, live)
        effective, total = remote.money(summary["effective_amount"]), remote.money(summary["total_amount"])
        message = "已有方舟及小满回款金额、手续费保持不变；新增收款或退款需另行登记"
        receipt_result = {"status": "done", "message": message, "balance": summary,
                          "unpaid_amount": str(max(total - effective, 0)),
                          "overpaid_amount": str(max(effective - total, 0))}
        if Decimal(summary["remaining_amount"]) < 0:
            receipt_result["status"] = "manual"
            receipt_result["message"] = "已登记或待发送金额超过新订单金额，请核对原回款；未修改实际收款"
        if effective > total:
            receipt_result["status"] = "manual"
            receipt_result["message"] = "已生效回款超过新订单金额，请核实退款；原回款未修改"
        _save_step(db, identity, token, key, receipt_result)
        return _finish(db, identity, token)
    except Exception as exc:
        db.rollback()
        logger.warning("linked sync failed step=%s (%s)", key, type(exc).__name__)
        print(f"[linked-sync] failed step={key} ({type(exc).__name__})", flush=True)
        # Exceptions while the order service is running can follow a successful
        # remote commit. Never classify those as blindly retryable.
        status = "uncertain" if key == "order" and not getattr(exc, "before_send", False) else "failed"
        message = str(exc.detail) if isinstance(exc, HTTPException) else str(exc) if isinstance(exc, ValueError) else "处理未完成，请核对当前步骤后重试"
        current = expire(db, identity)
        if current.status != "running" or current.run_token != token:
            return current
        _save_step(db, identity, token, key, {"status": status, "message": message[:500]})
        return _finish(db, identity, token, status)


def _finish(db, identity, token, status=None):
    invoice, row = _lock(db, identity)
    if row.run_token != token or row.status != "running":
        return row
    row.status = status or ("manual" if any(s["status"] == "manual" for s in row.steps.values()) else "done")
    row.run_token, row.lease_until = None, None
    if row.status in {"done", "manual"}:
        invoice.linked_sync_id = None
    db.commit()
    return row


def close_failed(db, identity):
    invoice, row = _lock(db, identity)
    if row.status != "failed" or invoice.linked_sync_id != identity:
        raise ValueError("只有明确失败的任务可以结束；待核对任务禁止解除锁定")
    row.status = "manual"
    invoice.linked_sync_id = None
    db.commit()
    return row


def expire(db, identity):
    _, row = _lock(db, identity)
    if row.status == "running" and (not row.lease_until or row.lease_until <= beijing_now()):
        row.status = "uncertain"
        db.commit()
    return row


def resolve_manually(db, identity, actor, reason):
    """Explicit admin attestation, not an inferred success or automatic replay."""
    from app.semifinished.models import InvoiceAllocation
    reason = reason.strip()
    if len(reason) < 10:
        raise ValueError("请至少填写10字人工核对依据")
    invoice, row = _lock(db, identity)
    if row.status != "uncertain" or invoice.linked_sync_id != identity:
        raise ValueError("仅可处理本订单当前待核对任务")
    # A lease remains on interrupted runners. Never unlock while they can send.
    if row.lease_until and row.lease_until > beijing_now():
        raise ValueError("原执行租约尚未结束，请等待后再人工核对")
    if db.query(InvoiceAllocation.id).filter_by(invoice_id=invoice.id, status="pending").first():
        raise ValueError("请先完成半成品库存恢复")
    row.steps = {**row.steps, "resolution": {"status": "manual", "message": reason,
        "operator_id": actor, "resolved_at": beijing_now().isoformat()}}
    row.status, row.run_token, row.lease_until = "manual", None, None
    invoice.linked_sync_id = None
    # Keep invoice sync status and all remote IDs unchanged. The administrator
    # must use existing order recovery if its status is still uncertain.
    db.commit()
    return row
