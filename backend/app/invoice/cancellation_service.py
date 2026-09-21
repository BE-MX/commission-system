"""Durable cancellation: freeze, inspect, remove only eligible remote orders, retain facts."""
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from app.core.time import beijing_now
from app.invoice import lifecycle_remote, linked_outbound_service, okki_client, service
from app.invoice.lifecycle_guard import ensure_mutable
from app.invoice.models import InvoiceSyncLog
from app.receipt import remote
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation

logger = logging.getLogger(__name__)
TERMINAL = {"remote_deleted", "retained", "aborted"}


def audit(db, invoice, action, actor, data):
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action=action, success=1, operator_id=actor,
                         request_digest=json.dumps(data, ensure_ascii=False, default=str)))


def save(db, invoice, state, actor, message):
    invoice.cancellation = {**(invoice.cancellation or {}), **state,
                            "message": message, "updated_at": beijing_now().isoformat()}
    audit(db, invoice, "cancel_step", actor, invoice.cancellation)
    db.commit()
    return invoice.cancellation


def begin(db, invoice, reason, actor, expected_version):
    from app.invoice.linked_sync_service import edit_version, ensure_idle
    if invoice.cancellation and invoice.cancellation["status"] != "aborted":
        return invoice.cancellation
    ensure_idle(invoice)
    ensure_mutable(db, invoice)
    if not invoice.xiaoman_order_id:
        raise ValueError("未同步草稿请使用删除；结果待核对请先恢复原订单")
    if edit_version(invoice) != expected_version:
        raise ValueError("订单已变化，请刷新后重新发起取消")
    previous = invoice.status
    invoice.status = "cancel_pending"
    return save(db, invoice, {"status": "pending", "reason": reason, "created_by": actor,
        "previous_status": previous, "started_at": beijing_now().isoformat(), "token": None,
        "lease_until": None, "evidence": None}, actor,
        "已暂停订单编辑、新回款发送及自动出库；请核对关联单据")


def inspect(db, invoice):
    if not invoice.cancellation or invoice.cancellation["status"] == "aborted":
        raise ValueError("请先发起取消，冻结后续业务")
    order = lifecycle_remote.read(db, "order", invoice.xiaoman_order_id)
    if order is not None and (str(order.get("company_id")) != str(invoice.customer_id)
                              or order.get("currency") != invoice.currency):
        raise ValueError("小满订单客户或币种已变化，请核实原单")
    outbounds = linked_outbound_service.find_related(db, order) if order else []
    receipts = remote.order_receipts(db, invoice.xiaoman_order_id)
    local = db.query(Receipt).filter_by(invoice_id=invoice.id, status="active").all()
    intent = db.query(ReceiptIntent).filter_by(invoice_id=invoice.id).first()
    allocations = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id).all()
    blockers = []
    if outbounds: blockers.append("仍有关联出库单：待出库请单独删除；已出库请办理退货或保留原单")
    if receipts: blockers.append("仍有关联小满回款：请核实实际收款、退款及财务处理")
    if local: blockers.append("仍有方舟有效回款：未发送可作废，远端删改请先核实并登记")
    if intent and (intent.attempt_token or intent.status in {"armed", "ready"}):
        blockers.append("自动回款意图尚未处理，请核实后保留原单取消")
    if any(a.status == "pending" or Decimal(a.allocated_qty_grams or 0) != 0 for a in allocations):
        blockers.append("仍有半成品预占或出库记录：先核实库存恢复，或保留原记录取消")
    return {"remote_exists": order is not None, "order_status": order.get("status") if order else None,
            "outbounds": [{"id": str(d["outbound_invoice_id"]), "number": d.get("serial_id"), "status": d.get("status")} for d in outbounds],
            "remote_receipt_count": len(receipts), "local_receipt_count": len(local), "blockers": blockers}


def refresh(db, invoice, actor):
    proof = inspect(db, invoice)
    invoice = service.get_invoice(db, invoice.id, for_update=True)
    state = invoice.cancellation
    if state["status"] in TERMINAL:
        return state
    if state["status"] in {"deleting", "uncertain"}:
        if state.get("lease_until") and datetime.fromisoformat(state["lease_until"]) > beijing_now():
            return state
        if not proof["remote_exists"] and not proof["blockers"]:
            invoice.status = "cancelled"
            return save(db, invoice, {"status": "remote_deleted", "evidence": proof}, actor, "已核实小满订单不存在；方舟保留原单及审计记录")
        return save(db, invoice, {"status": "uncertain", "evidence": proof}, actor, "原删除结果仍待核对，不会自动重发；可保留远端原单结束取消")
    return save(db, invoice, {"status": "blocked" if proof["blockers"] else "pending", "evidence": proof}, actor,
                "请处理关联单据后重新核对" if proof["blockers"] else "未发现本地已知阻塞；小满仍会检查确认态、审批及其他下游")


def remove_remote(db, invoice, actor):
    if not invoice.cancellation:
        raise ValueError("请先发起取消")
    if invoice.cancellation["status"] in TERMINAL:
        return invoice.cancellation
    if invoice.cancellation["status"] in {"deleting", "uncertain"}:
        return refresh(db, invoice, actor)
    # Token acquisition may commit. Finish it before the final lock and POST.
    token = okki_client.ensure_access_token(db)
    proof = inspect(db, invoice)
    invoice = service.get_invoice(db, invoice.id, for_update=True)
    db.refresh(invoice)
    if invoice.status != "cancel_pending" or invoice.cancellation["status"] not in {"pending", "blocked"}:
        return invoice.cancellation
    if proof["blockers"]:
        return save(db, invoice, {"status": "blocked", "evidence": proof}, actor, "存在关联单据，未发送小满删除请求")
    if not proof["remote_exists"]:
        invoice.status = "cancelled"
        return save(db, invoice, {"status": "remote_deleted", "evidence": proof}, actor, "已核实小满订单不存在，方舟原单保留")
    token_id = uuid4().hex
    save(db, invoice, {"status": "deleting", "token": token_id,
                      "lease_until": (beijing_now() + timedelta(minutes=5)).isoformat(), "evidence": proof}, actor, "删除意图已保存，正在请求小满")
    invoice = service.get_invoice(db, invoice.id, for_update=True)
    db.refresh(invoice)
    state = invoice.cancellation
    if state["status"] != "deleting" or state["token"] != token_id or datetime.fromisoformat(state["lease_until"]) <= beijing_now():
        raise ValueError("删除执行权已失效，请核对原任务")
    try:
        lifecycle_remote.request(token, "order", invoice.xiaoman_order_id, remove=True)
        after = lifecycle_remote.request(token, "order", invoice.xiaoman_order_id)
        if after is not None:
            raise okki_client.OkkiOutcomeUncertainError("小满仍返回原订单")
    except okki_client.OkkiApiError as exc:
        logger.warning("Order cancellation awaits reconciliation (%s)", type(exc).__name__)
        print(f"[invoice-cancel] awaits reconciliation ({type(exc).__name__})", flush=True)
        return save(db, invoice, {"status": "uncertain"}, actor, "小满尚未确认删除；请核对审批、确认状态及下游单据，不会重发")
    invoice.status = "cancelled"
    return save(db, invoice, {"status": "remote_deleted"}, actor, "小满删除已回读确认；方舟原单、ID与审计记录保留")


def retain(db, invoice, reason, actor, confirmed):
    if not confirmed or len(reason.strip()) < 10:
        raise ValueError("请核实退货、退款及库存事项，填写至少10字处理依据")
    if not invoice.cancellation or invoice.cancellation["status"] == "aborted":
        raise ValueError("请先发起取消")
    if invoice.cancellation["status"] in TERMINAL:
        return invoice.cancellation
    lease = invoice.cancellation.get("lease_until")
    if lease and datetime.fromisoformat(lease) > beijing_now():
        raise ValueError("原删除任务尚未过期，请稍后核对")
    invoice.status = "cancelled"
    return save(db, invoice, {"status": "retained", "resolution_reason": reason.strip(), "resolved_by": actor}, actor,
        "业务已取消，远端单据及原货款、库存记录保留；此操作不代表已退货、退款或库存冲销")


def abort(db, invoice, actor, reason):
    if not invoice.cancellation or invoice.cancellation["status"] not in {"pending", "blocked"}:
        raise ValueError("仅尚未发送删除的取消流程可撤回")
    invoice.status = invoice.cancellation["previous_status"]
    return save(db, invoice, {"status": "aborted", "resolution_reason": reason}, actor, "取消申请已撤回，恢复原业务状态")
