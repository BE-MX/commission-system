"""Mobile pending/done queue with shared visibility and batched card enrichment."""
from datetime import datetime, timedelta

from sqlalchemy import func, or_

from app.core.time import beijing_today
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from app.shipping_inspection import outbound_service, service, waybill_scope_service as scope
from app.tracking.models import ShipmentTracking


def queue(db, user_id, roles, permissions, *, tab='pending', keyword=None, include_older=False, page=1, page_size=50):
    today = datetime.combine(beijing_today(), datetime.min.time())
    query = db.query(ShippingInspection).filter(ShippingInspection.status == 'submitted')
    bound = {}
    if tab == 'pending':
        query = query.outerjoin(ShipmentTracking, ShipmentTracking.id == ShippingInspection.shipment_tracking_id).filter(
            or_(ShipmentTracking.id.is_(None), ShipmentTracking.deleted_at.isnot(None)))
        if not include_older and not keyword:
            query = query.filter(ShippingInspection.submitted_at >= today - timedelta(days=13))
    else:
        query = query.join(ShipmentTracking, ShipmentTracking.id == ShippingInspection.shipment_tracking_id).filter(
            ShipmentTracking.deleted_at.is_(None))
        # Latest current association only; an earlier actor must not see another actor's replacement as theirs.
        latest = db.query(ShippingOperationEvent.inspection_id.label('inspection_id'),
            func.max(ShippingOperationEvent.id).label('id')).filter(
                ShippingOperationEvent.action == 'shipment_bound').group_by(ShippingOperationEvent.inspection_id).subquery()
        events = db.query(ShippingOperationEvent).join(latest, latest.c.id == ShippingOperationEvent.id).filter(
            ShippingOperationEvent.operator_user_id == user_id, ShippingOperationEvent.created_at >= today,
            ShippingOperationEvent.created_at < today + timedelta(days=1)).all()
        bound = {e.inspection_id: e for e in events}
        query = query.filter(ShippingInspection.id.in_(bound))
    if keyword:
        query = query.filter(or_(ShippingInspection.outbound_no.contains(keyword, autoescape=True),
                                ShippingInspection.customer_name.contains(keyword, autoescape=True)))
    rows = query.order_by(ShippingInspection.submitted_at.desc(), ShippingInspection.id.desc()).all()
    invoices = scope.invoice_map(db, rows)
    visible = scope.visible_ids(db, rows, user_id, roles, permissions, invoices)
    rows = [row for row in rows if row.id in visible and (tab != 'pending' or not invoices[row.id] or
            not all(inv.express_channel in {'自提', '货代/海运'} for inv in invoices[row.id]))]
    if tab == 'done':
        rows = [row for row in rows if row.shipment_tracking_id and
                str((bound[row.id].payload or {}).get('shipment_tracking_id')) == str(row.shipment_tracking_id)]
        rows.sort(key=lambda row: bound[row.id].created_at, reverse=True)
    total = len(rows)
    rows = rows[(page - 1) * page_size:page * page_size]
    legacy = [str(row.outbound_record_id) for row in rows if not row.local_outbound_id]
    records, _ = outbound_service.list_outbound_records(db, record_ids=legacy, page_size=max(len(legacy), 1),
                                                       count_total=False) if legacy else ([], 0)
    records = {str(row['outbound_record_id']): row for row in records}
    from app.shipping_inspection import local_outbound_service
    for row in rows:
        if row.local_outbound_id:
            record = local_outbound_service.header(db, row.outbound_record_id, include_deleted=True)
            if record:
                records[str(row.outbound_record_id)] = record
    countries = scope.countries(db, [str(r.get('company_id') or '') for r in records.values()])
    from app.customer.models import CustomerAccount
    local_customer_ids = [int(r['company_id'][4:]) for r in records.values() if str(r.get('company_id', '')).startswith('ark:')]
    if local_customer_ids:
        countries.update({f'ark:{c.id}': c.primary_country_code or '' for c in db.query(CustomerAccount).filter(CustomerAccount.id.in_(local_customer_ids)).all()})
    from app.shipping_inspection.waybill_photo_service import current_photos
    photos = current_photos(db, [row.id for row in rows])
    from app.shipping_inspection.waybill_export_service import exported_ids
    exported = exported_ids(db, rows)
    shipments = service._shipment_briefs(db, rows)
    items = []
    for row in rows:
        associated = invoices[row.id]
        cross = [inv for inv in associated if scope.is_9610(inv)]
        record = records.get(str(row.outbound_record_id), {})
        items.append(dict(id=row.id, outbound_no=row.outbound_no, customer_name=row.customer_name,
            recipient_country=countries.get(str(record.get('company_id')), ''),
            recipient_name=next((inv.contact_name for inv in associated if inv.contact_name), row.customer_name or ''),
            submitted_at=row.submitted_at, quantity=record.get('total_qty', 0),
            edit_version=row.edit_version, shipment_version=row.shipment_version, shipment=shipments.get(row.id),
            cross_border={'is_9610': bool(cross), 'has_exported': row.id in exported, 'invoices': [dict(invoice_id=inv.id, invoice_no=inv.invoice_no,
                alibaba_order_no=inv.alibaba_order_no) for inv in cross]},
            photo=photos.get(row.id), bound_at=bound[row.id].created_at if row.id in bound else None,
            ship_date=beijing_today().isoformat()))
    return dict(items=items, total=total, has_more=page * page_size < total)
