"""Cross-order shipments. Writers share order -> item locks with production reporting."""
import hashlib
import json
import logging
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, OperationalError
from app.core.time import beijing_now
from app.domestic import constants as C, balance_service, progress_service, unit_service, routing_service
from app.domestic.models import DomesticCustomer, DomesticOrder, DomesticOrderItem, DomesticItemProgress, DomesticItemUnit, DomesticCustomerRequest, DomesticReportUnit, DomesticReportLog
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentLine, DomesticShipmentUnit, DomesticReceiptAllocation


def payload_hash(payload):
    body = payload.model_dump(mode="json")
    # An omitted batch override must retain fingerprints of existing requests.
    for row in body.get("items", []):
        if row.get("unit_price") is None:
            row.pop("unit_price", None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def shipped_unit_ids(db, item_id, lock=False):
    query = db.query(DomesticShipmentUnit.unit_id).join(
        DomesticItemUnit, DomesticItemUnit.id == DomesticShipmentUnit.unit_id,
    ).filter(DomesticItemUnit.item_id == item_id)
    if lock:
        query = query.with_for_update()
    return {value for (value,) in query.all()}


def assert_units_unshipped(db, unit_ids):
    if unit_ids and db.query(DomesticShipmentUnit.id).filter(
        DomesticShipmentUnit.unit_id.in_(unit_ids),
    ).with_for_update().first():
        raise ValueError("相关单件已发货，不能撤销报工或放行")


def shipped_item_amount(db, item):
    """Value delivered quantities at the order price for order refunds/summary.

    Batch prices belong only to delivery receivables, never order accounting.
    """
    # Cancelled batches retain lines but release unit reservations. Count current
    # reservations without locking batches before the refund path's customer lock.
    values = db.query(DomesticShipmentUnit.unit_id).join(DomesticShipmentLine).filter(
        DomesticShipmentLine.item_id == item.id,
    ).with_for_update().all()
    amount = balance_service.money(item.unit_price) * len(values) if values else None
    # Existing whole-line shipments are known deliveries, without inventing receipt facts.
    if amount is None and item.status == C.ITEM_SHIPPED:
        return balance_service.money(item.unit_price) * item.order_qty
    return balance_service.money(amount)


def assert_item_unshipped(db, item):
    if item.status == C.ITEM_SHIPPED or shipped_unit_ids(db, item.id, lock=True):
        raise ValueError("该明细已有发货，不能编辑或删除；请保留交付记录")


def ready_units(db, item, lock=False):
    if item.status == C.ITEM_TERMINATED:
        return [], 0, 0
    if item.status == C.ITEM_SHIPPED:
        return [], item.order_qty, item.order_qty
    last = db.query(DomesticItemProgress).filter_by(item_id=item.id).order_by(
        DomesticItemProgress.step_order.desc(),
    ).first()
    units_query = db.query(DomesticItemUnit).filter_by(item_id=item.id, status=1).order_by(DomesticItemUnit.unit_no)
    reports = db.query(DomesticReportUnit.unit_id).join(DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id).filter(DomesticReportUnit.progress_id == (last.id if last else -1), DomesticReportLog.revoked == 0)
    if lock:
        units_query = units_query.with_for_update()
        reports = reports.with_for_update()
    units = units_query.all()
    completed = {value for (value,) in reports.all()}
    shipped = shipped_unit_ids(db, item.id, lock=lock)
    done = [unit for unit in units if unit.id in completed]
    return [unit for unit in done if unit.id not in shipped], len(done), len(shipped)


def candidate_rows(db, customer_id, user_id, can_read_all=False):
    q = db.query(DomesticOrderItem, DomesticOrder).join(
        DomesticOrder, DomesticOrder.id == DomesticOrderItem.order_id,
    ).filter(
        DomesticOrder.customer_id == customer_id, DomesticOrder.order_kind == "business",
        DomesticOrderItem.status != C.ITEM_TERMINATED,
        DomesticOrder.deleted_flag == 0,
        DomesticOrder.status.in_((C.ORDER_PRODUCING, C.ORDER_DONE)),
    )
    if not can_read_all:
        q = q.filter(DomesticOrder.created_by == user_id)
    rows = q.order_by(DomesticOrder.id, DomesticOrderItem.line_no).all()
    item_ids = [item.id for item, _order in rows if item.status != C.ITEM_SHIPPED]
    if not item_ids:
        return []
    # Load candidate identity and reporting once for the whole customer, not per row.
    last_by_item = {}
    for progress in db.query(DomesticItemProgress).filter(DomesticItemProgress.item_id.in_(item_ids)).order_by(DomesticItemProgress.step_order).all():
        last_by_item[progress.item_id] = progress.id
    units_by_item = {}
    for unit in db.query(DomesticItemUnit).filter(DomesticItemUnit.item_id.in_(item_ids), DomesticItemUnit.status == 1).order_by(DomesticItemUnit.unit_no).all():
        units_by_item.setdefault(unit.item_id, []).append(unit)
    done_by_progress = {}
    for progress_id, unit_id in db.query(DomesticReportUnit.progress_id, DomesticReportUnit.unit_id).join(
        DomesticReportLog, DomesticReportLog.id == DomesticReportUnit.log_id,
    ).filter(DomesticReportUnit.progress_id.in_(last_by_item.values()), DomesticReportLog.revoked == 0).all():
        done_by_progress.setdefault(progress_id, set()).add(unit_id)
    shipped_by_item = {}
    for item_id, unit_id in db.query(DomesticItemUnit.item_id, DomesticShipmentUnit.unit_id).join(
        DomesticItemUnit, DomesticItemUnit.id == DomesticShipmentUnit.unit_id,
    ).filter(DomesticItemUnit.item_id.in_(item_ids)).all():
        shipped_by_item.setdefault(item_id, set()).add(unit_id)
    result = []
    for item, order in rows:
        units = units_by_item.get(item.id, [])
        finished = done_by_progress.get(last_by_item.get(item.id), set())
        sent = shipped_by_item.get(item.id, set())
        done = sum(unit.id in finished for unit in units)
        shipped = len(sent)
        available = [unit for unit in units if unit.id in finished and unit.id not in sent]
        if not available:
            continue
        result.append({
            "item_id": item.id, "order_id": order.id, "domestic_no": order.domestic_no,
            "order_no": order.order_no, "line_code": f"A{item.line_no}",
            "guest_name": item.guest_name, "product_name": item.product_name,
            "order_qty": item.order_qty, "completed_qty": done, "shipped_qty": shipped,
            "available_qty": len(available), "unit_price": float(item.unit_price),
            "units": [{"id": u.id, "code": unit_service.unit_display_code(item, u.unit_no)} for u in available],
        })
    return result


def _create_shipment_once(db, payload, user_id):
    db.info["domestic_actor_id"] = user_id
    fingerprint = payload_hash(payload)
    existing = db.query(DomesticShipment).filter_by(request_id=payload.request_id).first()
    if existing:
        if existing.created_by != user_id or existing.request_hash != fingerprint:
            raise ValueError("该请求号已用于不同发货内容")
        return {**shipment_view(db, existing), "replayed": True}
    item_ids = sorted(row.item_id for row in payload.items)
    previews = db.query(DomesticOrderItem.order_id).filter(DomesticOrderItem.id.in_(item_ids)).all()
    order_ids = sorted({value for (value,) in previews})
    orders = db.query(DomesticOrder).filter(DomesticOrder.id.in_(order_ids)).order_by(
        DomesticOrder.id,
    ).populate_existing().with_for_update().all()
    # A concurrent identical request can finish these orders while we await locks.
    replay = db.query(DomesticShipment).filter_by(request_id=payload.request_id).populate_existing().with_for_update().first()
    if replay:
        if replay.created_by != user_id or replay.request_hash != fingerprint:
            raise ValueError("该请求号已用于不同发货内容")
        db.commit()
        return {**shipment_view(db, replay), "replayed": True}
    by_order = {order.id: order for order in orders}
    items = db.query(DomesticOrderItem).filter(DomesticOrderItem.id.in_(item_ids)).order_by(
        DomesticOrderItem.id,
    ).populate_existing().with_for_update().all()
    if len(items) != len(item_ids):
        raise ValueError("订单明细不存在")
    # Only the creator may operate an order, matching the existing order write contract.
    for order in orders:
        if (order.customer_id != payload.customer_id or order.created_by != user_id
                or order.deleted_flag or order.order_kind != "business"
                or order.status not in (C.ORDER_PRODUCING, C.ORDER_DONE)):
            raise ValueError("只能选择同一客户本人创建的有效业务订单")
    customer = db.get(DomesticCustomer, payload.customer_id)
    if not customer:
        raise ValueError("客户不存在")
    inputs = {row.item_id: row for row in payload.items}
    batch = DomesticShipment(
        shipment_no=f"FH{beijing_now():%Y%m%d}-{uuid4().hex[:12]}",
        customer_id=payload.customer_id, ship_time=payload.ship_time, remark=payload.remark,
        total_amount=Decimal(0), request_id=payload.request_id, request_hash=fingerprint,
        created_by=user_id,
    )
    db.add(batch)
    db.flush()
    total = Decimal(0)
    for item in items:
        row = inputs[item.id]
        available, _done, _shipped = ready_units(db, item, lock=True)
        if row.quantity > len(available):
            raise ValueError(f"{item.guest_name or ''} A{item.line_no} 最多可发 {len(available)} 件，请刷新")
        if row.unit_ids is None:
            selected = available[:row.quantity]
        else:
            by_id = {u.id: u for u in available}
            if not set(row.unit_ids).issubset(by_id):
                raise ValueError("指定单件未完工、已发货或不属于该明细")
            selected = [by_id[value] for value in row.unit_ids]
        order = by_order[item.order_id]
        price = balance_service.money(item.unit_price if row.unit_price is None else row.unit_price)
        amount = price * len(selected)
        if total + amount > balance_service._MAX_MONEY:
            raise ValueError("批次金额超过系统上限")
        line = DomesticShipmentLine(
            shipment_id=batch.id, item_id=item.id, order_no=order.order_no,
            domestic_no=order.domestic_no, line_code=f"A{item.line_no}",
            guest_name=item.guest_name, product_name=item.product_name,
            quantity=len(selected), unit_price=price, amount=amount, ship_weight=row.ship_weight, attrs_snapshot=item.attrs_snapshot,
        )
        db.add(line)
        db.flush()
        db.add_all([DomesticShipmentUnit(line_id=line.id, unit_id=u.id) for u in selected])
        db.flush()
        total += amount
        item.ship_time = max(item.ship_time, payload.ship_time) if item.ship_time else payload.ship_time  # Latest actual delivery; history lives in batches.
        if row.ship_weight is not None:
            item.ship_weight = row.ship_weight
        if _shipped + len(selected) == item.order_qty:
            item.status = C.ITEM_SHIPPED
        else:
            progress_service.recalc_item_status(db, item)
    batch.total_amount = total
    for order in orders:
        progress_service.sync_order_status(db, order.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(DomesticShipment).filter_by(request_id=payload.request_id).first()
        if not existing or existing.created_by != user_id or existing.request_hash != fingerprint:
            raise ValueError("发货发生并发冲突，请刷新后核对")
        return {**shipment_view(db, existing), "replayed": True}
    return {**shipment_view(db, batch), "replayed": False}


def create_shipment(db, payload, user_id):
    for attempt in range(2):
        try:
            return _create_shipment_once(db, payload, user_id)
        except OperationalError as exc:
            # 1213 guarantees transaction rollback. Never retry an ambiguous commit/
            # connection failure: readback with the original request key is required.
            args = getattr(exc.orig, "args", ())
            if not args or args[0] != 1213:
                raise
            db.rollback()
            logging.getLogger(__name__).warning("Domestic shipment transaction deadlock; bounded retry")
            print("[DOMESTIC] shipment deadlock; transaction rolled back", flush=True)
            if attempt:
                raise ValueError("发货遇到并发冲突，请核对后使用同一请求号重试") from exc
        except IntegrityError as exc:
            db.rollback()
            existing = db.query(DomesticShipment).filter_by(request_id=payload.request_id).first()
            if existing and existing.created_by == user_id and existing.request_hash == payload_hash(payload):
                return {**shipment_view(db, existing), "replayed": True}
            raise ValueError("发货发生并发冲突，请刷新后核对") from exc


def paid_amount(db, shipment_id):
    value = db.query(func.sum(DomesticReceiptAllocation.amount)).filter(
        DomesticReceiptAllocation.shipment_id == shipment_id,
        DomesticReceiptAllocation.ledger_id.isnot(None),
    ).scalar()
    return balance_service.money(value)


def shipment_view(db, batch):
    lines = db.query(DomesticShipmentLine).filter_by(shipment_id=batch.id).order_by(DomesticShipmentLine.id).all()
    paid = paid_amount(db, batch.id)
    return {
        "id": batch.id, "shipment_no": batch.shipment_no, "customer_id": batch.customer_id,
        "ship_time": batch.ship_time, "received_date": batch.received_date,
        "total_amount": float(batch.total_amount), "paid_amount": float(paid),
        "unpaid_amount": 0.0 if batch.cancelled_at else float(balance_service.money(batch.total_amount) - paid),
        "cancelled_at": batch.cancelled_at, "cancelled_by": batch.cancelled_by,
        "remark": batch.remark, "created_by": batch.created_by,
        "items": [{
            "id": line.id, "item_id": line.item_id, "domestic_no": line.domestic_no,
            "order_no": line.order_no, "line_code": line.line_code, "guest_name": line.guest_name,
            "product_name": line.product_name, "attrs": line.attrs_snapshot, "quantity": line.quantity,
            "unit_price": float(line.unit_price), "amount": float(line.amount), "ship_weight": line.ship_weight,
            "unit_codes": [u["code"] for u in (batch.cancelled_units or {}).get(str(line.id), [])] if batch.cancelled_at else [unit_service.unit_display_code(db.get(DomesticOrderItem, line.item_id), u.unit_no)
                           for u in db.query(DomesticItemUnit).join(DomesticShipmentUnit, DomesticShipmentUnit.unit_id == DomesticItemUnit.id)
                           .filter(DomesticShipmentUnit.line_id == line.id).order_by(DomesticItemUnit.unit_no).all()],
        } for line in lines],
    }


def list_shipments(db, customer_id, user_id, can_read_all=False):
    q = db.query(DomesticShipment).filter_by(customer_id=customer_id)
    if not can_read_all:
        q = q.filter(DomesticShipment.created_by == user_id)
    return [shipment_view(db, row) for row in q.order_by(DomesticShipment.id.desc()).all()]


def confirm_received(db, shipment_id, payload, user_id):
    db.info["domestic_actor_id"] = user_id
    batch = db.query(DomesticShipment).filter_by(id=shipment_id).populate_existing().with_for_update().first()
    if not batch or batch.created_by != user_id:
        raise ValueError("发货批次不存在或不是本人创建")
    if batch.cancelled_at:
        raise ValueError("发货批次已取消，不能确认收货")
    if batch.received_date:
        if batch.received_date != payload.received_date:
            raise ValueError("该批次已确认收货，不能覆盖历史日期")
        return shipment_view(db, batch)
    if payload.received_date < batch.ship_time.date():
        raise ValueError("收货日期不能早于发货日期")
    batch.received_date = payload.received_date
    batch.received_by = user_id
    batch.received_at = beijing_now()
    db.commit()
    return shipment_view(db, batch)


def cancel_shipment(db, shipment_id, user_id):
    from app.domestic.shipment_cancel_service import cancel_shipment as cancel
    return cancel(db, shipment_id, user_id)


def customer_summary(db, customer_id, user_id=None):
    query = db.query(DomesticShipment).filter_by(customer_id=customer_id, cancelled_at=None)
    if user_id is not None:
        query = query.filter_by(created_by=user_id)
    batches = query.all()
    transit = sum((balance_service.money(b.total_amount) - paid_amount(db, b.id) for b in batches if not b.received_date), Decimal(0))
    due = sum((balance_service.money(b.total_amount) - paid_amount(db, b.id) for b in batches if b.received_date), Decimal(0))
    receipts_query = db.query(DomesticCustomerRequest).filter_by(customer_id=customer_id, request_type="receipt", status="approved")
    if user_id is not None:
        receipts_query = receipts_query.filter_by(created_by=user_id)
    receipts = receipts_query.all()
    unapplied = sum((balance_service.money(r.amount) - balance_service.money(
        db.query(func.sum(DomesticReceiptAllocation.amount)).filter_by(request_id=r.id).scalar()
    ) for r in receipts), Decimal(0))
    rows_query = db.query(DomesticOrderItem).join(DomesticOrder).filter(
        DomesticOrder.customer_id == customer_id, DomesticOrder.deleted_flag == 0,
        DomesticOrderItem.status != C.ITEM_TERMINATED,
        DomesticOrder.order_kind == "business", DomesticOrder.status.in_((C.ORDER_PRODUCING, C.ORDER_DONE, C.ORDER_SHIPPED)),
    )
    if user_id is not None:
        rows_query = rows_query.filter(DomesticOrder.created_by == user_id)
    rows = rows_query.all()
    unshipped = sum((balance_service.money(i.unit_price) * i.order_qty - shipped_item_amount(db, i) for i in rows), Decimal(0))
    legacy_count = sum(i.status == C.ITEM_SHIPPED and not shipped_unit_ids(db, i.id) for i in rows)
    return {"unshipped_amount": float(unshipped), "transit_unpaid_amount": float(transit),
            "received_unpaid_amount": float(due), "unallocated_receipts": float(unapplied),
            "legacy_shipped_items": legacy_count}
