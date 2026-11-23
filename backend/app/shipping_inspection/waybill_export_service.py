"""Read immutable export membership when replacing a declared shipment."""
from app.cross_border.models import Declaration, ExportBatch
from app.shipping_inspection.models import ShippingOperationEvent


def export_baseline(db, inspection_id):
    row = db.query(ShippingOperationEvent).filter(
        ShippingOperationEvent.inspection_id == inspection_id, ShippingOperationEvent.action == 'shipment_exported'
    ).order_by(ShippingOperationEvent.id.desc()).with_for_update().first()
    return (row.payload or {}).get('shipment_tracking_id') if row else None


def exported_ids(db, inspections):
    current = {i.id: i.shipment_tracking_id for i in inspections if i.shipment_tracking_id}
    if not current:
        return set()
    rows = db.query(ShippingOperationEvent).filter(ShippingOperationEvent.inspection_id.in_(current),
        ShippingOperationEvent.action == 'shipment_exported').all()
    return {row.inspection_id for row in rows}


def legacy_export_unverified(db, inspection, invoices):
    order_nos = {i.alibaba_order_no for i in invoices if i.alibaba_order_no}
    if not order_nos:
        return False
    hashes = {r[0] for r in db.query(Declaration.content_hash).filter(Declaration.order_no.in_(order_nos)).all()}
    if not hashes:
        return False
    batches = {row.id for row in db.query(ExportBatch.id, ExportBatch.content_hashes).all()
               if hashes.intersection(row.content_hashes or [])}
    if not batches:
        return False
    recorded = {row[0] for row in db.query(ShippingOperationEvent.payload['export_id'].as_integer()).filter(
        ShippingOperationEvent.action == 'shipment_exported',
        ShippingOperationEvent.payload['export_id'].as_integer().in_(batches)).distinct().all()}
    return bool(batches - recorded)
