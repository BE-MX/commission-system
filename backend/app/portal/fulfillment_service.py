"""Customer-safe order processing and exact inspection/shipment projections."""
import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.invoice.models import Invoice

logger = logging.getLogger(__name__)
PROCESSING = {
    'draft': 'PI prepared', 'ready': 'Awaiting order processing', 'synced': 'Order confirmed',
    'sync_failed': 'Order processing needs review', 'sync_uncertain': 'Order processing needs review',
    'cancel_pending': 'Cancellation in progress', 'cancelled': 'Cancelled',
}
BUSINESS_STATES = {
    '待确认': 'Awaiting confirmation', '待收款': 'Awaiting payment', '待付款': 'Awaiting payment',
    '生产中': 'In production', '待生产': 'Awaiting production', '待发货': 'Awaiting dispatch',
    '已发货': 'Shipped', '已完成': 'Completed', '已取消': 'Cancelled',
}
SHIPMENT_STATES = {
    'pending': 'Awaiting carrier update', 'picked_up': 'Picked up', 'in_transit': 'In transit',
    'customs': 'Customs clearance', 'customs_hold': 'Customs clearance',
    'out_for_delivery': 'Out for delivery', 'delivered': 'Delivered',
    'exception': 'Delivery exception', 'returned': 'Returned',
}


def shipment_view(db, shipment):
    from app.tracking.models import TrackingEvent
    events = db.scalars(select(TrackingEvent).where(TrackingEvent.waybill_no == shipment.waybill_no,
        TrackingEvent.carrier == shipment.carrier).order_by(TrackingEvent.event_time.desc(), TrackingEvent.id.desc()).limit(100)).all()
    return {'waybill_no': shipment.waybill_no, 'carrier': shipment.carrier,
        'status': SHIPMENT_STATES.get(shipment.unified_status or shipment.current_status, 'Awaiting carrier update'),
        'estimated_delivery_at': shipment.estimated_delivery_date.isoformat() if shipment.estimated_delivery_date else None,
        'events': [{'at': row.event_time.isoformat(), 'description': row.description,
                    'location': row.location} for row in events]}


def view(db, order, *, details=False):
    if order.status != 'invoice_created' or not order.invoice_id:
        return {}
    invoice = db.scalar(select(Invoice).where(Invoice.id == order.invoice_id,
        Invoice.source_type == 'portal', Invoice.source_order_id == order.public_id,
        Invoice.customer_id == order.okki_company_id_snapshot))
    if invoice is None:
        return {'processing_status': 'Processing details need review'}
    result = {'processing_status': PROCESSING.get(invoice.status, 'Processing details need review')}
    if invoice.sync_status in {'sync_failed', 'sync_uncertain'}:
        result['processing_status'] = 'Order processing needs review'
    if invoice.status in {'cancelled', 'cancel_pending'} or not invoice.xiaoman_order_id:
        return result
    from app.models.business import OkkiOrder
    from app.invoice.detail_outbound_mirror import read
    from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
    from app.shipping_inspection.outbound_sync_state import SCOPE
    from app.invoice.detail_outbounds import inspection_integrity
    from app.tracking.models import ShipmentTracking
    try:
        # A missing/unavailable mirror must not poison the surrounding read transaction.
        with db.begin_nested():
            remote = db.scalar(select(OkkiOrder).where(OkkiOrder.order_id == str(invoice.xiaoman_order_id),
                OkkiOrder.company_id == str(invoice.customer_id)))
            if remote and remote.status_name in BUSINESS_STATES:
                result['processing_status'] = BUSINESS_STATES[remote.status_name]
            outbounds = read(db, invoice, None)
            if not outbounds:
                return result
            result['dispatch_recorded'] = True
            if not remote or remote.status_name not in BUSINESS_STATES:
                result['processing_status'] = 'Dispatch recorded'
            sync_events = {row.request_id: row for row in db.scalars(select(ShippingOperationEvent).where(
                ShippingOperationEvent.scope == SCOPE,
                ShippingOperationEvent.request_id.in_([str(doc['record_id']) for doc in outbounds]))).all()}
            verified_outbounds = [doc for doc in outbounds if not any(inspection_integrity(
                db, doc, sync_events.get(str(doc['record_id']))).values())]
            inspections = db.scalars(select(ShippingInspection).where(
                ShippingInspection.outbound_record_id.in_([str(row['record_id']) for row in verified_outbounds]),
                ShippingInspection.status == 'submitted', ShippingInspection.shipment_tracking_id.is_not(None))).all()
            shipment_ids = {row.shipment_tracking_id for row in inspections}
            # 员工在验货单上显式关联即为确认；PC 录入的运单没有图片，不能再以 source_image_url 过滤
            shipments = db.scalars(select(ShipmentTracking).where(ShipmentTracking.id.in_(shipment_ids),
                ShipmentTracking.deleted_at.is_(None)).order_by(ShipmentTracking.id)).all() if shipment_ids else []
            if details:
                result['shipments'] = [shipment_view(db, row) for row in shipments]
    except (ValueError, SQLAlchemyError) as exc:
        logger.warning('Portal fulfillment evidence unavailable for request %s: %s', order.public_id, type(exc).__name__)
        print('Portal fulfillment evidence unavailable; processing details need review', flush=True)
        result['processing_status'] = 'Processing details need review'
        result.pop('shipments', None)
    return result
