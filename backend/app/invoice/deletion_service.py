"""One reviewed cancellation, durable steps, and no replay of ambiguous deletes."""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from app.auth.dependencies import require_permission
from app.core.time import beijing_now
from app.invoice import cancellation_service, lifecycle_remote, linked_outbound_service, okki_client, service
from app.invoice.linked_sync_service import edit_version
from app.invoice.models import OkkiOutboundTask
from app.receipt import access, deletion_evidence, remote, service as receipts
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection import outbound_delete_service, outbound_service, outbound_sync_state

logger = logging.getLogger(__name__)
REASON = "订单发票页已确认删除订单及关联出库和回款单据"


def _order_content(order):
    # Receipt deletion can change payment status/update_time without changing the contract.
    from app.invoice.xiaoman_service import FIELD_ORDER_TYPE, FIELD_NEW_DEAL, FIELD_FREE_SHIPPING, FIELD_FIRST_RETURN
    return {key: (order or {}).get(key) for key in (
        "order_id", "company_id", "currency", "name", "amount", "product_list", "cost_list", "remark",
        "account_date", "create_user", "handler", "users", "departments", "exchange_rate", "exchange_rate_usd",
        FIELD_ORDER_TYPE, FIELD_NEW_DEAL, FIELD_FREE_SHIPPING, FIELD_FIRST_RETURN)}


def _local_rows(db, invoice):
    return db.query(Receipt).filter_by(invoice_id=invoice.id).order_by(Receipt.id).populate_existing().all()


def _invoice_stamp(invoice):
    return {"edit": edit_version(invoice), "order_id": invoice.xiaoman_order_id,
            "status": invoice.status, "sync_status": invoice.sync_status,
            "amounts": {key: str(getattr(invoice, key)) for key in (
                "total_amount", "product_amount", "shipping_fee", "surcharge_amount", "internal_accessory")},
            "cancellation": hashlib.sha256(json.dumps(invoice.cancellation, sort_keys=True, default=str).encode()).hexdigest()}


def _local_stamp(local):
    return [{"id": r.id, "version": r.version, "status": r.status, "sync_status": r.sync_status,
             "remote_id": r.xiaoman_receipt_id, "amount": str(r.amount), "bank_charge": str(r.bank_charge),
             "batch_id": r.batch_id, "purpose": r.purpose, "currency": r.currency, "customer_id": r.customer_id} for r in local]


def _workflow(invoice):
    return (invoice.cancellation or {}).get("deletion") or {}


def _warn(exc):
    logger.warning("Invoice deletion paused (%s)", type(exc).__name__)
    print(f"[invoice-deletion] paused ({type(exc).__name__})", flush=True)


def _guards(db, invoice, blockers):
    if not invoice.xiaoman_order_id:
        blockers.append("未同步草稿请使用草稿删除入口")
    if invoice.linked_sync_id or invoice.sync_status == "sync_uncertain" or invoice.sync_attempt:
        blockers.append("订单同步正在执行或结果待核对，请先核实原任务")
    if invoice.order_type == "presale":
        blockers.append("预售订单涉及分批结算，请先处理关联结算，不能整单自动删除")
    if invoice.status == "cancelled" and not _workflow(invoice):
        blockers.append("订单已归档，请查看原取消记录")
    if (invoice.cancellation or {}).get("status") in {"deleting", "uncertain"} and not _workflow(invoice):
        blockers.append("原订单删除结果待核对，请先核实原取消任务，禁止重新发送删除")
    task = db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).first()
    if task and task.status in {"running", "uncertain"}:
        blockers.append("自动出库正在执行或结果待核对")
    if task and (task.reason or "").startswith("delete_pending:"):
        key = "outbound:" + task.reason.split(":", 1)[1]
        if key not in _workflow(invoice).get("steps", {}):
            blockers.append("关联出库删除正在执行或待核对，请先完成原删除任务")
    try:
        outbound_sync_state.ensure_invoice_idle(db, invoice)
    except ValueError as exc:
        blockers.append(str(exc))
    allocations = db.query(InvoiceAllocation).filter_by(invoice_id=invoice.id).all()
    if any(a.status == "pending" or Decimal(a.allocated_qty_grams or 0) != 0
           or Decimal(a.pending_delta_grams or 0) != 0 for a in allocations):
        blockers.append("仍有半成品库存预占或出库记录，请先恢复库存")
    intent = db.query(ReceiptIntent).filter_by(invoice_id=invoice.id).first()
    if intent and (intent.attempt_token or intent.status in {"armed", "ready"}):
        blockers.append("自动回款正在处理，请先核实原任务")


def collect(db, invoice, user):
    """Discover all live links and validate all permissions before any deletion."""
    stamp = _invoice_stamp(invoice)
    blockers = []
    _guards(db, invoice, blockers)
    local = _local_rows(db, invoice)
    detail = lifecycle_remote.read(db, "order", invoice.xiaoman_order_id) if invoice.xiaoman_order_id else None
    if detail and (str(detail.get("company_id")) != str(invoice.customer_id)
                  or detail.get("currency") != invoice.currency):
        blockers.append("小满订单客户或币种与方舟不一致")
    order = detail if detail and remote.order_active(db, detail) else None
    source_order = detail or _workflow(invoice).get("order")
    if invoice.xiaoman_order_id and not source_order:
        blockers.append("原小满订单已缺失，无法完整核验关联出库，请先处理原取消记录")
    outbounds = linked_outbound_service.find_related(db, source_order) if source_order else []
    indexed = remote.order_receipts(db, invoice.xiaoman_order_id) if invoice.xiaoman_order_id else []
    if indexed or any(r.status == "active" for r in local):
        require_permission("receipt:admin")(user)
        access.ensure_invoice(db, invoice, user)
    records = {}
    pending_outbounds = {k.split(":", 1)[1]: v for k, v in _workflow(invoice).get("steps", {}).items()
                        if k.startswith("outbound:") and v.get("status") in {"sending", "uncertain"}}
    if outbounds or pending_outbounds:
        require_permission("shipping_inspection:delete")(user)
        from app.shipping_inspection.router import _outbound_scope
        scope = _outbound_scope(db, user)
        for doc in outbounds:
            identity = str(doc["outbound_invoice_id"])
            record = outbound_service.get_record_by_outbound_invoice_id(db, identity, okki_user_id=scope)
            if record is None:
                raise HTTPException(404, "关联出库单尚未同步或不在当前账号的数据范围")
            records[identity] = record
            if str(doc.get("status")) != "1":
                blockers.append(f"出库单 {doc.get('serial_id') or identity} 已出库，不能自动删除")
            lines = doc.get("record_list")
            if not isinstance(lines, list) or not lines or any(
                    str(line.get("order_id")) != str(invoice.xiaoman_order_id) for line in lines):
                blockers.append(f"出库单 {identity} 关联其他订单或明细不完整，不能整张删除")
        # Recover exact prior intents even after the active list / mirror removes them.
        from app.shipping_inspection.models import ShippingOperationEvent
        for identity, step in pending_outbounds.items():
            if identity in records:
                continue
            event = db.query(ShippingOperationEvent).filter_by(scope=outbound_delete_service.SCOPE, request_id=identity).first()
            if scope is not None and (event is None or event.login_user_id != access.user_id(user)):
                raise HTTPException(404, "原出库删除记录不在当前账号的数据范围")
            records[identity] = step["record"]
    details = []
    for row in indexed:
        identity = str(row["cash_collection_id"])
        data = lifecycle_remote.read(db, "receipt", identity)
        if data is None or str(data.get("order_id")) != str(invoice.xiaoman_order_id) or data.get("currency") != invoice.currency:
            blockers.append(f"回款 {identity} 的远端证据不一致，请刷新核对")
        else:
            details.append(data)
    remote_ids = {str(r["cash_collection_id"]) for r in details}
    for row in local:
        if row.status != "active":
            continue
        if row.batch_id or row.purpose == "presale_deposit":
            blockers.append("回款属于汇总批次或预售首款，不能整单自动删除")
        if row.currency != invoice.currency or str(row.customer_id) != str(invoice.customer_id):
            blockers.append(f"回款 {row.receipt_no} 的客户或币种与订单不一致")
        if row.sync_status in {"syncing", "uncertain"} and not row.xiaoman_receipt_id:
            blockers.append("回款正在发送或结果待核对，请先核实原回款")
        elif row.sync_status == "syncing":
            blockers.append("回款正在发送，请稍后再删除")
        if row.xiaoman_receipt_id and row.xiaoman_receipt_id not in remote_ids:
            if not _receipt_absent(db, invoice.xiaoman_order_id, row.xiaoman_receipt_id, invoice.currency):
                blockers.append(f"回款 {row.receipt_no} 详情与有效列表不一致")
        if not row.xiaoman_receipt_id and row.sync_status not in {"pending", "failed"}:
            blockers.append(f"回款 {row.receipt_no} 尚未明确远端结果")
    plan = {"invoice": stamp, "order": order, "outbounds": outbounds, "receipts": details,
            "local": _local_stamp(local),
            "blockers": sorted(set(blockers))}
    version = hashlib.sha256(json.dumps({"edit": edit_version(invoice), "order_id": invoice.xiaoman_order_id,
        "status": invoice.status, "sync_status": invoice.sync_status, "plan": plan,
        "progress": _workflow(invoice).get("steps", {})}, sort_keys=True, default=str).encode()).hexdigest()
    return plan, records, version


def preview(db, invoice, user):
    plan, _, version = collect(db, invoice, user)
    flow = _workflow(invoice)
    return {"version": version, "invoice_no": invoice.invoice_no,
            "outbounds": [{"id": str(d["outbound_invoice_id"]), "number": d.get("serial_id"), "status": d.get("status")} for d in plan["outbounds"]],
            "receipts": [{"id": str(r["cash_collection_id"]), "number": r.get("cash_collection_no"),
                          "amount": str(r.get("amount")), "currency": r.get("currency")} for r in plan["receipts"]],
            "local_receipt_count": sum(r["status"] == "active" for r in plan["local"]),
            "blockers": plan["blockers"], "progress": flow.get("steps", {}),
            "complete": (invoice.cancellation or {}).get("status") == "remote_deleted"}


def _lock(db, identity):
    invoice = service.get_invoice(db, identity, for_update=True)
    db.refresh(invoice)
    return invoice


def _owned(db, identity, token):
    invoice = _lock(db, identity)
    flow = _workflow(invoice)
    if flow.get("token") != token or datetime.fromisoformat(flow["lease_until"]) <= beijing_now():
        raise ValueError("删除执行权已变化或过期，请从订单发票页重新核对处理结果")
    return invoice


def _save(db, invoice, flow, actor, status, message):
    return cancellation_service.save(db, invoice, {"status": status, "deletion": flow,
        "reason": REASON, "lease_until": flow.get("lease_until")}, actor, message)


def _step(db, identity, token, key, value, actor):
    invoice = _owned(db, identity, token)
    flow = _workflow(invoice)
    flow = {**flow, "steps": {**flow.get("steps", {}), key: value},
            "lease_until": (beijing_now() + timedelta(minutes=5)).isoformat()}
    _save(db, invoice, flow, actor, "cascade_running", value.get("message", "正在自动删除关联单据"))
    return flow


def _receipt_absent(db, order_id, identity, currency):
    return deletion_evidence.absent(db, order_id, identity, currency)


def _delete_receipt(db, invoice_id, token, row, actor):
    identity = str(row["cash_collection_id"])
    key = "receipt:" + identity
    invoice = _owned(db, invoice_id, token)
    state = _workflow(invoice).get("steps", {}).get(key, {}).get("status")
    db.commit()
    if state == "done":
        return
    if state in {"sending", "uncertain"}:
        if not _receipt_absent(db, invoice.xiaoman_order_id, identity, invoice.currency):
            raise ValueError("原回款删除结果待核对，未重复发送删除")
    else:
        api_token = okki_client.ensure_access_token(db)
        current = lifecycle_remote.request(api_token, "receipt", identity)
        if current is not None:
            if str(current.get("order_id")) != invoice.xiaoman_order_id or current.get("currency") != invoice.currency:
                raise ValueError("回款关联订单或币种变化，未删除")
            if current != row:
                raise ValueError("回款资料在确认后变化，请刷新重新确认")
            _step(db, invoice_id, token, key, {"status": "sending", "before": row}, actor)
            _owned(db, invoice_id, token)
            try:
                lifecycle_remote.request(api_token, "receipt", identity, remove=True)
            except okki_client.OkkiApiError as exc:
                _warn(exc)
            if not _receipt_absent(db, invoice.xiaoman_order_id, identity, invoice.currency):
                _step(db, invoice_id, token, key, {"status": "uncertain", "before": row}, actor)
                raise ValueError("小满回款删除结果待核对，未继续删除订单")
        elif not _receipt_absent(db, invoice.xiaoman_order_id, identity, invoice.currency):
            raise ValueError("回款删除证据不一致")
    _step(db, invoice_id, token, key, {"status": "done", "before": row}, actor)


def run(db, identity, user, expected_version):
    actor = access.user_id(user)
    invoice = service.get_invoice(db, identity)
    plan, records, version = collect(db, invoice, user)
    db.commit()  # Token refresh and read transactions must finish before the claim.
    invoice = _lock(db, identity)
    flow = _workflow(invoice)
    if (invoice.cancellation or {}).get("status") == "remote_deleted":
        return {"status": "remote_deleted", "message": "订单及关联单据已删除，方舟记录已归档", "steps": flow.get("steps", {})}
    if version != expected_version:
        raise ValueError("订单或关联单据已变化，请刷新后重新确认删除")
    if flow.get("token") and datetime.fromisoformat(flow["lease_until"]) > beijing_now():
        return {"status": "running", "message": "原删除任务正在执行，请稍后核对", "steps": flow.get("steps", {})}
    if _invoice_stamp(invoice) != plan["invoice"] or _local_stamp(_local_rows(db, invoice)) != plan["local"]:
        raise ValueError("订单或回款在核对期间变化，请刷新后重新确认删除")
    # Recheck local writers while holding the same invoice lock used by senders.
    blockers = list(plan["blockers"])
    _guards(db, invoice, blockers)
    if blockers:
        return {"status": "blocked", "message": "；".join(sorted(set(blockers))), "steps": flow.get("steps", {})}
    token = uuid4().hex
    previous = (invoice.cancellation or {}).get("previous_status", invoice.status)
    invoice.status = "cancel_pending"
    flow = {**flow, "token": token, "lease_until": (beijing_now() + timedelta(minutes=5)).isoformat(),
            "order": plan["order"] or flow.get("order"), "plan": plan, "steps": flow.get("steps", {}), "actor": actor}
    invoice.cancellation = {**(invoice.cancellation or {}), "previous_status": previous}
    _save(db, invoice, flow, actor, "cascade_running", "已冻结订单，正在自动删除关联出库和回款")
    try:
        prior_outbounds = [v["before"] for k, v in flow["steps"].items() if k.startswith("outbound:")
                          and v.get("status") in {"sending", "uncertain"}]
        outbound_rows = {str(d["outbound_invoice_id"]): d for d in [*prior_outbounds, *plan["outbounds"]]}
        for doc in outbound_rows.values():
            key = "outbound:" + str(doc["outbound_invoice_id"])
            record = records[str(doc["outbound_invoice_id"])]
            _step(db, identity, token, key, {"status": "sending", "before": doc, "record": record}, actor)
            _owned(db, identity, token)
            outbound_delete_service.delete_outbound(db, record, actor,
                expected_order_id=invoice.xiaoman_order_id, expected_snapshot=doc)
            _step(db, identity, token, key, {"status": "done", "number": doc.get("serial_id")}, actor)
        # Ambiguous receipt attempts may disappear from a later live preview.
        old = [v["before"] for k, v in flow["steps"].items() if k.startswith("receipt:")
               and v.get("status") in {"sending", "uncertain"}]
        rows = {str(r["cash_collection_id"]): r for r in [*old, *plan["receipts"]]}
        for row in rows.values():
            _delete_receipt(db, identity, token, row, actor)
        # Local ledger changes retain amounts, IDs, fee allocations and proofs.
        invoice = _owned(db, identity, token)
        reviewed_local = {row["id"]: row for row in plan["local"]}
        for row in _local_rows(db, invoice):
            if row.status != "active":
                continue
            if row.xiaoman_receipt_id:
                if not _receipt_absent(db, invoice.xiaoman_order_id, row.xiaoman_receipt_id, invoice.currency):
                    raise ValueError("仍有有效回款，未继续删除订单")
                invoice = _owned(db, identity, token)
                db.refresh(row, with_for_update=True)
                if _local_stamp([row])[0] != reviewed_local.get(row.id):
                    raise ValueError("方舟回款在删除期间变化，请刷新后继续核对")
                row.status, row.collect_status = "remote_deleted", None
                row.version += 1
                receipts.log(db, row, "remote_deleted", REASON + "；已核实小满不存在，原资金和凭证保留", actor)
            else:
                db.refresh(row, with_for_update=True)
                if _local_stamp([row])[0] != reviewed_local.get(row.id):
                    raise ValueError("方舟回款在删除期间变化，请刷新后继续核对")
                receipts.void(db, row, REASON, actor)
        _step(db, identity, token, "local_receipts", {"status": "done"}, actor)
        # Verify no unreviewed links appeared before deleting the parent.
        invoice = _owned(db, identity, token)
        fresh, _, _ = collect(db, invoice, user)
        if fresh["blockers"] or fresh["outbounds"] or fresh["receipts"]:
            raise ValueError("关联单据仍存在或发生变化，已完成步骤保留，请刷新后继续")
        if fresh["order"] is not None and _order_content(fresh["order"]) != _order_content(plan["order"]):
            raise ValueError("小满订单内容在确认后变化，未删除订单，请刷新重新确认")
        api_token = okki_client.ensure_access_token(db)
        invoice = _owned(db, identity, token)
        order_state = _workflow(invoice).get("steps", {}).get("order", {}).get("status")
        db.commit()
        if order_state not in {"sending", "uncertain", "done"} and fresh["order"] is not None:
            _step(db, identity, token, "order", {"status": "sending"}, actor)
            _owned(db, identity, token)
            try:
                lifecycle_remote.request(api_token, "order", invoice.xiaoman_order_id, remove=True)
            except okki_client.OkkiApiError as exc:
                _warn(exc)
        after = lifecycle_remote.request(api_token, "order", invoice.xiaoman_order_id)
        if after is not None and remote.order_active(db, after):
            _step(db, identity, token, "order", {"status": "uncertain"}, actor)
            raise ValueError("小满订单删除结果待核对，未重复发送删除")
        _step(db, identity, token, "order", {"status": "done"}, actor)
        invoice = _owned(db, identity, token)
        invoice.status = "cancelled"
        flow = {**_workflow(invoice), "token": None, "lease_until": None}
        result = _save(db, invoice, flow, actor, "remote_deleted", "小满订单及关联单据已删除，方舟发票、回款凭证和审计记录已归档")
        return {"status": result["status"], "message": result["message"], "steps": flow["steps"]}
    except (ValueError, okki_client.OkkiApiError, outbound_delete_service.OutboundDeleteError) as exc:
        _warn(exc)
        db.rollback()
        invoice = _lock(db, identity)
        if _workflow(invoice).get("token") != token:
            raise ValueError("删除执行权已变化，请核对当前处理结果") from exc
        flow = {**_workflow(invoice), "token": None, "lease_until": None}
        unknown = any(s.get("status") in {"sending", "uncertain"} for s in flow["steps"].values())
        result = _save(db, invoice, flow, actor, "cascade_uncertain" if unknown else "cascade_blocked", str(exc))
        return {"status": "uncertain" if unknown else "blocked", "message": result["message"], "steps": flow["steps"]}
