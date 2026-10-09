"""Inspection-completed quantities from exact local outbound associations."""
import logging
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from app.core.time import beijing_now
from app.invoice import detail_access, detail_outbound_mirror
from app.invoice.models import Invoice, OkkiOutboundTask
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementItem
from app.receipt import access as receipt_access
from app.shipping_inspection import outbound_service, outbound_sync_state
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection

# Operation history belongs to this detail panel, never the navigation badge.
EVENT_BAD = ("sync_failed", "sync_uncertain", "recheck_required", "delete_uncertain", "delete_failed")

logger = logging.getLogger(__name__)


def annotate_inspections(db, invoice, documents, user, scope):
    """Batch-load inspections and events after applying their independent scope."""
    from app.shipping_inspection.router import _inspection_scope
    try:
        inspection_scope = _inspection_scope(db, user)
        visible = {d["record_id"] for d in documents} if inspection_scope is None or inspection_scope == scope else {
            d["record_id"] for d in detail_outbound_mirror.read(db, invoice, inspection_scope)}
    except HTTPException:
        visible = set()
    identities = [d["record_id"] for d in documents]
    inspections = {i.outbound_record_id: i for i in db.query(ShippingInspection).filter(
        ShippingInspection.outbound_record_id.in_(identities)).all()} if identities else {}
    events = {e.request_id: e for e in db.query(ShippingOperationEvent).filter(
        ShippingOperationEvent.scope == outbound_sync_state.SCOPE, ShippingOperationEvent.request_id.in_(identities)).all()} if identities else {}
    for document in documents:
        identity = document["record_id"]
        inspection, event = inspections.get(identity), events.get(identity)
        document["inspection"] = {"state": "ready" if identity in visible else "restricted",
            "status": (inspection.status if inspection else "not_inspected") if identity in visible else None}
        evidence = event.result or {} if event else {}
        document["inspection_blocked"] = bool(event and (event.action in outbound_sync_state.BLOCKED or evidence.get("required_recheck_ids")))
        verified_time = (evidence.get("verified") or {}).get("update_time")
        document["quantity_unverified"] = bool(verified_time and (not document.get("mirror_updated_at") or str(document["mirror_updated_at"]) < str(verified_time)))
        if verified_time and str(document.get("mirror_updated_at")) == str(verified_time):
            document["quantity_unverified"] = not outbound_service.mirror_matches_snapshot(db, identity, evidence["verified"])
        if event and event.action in EVENT_BAD and event.action != "recheck_required":
            document["anomaly"] = event.action
        elif identity in visible and document["inspection_blocked"]:
            document["anomaly"] = "recheck_required"


def project(invoice, documents, *, presale_outbounds=None):
    from app.invoice.presale_lines import remote_items, remote_quantity
    projected = remote_items(invoice) if invoice.order_type == "presale" else invoice.items
    wanted = {}
    for item in projected:
        key = (str(item.xiaoman_unique_id or ""), str(item.product_id or ""), str(item.sku_id or ""))
        if not all(key) or key in wanted:
            raise ValueError("订单行尚未精确映射，实际出库数量待核验")
        wanted[key] = item
    shipped = {item.id: Decimal(0) for item in projected}
    result, seen = [], set()
    for doc in documents:
        identity = str(doc.get("outbound_invoice_id") or "")
        if not identity or identity in seen or not isinstance(doc.get("record_list"), list):
            raise ValueError("出库单身份或状态待核对")
        seen.add(identity)
        inspection = doc.get("inspection") or {}
        if inspection.get("state") != "ready":
            raise ValueError("部分关联出库单的检验状态不可见，进度待核验")
        if inspection.get("status") not in ("submitted", "draft", "not_inspected") or doc.get("quantity_unverified"):
            raise ValueError("出库镜像或检验状态待核验，请先完成出库资料刷新")
        actual_shipped = inspection.get("status") == "submitted" and not doc.get("inspection_blocked")
        if presale_outbounds is not None and identity in presale_outbounds:
            local = presale_outbounds[identity]
            expected = {str(x["order_record_id"]): Decimal(str(x["outbound_count"])) for x in local.payload["record_list"]}
            current = {str(x.get("order_record_id")): Decimal(str(x.get("outbound_count"))) for x in doc["record_list"]}
            if expected != current or len(current) != len(doc["record_list"]) or any(str(x.get("order_id")) != str(invoice.xiaoman_order_id) for x in doc["record_list"]):
                raise ValueError("预售出库数量已变化，请核对原单")
        lines, line_ids = [], set()
        for row in doc.get("record_list", []):
            if str(row.get("order_id")) != str(invoice.xiaoman_order_id):
                continue
            key = (str(row.get("order_record_id") or ""), str(row.get("product_id") or ""), str(row.get("sku_id") or ""))
            item = wanted.get(key)
            if item is None or key in line_ids:
                raise ValueError("出库明细关联异常，请核对订单行")
            line_ids.add(key)
            qty = Decimal(str(row.get("outbound_count")))
            if not qty.is_finite() or qty < 0 or qty != qty.to_integral_value():
                raise ValueError("出库数量或单位待核对")
            if actual_shipped:
                shipped[item.id] += qty
            lines.append({"invoice_item_id": item.id, "product_name": item.product_name, "quantity": str(qty), "ordered_quantity": remote_quantity(item)})
        result.append({"id": identity, "number": doc.get("serial_id") or identity,
            "state": "shipped" if actual_shipped else "generated", "date": doc.get("outbound_time") or doc.get("create_time"),
            "maker_name": doc.get("maker_name"), "inspection": inspection, "anomaly": doc.get("anomaly"),
            "items": lines, "quantity": str(sum((Decimal(x["quantity"]) for x in lines), Decimal(0)))})
    if any(shipped[i.id] > remote_quantity(i) for i in projected):
        raise ValueError("实际出库超过订单数量，请核对原单")
    return result, {str(k): str(v) for k, v in shipped.items()}


def read(db, invoice, user):
    from app.invoice.presale_lines import remote_items, remote_quantity
    projected = remote_items(invoice) if invoice.order_type == "presale" else invoice.items
    scope = detail_access.outbound_scope(db, user)
    result = {"state": "unverified", "items": [], "batches": [], "tasks": [], "summary": None,
              "checked_at": None, "message": "", "source": "inspection"}
    from sqlalchemy import literal_column
    from app.shipping_inspection.list_sort_service import local_retry_at
    retry_at = literal_column(local_retry_at(db).replace("t.", "ark_okki_outbound_tasks.").replace("f.", "ark_invoices."))
    tasks = detail_access.local_outbound_query(db.query(OkkiOutboundTask, retry_at).join(Invoice,
        Invoice.id == OkkiOutboundTask.invoice_id), scope).filter(Invoice.id == invoice.id,
        OkkiOutboundTask.order_id == Invoice.xiaoman_order_id).all()
    result["tasks"] = [{"number": invoice.invoice_no, "state": "retrying" if retry else t.status} for t, retry in tasks]
    can_batch = detail_access.allowed(user, "shipment") and (receipt_access.all_access(user) or invoice.sales_user_id == receipt_access.user_id(user))
    can_funds = False
    if can_batch:
        try:
            detail_access.require_receipts(db, invoice, user)
            can_funds = True
        except HTTPException:
            pass
    batches = db.query(ShipmentSettlement).filter_by(invoice_id=invoice.id).order_by(ShipmentSettlement.sequence).all() if can_batch else []
    batch_ids = [batch.id for batch in batches]
    batch_items = {}
    for item in db.query(SettlementItem).filter(SettlementItem.settlement_id.in_(batch_ids)).all() if batch_ids else []:
        batch_items.setdefault(item.settlement_id, []).append(item)
    batch_outbounds = {out.settlement_id: out for out in db.query(ShipmentOutbound).filter(
        ShipmentOutbound.settlement_id.in_(batch_ids)).all()} if batch_ids else {}
    names = {i.id: i.product_name for i in invoice.items}
    for batch in batches:
        items = batch_items.get(batch.id, [])
        out = batch_outbounds.get(batch.id)
        result["batches"].append({"number": batch.settlement_no, "state": batch.state,
            "outbound_id": out.remote_id if out else None, "outbound_state": out.status if out else None,
            "sequence": batch.sequence, "currency": invoice.currency, "is_final": bool(batch.is_final),
            "amounts": {k: batch.quote.get(k) for k in ("goods_amount", "packaging_amount", "handling_amount", "freight_amount", "deposit_applied", "goods_payment_due")} if can_funds else None,
            "items": [{"invoice_item_id": i.invoice_item_id, "product_name": i.snapshot.get("product_name") or names.get(i.invoice_item_id, "关联商品"),
                "quantity": i.quantity, "sale_price": i.snapshot.get("sale_price") if can_funds else None,
                "line_amount": str(i.line_amount) if can_funds else None} for i in items]})
    if invoice.order_type == "presale" and not can_batch:
        result["message"] = "无发货批次查看范围，实际出库进度待核验"
        return result
    if not invoice.xiaoman_order_id:
        result.update(state="ready", checked_at=beijing_now(), summary={"ordered_quantity": sum(remote_quantity(i) for i in projected),
            "shipped_quantity": "0", "by_item": {str(i.id): "0" for i in invoice.items}})
        return result
    try:
        documents = detail_outbound_mirror.read(db, invoice, scope)
        # A narrow list must not become a misleading whole-order percentage.
        if scope is not None and {d["record_id"] for d in documents} != {
                d["record_id"] for d in detail_outbound_mirror.read(db, invoice, None)}:
            raise HTTPException(403, "部分关联出库单不在当前查看范围内")
        annotate_inspections(db, invoice, documents, user, scope)
        names = {str(i.xiaoman_unique_id): i.product_name for i in invoice.items if i.xiaoman_unique_id}
        result["items"] = [{"id": str(d["outbound_invoice_id"]), "number": d.get("serial_id") or str(d["outbound_invoice_id"]),
            "state": "uncertain", "date": d.get("outbound_time"), "quantity": None,
            "inspection": d["inspection"], "maker_name": d.get("maker_name"), "anomaly": d.get("anomaly"),
            "items": [{"product_name": names.get(str(r.get("order_record_id")), "关联行待核对"), "quantity": str(r.get("outbound_count")), "ordered_quantity": None}
                      for r in d["record_list"] if str(r.get("order_id")) == str(invoice.xiaoman_order_id)]} for d in documents]
        local = {o.remote_id: o for o in db.query(ShipmentOutbound).filter_by(invoice_id=invoice.id).all() if o.remote_id} if invoice.order_type == "presale" else None
        if local is not None and not set(local) <= {str(d["outbound_invoice_id"]) for d in documents}:
            raise ValueError("已生成的预售出库单尚未进入镜像，进度待核验")
        items, by_item = project(invoice, documents, presale_outbounds=local)
        result.update(state="ready", items=items, checked_at=beijing_now(), summary={"ordered_quantity": sum(remote_quantity(i) for i in projected),
            "shipped_quantity": str(sum((Decimal(v) for v in by_item.values()), Decimal(0))), "by_item": by_item})
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("invoice outbound verification unavailable invoice=%s: %s", invoice.id, type(exc).__name__)
        print(f"[invoice_detail] outbound verification unavailable invoice={invoice.id}: {type(exc).__name__}", flush=True)
        result["message"] = str(exc) if isinstance(exc, (ValueError, InvalidOperation)) else "出库镜像或检验记录读取失败，请重试；任务与批次记录已保留"
    return result
