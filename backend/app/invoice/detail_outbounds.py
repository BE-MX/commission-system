"""Actual shipped quantities: exact order line identity, never generated task counts."""
import logging
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from app.core.time import beijing_now
from app.invoice import detail_access, linked_outbound_service, settlement_service
from app.invoice.models import Invoice, OkkiOutboundTask
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementItem
from app.receipt import remote, access as receipt_access
from app.shipping_inspection import outbound_service
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection

# Operation history belongs to this detail panel, never the navigation badge.
EVENT_BAD = ("sync_failed", "sync_uncertain", "recheck_required", "delete_uncertain", "delete_failed")

logger = logging.getLogger(__name__)


def inspection_metadata(db, record, user):
    """Inspection visibility is narrower than outbound-list visibility."""
    if not record:
        return {"state": "unverified", "status": None}
    from app.shipping_inspection.router import _inspection_scope
    try:
        scope = _inspection_scope(db, user)
        if scope is not None and outbound_service.get_outbound_record(db, record["outbound_record_id"], okki_user_id=scope) is None:
            return {"state": "restricted", "status": None}
    except HTTPException:
        return {"state": "restricted", "status": None}
    inspection = db.query(ShippingInspection).filter_by(outbound_record_id=record["outbound_record_id"]).first()
    return {"state": "ready", "status": inspection.status if inspection else "not_inspected"}


def project(invoice, documents, *, presale_outbounds=None):
    wanted = {}
    for item in invoice.items:
        key = (str(item.xiaoman_unique_id or ""), str(item.product_id or ""), str(item.sku_id or ""))
        if not all(key) or key in wanted:
            raise ValueError("订单行尚未精确映射，实际出库数量待核验")
        wanted[key] = item
    shipped = {item.id: Decimal(0) for item in invoice.items}
    result, seen = [], set()
    for doc in documents:
        identity = str(doc.get("outbound_invoice_id") or "")
        if not identity or identity in seen or str(doc.get("status")) not in ("1", "2") or not isinstance(doc.get("record_list"), list):
            raise ValueError("出库单身份或状态待核对")
        seen.add(identity)
        actual_shipped = str(doc["status"]) == "2"
        if presale_outbounds is not None:
            local = presale_outbounds.get(identity)
            if local is None or (local.status == "shipped") != actual_shipped:
                raise ValueError("预售本地出库与小满事实不一致，请核对原单")
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
            lines.append({"invoice_item_id": item.id, "product_name": item.product_name, "quantity": str(qty), "ordered_quantity": item.quantity})
        result.append({"id": identity, "number": doc.get("serial_id") or identity,
            "state": "shipped" if actual_shipped else "generated", "date": doc.get("outbound_time") or doc.get("create_time"),
            "items": lines, "quantity": str(sum((Decimal(x["quantity"]) for x in lines), Decimal(0)))})
    if any(shipped[i.id] > i.quantity for i in invoice.items):
        raise ValueError("实际出库超过订单数量，请核对原单")
    return result, {str(k): str(v) for k, v in shipped.items()}


def read(db, invoice, user):
    scope = detail_access.outbound_scope(db, user)
    result = {"state": "unverified", "items": [], "batches": [], "tasks": [], "summary": None,
              "checked_at": None, "message": ""}
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
    for batch in batches:
        items = db.query(SettlementItem).filter_by(settlement_id=batch.id).all()
        names = {i.id: i.product_name for i in invoice.items}
        out = db.query(ShipmentOutbound).filter_by(settlement_id=batch.id).first()
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
        result.update(state="ready", checked_at=beijing_now(), summary={"ordered_quantity": sum(i.quantity for i in invoice.items),
            "shipped_quantity": "0", "by_item": {str(i.id): "0" for i in invoice.items}})
        return result
    try:
        order = remote.read(db, "/v1/invoices/order/info", {"order_id": invoice.xiaoman_order_id})
        if str(order.get("order_id")) != str(invoice.xiaoman_order_id) or str(order.get("company_id")) != str(invoice.customer_id):
            raise ValueError("远端订单关联身份已变化")
        if not remote.order_active(db, order):
            raise ValueError("远端订单已失效或活动状态未确认")
        documents = linked_outbound_service.find_related(db, order)
        if scope is not None:
            for doc in documents:
                if outbound_service.get_record_by_outbound_invoice_id(db, str(doc["outbound_invoice_id"]), okki_user_id=scope) is None:
                    raise HTTPException(403, "部分关联出库单尚不可见或镜像待刷新")
        names = {str(i.xiaoman_unique_id): i.product_name for i in invoice.items if i.xiaoman_unique_id}
        result["items"] = [{"id": str(d["outbound_invoice_id"]), "number": d.get("serial_id") or str(d["outbound_invoice_id"]),
            "state": "uncertain", "date": d.get("create_time"), "quantity": None,
            "items": [{"product_name": names.get(str(r.get("order_record_id")), "关联行待核对"), "quantity": str(r.get("outbound_count")), "ordered_quantity": None}
                      for r in d["record_list"] if str(r.get("order_id")) == str(invoice.xiaoman_order_id)]} for d in documents]
        local = {o.remote_id: o for o in db.query(ShipmentOutbound).filter_by(invoice_id=invoice.id).all() if o.remote_id} if invoice.order_type == "presale" else None
        if local is not None and set(local) != {str(d["outbound_invoice_id"]) for d in documents}:
            raise ValueError("预售远端出库关联待核对")
        items, by_item = project(invoice, documents, presale_outbounds=local)
        for doc in items:
            record = outbound_service.get_record_by_outbound_invoice_id(db, doc["id"], okki_user_id=scope)
            doc["maker_name"] = record.get("owner_name") if record else None
            doc["inspection"] = inspection_metadata(db, record, user)
            if record:
                event = db.query(ShippingOperationEvent).filter_by(scope="outbound-invoice-sync", outbound_record_id=record["outbound_record_id"]).first()
                if event and event.action in EVENT_BAD:
                    doc["anomaly"] = event.action
        result.update(state="ready", items=items, checked_at=beijing_now(), summary={"ordered_quantity": sum(i.quantity for i in invoice.items),
            "shipped_quantity": str(sum((Decimal(v) for v in by_item.values()), Decimal(0))), "by_item": by_item})
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("invoice outbound verification unavailable invoice=%s: %s", invoice.id, type(exc).__name__)
        print(f"[invoice_detail] outbound verification unavailable invoice={invoice.id}: {type(exc).__name__}", flush=True)
        result["message"] = str(exc) if isinstance(exc, (ValueError, InvalidOperation)) else "出库事实核验失败，请重试；任务与批次记录已保留"
    return result
