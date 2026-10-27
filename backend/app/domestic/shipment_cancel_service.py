"""Cancel unreceived, unallocated deliveries without changing order accounting."""
from app.core.time import beijing_now
from app.domestic import constants as C, progress_service, unit_service
from app.domestic.models import DomesticCustomer, DomesticOrder, DomesticOrderItem, DomesticItemUnit
from app.domestic.shipment_models import DomesticShipment, DomesticShipmentLine, DomesticShipmentUnit, DomesticReceiptAllocation


def cancel_shipment(db, shipment_id, user_id):
    from app.domestic.shipment_service import shipment_view
    db.info['domestic_actor_id'] = user_id
    # Match order writers, then serialize with receipt writers on their customer lock.
    # order -> item -> customer -> batch -> allocation avoids approval's allocation/batch inversion.
    # Lines are immutable, including after cancellation, so previews only select locks.
    ids = db.query(DomesticShipmentLine.item_id).filter_by(shipment_id=shipment_id).all()
    item_ids = sorted(value for (value,) in ids)
    order_ids = sorted({value for (value,) in db.query(DomesticOrderItem.order_id).filter(DomesticOrderItem.id.in_(item_ids)).all()})
    orders = db.query(DomesticOrder).filter(DomesticOrder.id.in_(order_ids)).order_by(DomesticOrder.id).populate_existing().with_for_update().all()
    items = db.query(DomesticOrderItem).filter(DomesticOrderItem.id.in_(item_ids)).order_by(DomesticOrderItem.id).populate_existing().with_for_update().all()
    customer_id = db.query(DomesticShipment.customer_id).filter_by(id=shipment_id).scalar()
    if customer_id is not None:
        db.query(DomesticCustomer).filter_by(id=customer_id).populate_existing().with_for_update().one()
    batch = db.query(DomesticShipment).filter_by(id=shipment_id).populate_existing().with_for_update().first()
    if not batch or batch.created_by != user_id:
        raise ValueError('发货批次不存在或不是本人创建')
    if batch.cancelled_at:
        db.commit()
        return shipment_view(db, batch)
    if batch.received_date:
        raise ValueError('该批次已确认收货，不能取消')
    if db.query(DomesticReceiptAllocation.id).filter_by(shipment_id=batch.id).with_for_update().first():
        raise ValueError('该批次已关联收款核销记录，不能取消')
    if any(o.deleted_flag or o.status not in (C.ORDER_PRODUCING, C.ORDER_DONE, C.ORDER_SHIPPED) for o in orders) or any(i.status == C.ITEM_TERMINATED for i in items):
        raise ValueError('相关订单或明细已终止或失效，不能取消批次')
    by_item = {item.id: item for item in items}
    lines = db.query(DomesticShipmentLine).filter_by(shipment_id=batch.id).order_by(DomesticShipmentLine.id).with_for_update().all()
    snapshot = {}
    for line in lines:
        units = db.query(DomesticItemUnit).join(DomesticShipmentUnit, DomesticShipmentUnit.unit_id == DomesticItemUnit.id).filter(DomesticShipmentUnit.line_id == line.id).order_by(DomesticItemUnit.unit_no).with_for_update().all()
        snapshot[str(line.id)] = [{'id': u.id, 'code': unit_service.unit_display_code(by_item[line.item_id], u.unit_no)} for u in units]
        db.query(DomesticShipmentUnit).filter_by(line_id=line.id).delete(synchronize_session=False)
    batch.cancelled_units = snapshot
    batch.cancelled_at = beijing_now()
    batch.cancelled_by = user_id
    db.flush()
    for item in items:
        remaining = db.query(DomesticShipmentLine, DomesticShipment.ship_time).join(DomesticShipment).filter(DomesticShipmentLine.item_id == item.id, DomesticShipment.cancelled_at.is_(None)).order_by(DomesticShipment.id.desc()).with_for_update().all()
        item.ship_time = max((time for _line, time in remaining), default=None)
        item.ship_weight = next((line.ship_weight for line, _time in remaining if line.ship_weight is not None), None)
        if item.status == C.ITEM_SHIPPED:
            item.status = C.ITEM_PRODUCING
        progress_service.recalc_item_status(db, item)
    for order in orders:
        progress_service.sync_order_status(db, order.id)
    # No refund: the order is still effective and its units may be shipped again.
    db.commit()
    return shipment_view(db, batch)
