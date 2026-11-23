"""Read-only invoice/outbound evidence for cross-border reconciliation."""
import logging
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_, tuple_
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.time import to_beijing_naive
from app.invoice.models import Invoice
from app.invoice.settlement_models import ShipmentOutbound
from app.invoice import detail_outbound_mirror, detail_outbounds
from app.invoice.presale_lines import remote_items, remote_quantity, remote_amount
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from app.shipping_inspection import outbound_sync_state, outbound_service
from app.tracking.models import ShipmentTracking, TrackingEvent
from app.tracking.carriers.dhl import DHL_PICKUP_CODES

logger = logging.getLogger(__name__)


def picked_up(events, waybill_no, carrier):
    return str(carrier).upper() == 'DHL' and any(
        e.waybill_no == waybill_no and str(e.carrier).upper() == 'DHL'
        and str(e.status_code or '').strip().upper() in DHL_PICKUP_CODES for e in events)


def in_scope(invoice, go_live):
    return bool(go_live and invoice.created_at and
        to_beijing_naive(invoice.created_at).date() >= go_live and
        invoice.express_channel == 'DHL9610' and
        '便捷发货' in (invoice.internal_payment_method or ''))


def invoice_view(invoice):
    product_amount = getattr(invoice, 'product_amount', None)
    return {'id': invoice.id, 'number': invoice.invoice_no,
            'salesperson': invoice.sales_user_name, 'sales_user_id': invoice.sales_user_id,
            'shop': (invoice.internal_payment_method or '').split('信保')[0],
            'total_amount': str(invoice.total_amount), 'currency': invoice.currency,
            'product_amount': product_amount,
            'fees': invoice.total_amount - product_amount if product_amount is not None else None,
            'cancelled': is_cancelled(invoice)}


def is_cancelled(invoice):
    return invoice.commerce_status == 'cancelled' or getattr(invoice, 'status', None) in {
        'cancel_pending', 'cancelled', 'remote_deleted', 'deleted'}


def calculate_part(invoice, quantities):
    """Compare each line, never aggregate different SKU quantities."""
    items = remote_items(invoice) if invoice.order_type == 'presale' else invoice.items
    expected = {i.id: Decimal(str(remote_quantity(i))) for i in items}
    if not expected or quantities is None or not set(quantities) <= set(expected):
        return {'kind': 'unknown', 'product_amount': None, 'quantities': quantities, 'expected': expected}
    values = {key: Decimal(str(value)) for key, value in quantities.items()}
    if any(not q.is_finite() or q < 0 or q != q.to_integral_value() or q > expected[k] for k, q in values.items()):
        return {'kind': 'unknown', 'product_amount': None, 'quantities': None, 'expected': expected}
    exact = all(values.get(key, Decimal(0)) == qty for key, qty in expected.items())
    if exact:
        amount = Decimal(str(invoice.total_amount))
    elif any(expected[i.id] <= 0 for i in items):
        return {'kind': 'unknown', 'product_amount': None, 'quantities': None, 'expected': expected}
    else:
        amount = sum((values.get(i.id, Decimal(0)) * remote_amount(i) / expected[i.id] for i in items), Decimal(0))
    return {'kind': 'exact' if exact else 'split', 'product_amount': amount,
            'quantities': values, 'expected': expected}


def _unavailable(invoice, exc):
    logger.warning('cross-border outbound mapping unavailable invoice=%s: %s', invoice.id, type(exc).__name__)
    print(f'[cross_border] outbound mapping unavailable invoice={invoice.id}: {type(exc).__name__}', flush=True)


def build_tickets(db, *, order_nos=None):
    """Batch local evidence; reuse exact mirror mapping for legacy invoices."""
    go_live = get_settings().CROSS_BORDER_GO_LIVE_DATE
    if go_live is None:
        return {}, {}
    query = db.query(Invoice).options(selectinload(Invoice.items)).filter(
        Invoice.express_channel == 'DHL9610', Invoice.internal_payment_method.contains('便捷发货'),
        Invoice.created_at >= datetime.combine(go_live, datetime.min.time()), Invoice.alibaba_order_no.isnot(None))
    if order_nos is not None:
        query = query.filter(Invoice.alibaba_order_no.in_(order_nos))
    invoices = query.all()
    by_order = defaultdict(list)
    for invoice in invoices:
        by_order[invoice.alibaba_order_no].append(invoice_view(invoice))
    ids = [i.id for i in invoices]
    locals_ = db.query(ShipmentOutbound).filter(ShipmentOutbound.invoice_id.in_(ids),
        ShipmentOutbound.payload['transaction_mode'].as_string() == 'local',
        ShipmentOutbound.status != 'local_cancelled').all() if ids else []
    by_invoice = defaultdict(list)
    for out in locals_:
        by_invoice[out.invoice_id].append(out)
    documents = {}
    for invoice in invoices:
        if invoice.transaction_mode == 'local' or not invoice.xiaoman_order_id:
            continue
        try:
            documents[invoice.id] = detail_outbound_mirror.read(db, invoice, None)
        except ValueError as exc:
            _unavailable(invoice, exc)
            documents[invoice.id] = []
    record_ids = [d['record_id'] for docs in documents.values() for d in docs]
    inspections = db.query(ShippingInspection).filter(or_(
        ShippingInspection.local_outbound_id.in_([o.id for o in locals_]),
        ShippingInspection.outbound_record_id.in_(record_ids))).all() if locals_ or record_ids else []
    by_local = {i.local_outbound_id: i for i in inspections if i.local_outbound_id}
    by_record = {i.outbound_record_id: i for i in inspections if not i.local_outbound_id}
    sync_events = {e.request_id: e for e in db.query(ShippingOperationEvent).filter(
        ShippingOperationEvent.scope == outbound_sync_state.SCOPE,
        ShippingOperationEvent.request_id.in_(record_ids)).all()} if record_ids else {}
    bound, exported = {}, {}
    events = db.query(ShippingOperationEvent).filter(ShippingOperationEvent.inspection_id.in_([i.id for i in inspections]),
        ShippingOperationEvent.action.in_(['shipment_bound', 'shipment_exported'])).order_by(ShippingOperationEvent.id).all() if inspections else []
    for event in events:
        if event.action == 'shipment_bound':
            bound[event.inspection_id] = event
        else:
            exported[event.inspection_id] = (event.payload or {}).get('shipment_tracking_id')
    quantities, linked, unknown = {}, defaultdict(list), set()
    for invoice in invoices:
        for out in by_invoice[invoice.id]:
            inspection = by_local.get(out.id)
            if not inspection or not inspection.shipment_tracking_id:
                continue
            key = (invoice.id, inspection.shipment_tracking_id)
            linked[key].append(inspection)
            try:
                if inspection.status != 'submitted' or out.status != 'local_shipped' or inspection.local_outbound_version != out.payload.get('outbound_version'):
                    raise ValueError('Unverified local outbound')
                q = quantities.setdefault(key, defaultdict(Decimal))
                seen = set()
                for line in out.payload['items']:
                    item_id = int(line['invoice_item_id'])
                    if item_id in seen:
                        raise ValueError('Duplicate outbound item')
                    seen.add(item_id)
                    q[item_id] += Decimal(str(line['qty']))
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                _unavailable(invoice, exc)
                unknown.add(key)
        docs = documents.get(invoice.id, [])
        for doc in docs:
            inspection = by_record.get(doc['record_id'])
            if not inspection or not inspection.shipment_tracking_id:
                continue
            key = (invoice.id, inspection.shipment_tracking_id)
            linked[key].append(inspection)
            try:
                doc = dict(doc, inspection={'state': 'ready', 'status': inspection.status})
                doc.update(detail_outbounds.inspection_integrity(db, doc, sync_events.get(doc['record_id'])))
                if inspection.status != 'submitted':
                    raise ValueError('Inspection not submitted')
                if doc.get('inspection_blocked'):
                    raise ValueError('Outbound synchronization unverified')
                projected, _ = detail_outbounds.project(invoice, [doc])
                q = quantities.setdefault(key, defaultdict(Decimal))
                for line in projected[0]['items']:
                    q[line['invoice_item_id']] += Decimal(line['quantity'])
            except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
                _unavailable(invoice, exc)
                unknown.add(key)
    tracking_ids = {key[1] for key in linked}
    trackings = {t.id: t for t in db.query(ShipmentTracking).filter(ShipmentTracking.id.in_(tracking_ids),
        ShipmentTracking.deleted_at.is_(None)).all()} if tracking_ids else {}
    pairs = [(t.waybill_no, t.carrier) for t in trackings.values()]
    tracking_events = db.query(TrackingEvent).filter(tuple_(TrackingEvent.waybill_no, TrackingEvent.carrier).in_(pairs)).all() if pairs else []
    tickets, invoice_map = {}, {i.id: i for i in invoices}
    mixed_ids = set()
    if tracking_ids:
        shared = db.query(ShippingInspection.shipment_tracking_id, Invoice).join(
            ShipmentOutbound, ShipmentOutbound.id == ShippingInspection.local_outbound_id).join(
            Invoice, Invoice.id == ShipmentOutbound.invoice_id).filter(
            ShippingInspection.shipment_tracking_id.in_(tracking_ids)).all()
        mixed_ids = {tracking_id for tracking_id, invoice in shared if not in_scope(invoice, go_live)}
        # A shared legacy outbound may contain orders excluded from this screen.
        legacy_inspections = db.query(ShippingInspection).filter(
            ShippingInspection.shipment_tracking_id.in_(tracking_ids),
            ShippingInspection.local_outbound_id.is_(None)).all()
        if legacy_inspections:
            try:
                associations = outbound_service.order_ids_for_records(db, [i.outbound_record_id for i in legacy_inspections])
                remote_ids = {identity for group in associations.values() for identity in group}
                related = {i.xiaoman_order_id: i for i in db.query(Invoice).filter(Invoice.xiaoman_order_id.in_(remote_ids)).all()} if remote_ids else {}
                for inspection in legacy_inspections:
                    if any(identity not in related or not in_scope(related[identity], go_live)
                           for identity in associations.get(inspection.outbound_record_id, [])):
                        mixed_ids.add(inspection.shipment_tracking_id)
            except ValueError as exc:
                logger.warning('cross-border shared outbound inspection unavailable: %s', type(exc).__name__)
                print(f'[cross_border] shared outbound inspection unavailable: {type(exc).__name__}', flush=True)
    for (invoice_id, tracking_id), associated in linked.items():
        tracking = trackings.get(tracking_id)
        if tracking is None:
            continue
        invoice = invoice_map[invoice_id]
        if invoice.currency != 'USD' or is_cancelled(invoice):
            continue
        ticket = tickets.setdefault((invoice.alibaba_order_no, tracking_id), {
            'shipment_tracking_id': tracking_id, 'waybill_no': tracking.waybill_no,
            'carrier': tracking.carrier, 'logistics_status': tracking.unified_status or tracking.current_status,
            'bound_at': None, 'inspection_ids': [], 'invoices': [], 'parts': [],
            'mixed_waybill': tracking_id in mixed_ids,
            'exported_rebind': False,
            'picked_up': picked_up(tracking_events, tracking.waybill_no, tracking.carrier)})
        for inspection in associated:
            ticket['inspection_ids'].append(inspection.id)
            event = bound.get(inspection.id)
            if inspection.id in exported and str(exported[inspection.id]) != str(tracking_id):
                ticket['exported_rebind'] = True
            if event and str((event.payload or {}).get('shipment_tracking_id')) == str(tracking_id):
                when = to_beijing_naive(event.created_at)
                ticket['bound_at'] = max(ticket['bound_at'], when) if ticket['bound_at'] else when
        part = calculate_part(invoice, None if (invoice_id, tracking_id) in unknown else quantities.get((invoice_id, tracking_id)))
        ticket['parts'].append(dict(part, invoice_id=invoice.id, total_amount=Decimal(str(invoice.total_amount))))
        ticket['invoices'].append(invoice_view(invoice))
    # Aggregate overflow can be hidden when each individual ticket looks valid.
    all_quantities = defaultdict(Decimal)
    for ticket in tickets.values():
        for part in ticket['parts']:
            for item_id, quantity in (part['quantities'] or {}).items():
                all_quantities[(part['invoice_id'], item_id)] += quantity
    invalid_ids = {part['invoice_id'] for ticket in tickets.values() for part in ticket['parts']
                   if any(all_quantities[(part['invoice_id'], item_id)] > qty for item_id, qty in part['expected'].items())}
    for ticket in tickets.values():
        for part in ticket['parts']:
            if part['invoice_id'] in invalid_ids:
                part.update(kind='unknown', product_amount=None, quantities=None)
    result = defaultdict(list)
    for (order_no, _), ticket in tickets.items():
        kinds = {p['kind'] for p in ticket['parts']}
        ticket['kind'] = 'unknown' if 'unknown' in kinds else 'split' if 'split' in kinds else 'exact'
        amount = sum((p['product_amount'] for p in ticket['parts']), Decimal(0)) if 'unknown' not in kinds else None
        ticket['amount'] = amount if ticket['kind'] == 'exact' else None
        ticket['product_floor'] = amount if ticket['kind'] == 'split' else None
        result[order_no].append(ticket)
    for group in result.values():
        group.sort(key=lambda t: (t['bound_at'] or datetime.max, t['shipment_tracking_id']))
    return dict(result), dict(by_order)
