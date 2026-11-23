"""Both outbound routes exercised on the shared in-memory SQLite fixture."""
from datetime import date, datetime
from decimal import Decimal

from app.core.config import get_settings
from app.cross_border.ticket_service import build_tickets
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentOutbound
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from app.tracking.models import ShipmentTracking, TrackingEvent


def make_invoice(db, identity=1, **kwargs):
    values = dict(id=identity, invoice_no=f'CB{identity}', transaction_mode='local',
        customer_id='1', customer_name='Test', invoice_date=date(2026, 11, 23), currency='USD',
        express_channel='DHL9610', internal_payment_method='新莱莎信保（便捷发货）',
        alibaba_order_no='123456789012345', total_amount=Decimal('110'),
        created_at=datetime(2026, 11, 23), commerce_status='confirmed')
    values.update(kwargs)
    invoice = Invoice(**values)
    invoice.items = [InvoiceItem(id=identity, product_name='Test product', product_display='Test',
        color='Black', quantity=10, total_price=Decimal('100'), product_id=identity,
        sku_id=identity, xiaoman_unique_id=str(identity))]
    db.add(invoice)
    db.flush()
    return invoice


def tracking(db, identity=1):
    row = ShipmentTracking(id=identity, waybill_no=f'WB{identity}', carrier='DHL', carrier_name='DHL',
        dingtalk_user_id='test', dingtalk_user_name='Test', current_status='PU')
    db.add(row)
    db.add(TrackingEvent(waybill_no=row.waybill_no, carrier='DHL', event_time=datetime(2026, 11, 23),
                         status_code='pu', description='Picked up'))
    db.flush()
    return row


def inspection(db, identity, tracking_id=1, **kwargs):
    row = ShippingInspection(id=identity, outbound_record_id=str(identity), status='submitted',
        shipment_tracking_id=tracking_id, **kwargs)
    db.add(row)
    db.flush()
    db.add(ShippingOperationEvent(scope='test', request_id=str(identity), source='pc', action='shipment_bound',
        login_user_id=1, operator_user_id=1, operator_name='Test', login_name='Test',
        outbound_record_id=row.outbound_record_id, inspection_id=row.id,
        payload={'shipment_tracking_id': tracking_id}, created_at=datetime(2026, 11, 23, 8, identity)))
    db.flush()
    return row


def outbound(db, invoice, identity, qty=10, tracking_id=1):
    row = ShipmentOutbound(id=identity, settlement_id=identity, invoice_id=invoice.id, outbound_no=f'OUT{identity}',
        status='local_shipped', payload={'transaction_mode': 'local', 'outbound_version': 1,
            'items': [{'invoice_item_id': invoice.items[0].id, 'qty': qty}]}, payload_hash=f'h{identity}')
    db.add(row)
    db.flush()
    inspection(db, identity, tracking_id, local_outbound_id=identity, local_outbound_version=1)
    return row


def test_local_chain_groups_invoices_and_partial_quantities(db, monkeypatch):
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    a, b = make_invoice(db), make_invoice(db, 2)
    tracking(db)
    outbound(db, a, 1, 6)
    outbound(db, b, 2)
    tickets, invoices = build_tickets(db)
    group = tickets[a.alibaba_order_no]
    assert len(group) == 1 and len(group[0]['invoices']) == 2
    assert group[0]['kind'] == 'split' and group[0]['product_floor'] == Decimal('170')
    assert group[0]['picked_up']
    assert group[0]['inspection_ids'] == [1, 2]
    assert group[0]['bound_at'] == datetime(2026, 11, 23, 8, 2)
    assert len(invoices[a.alibaba_order_no]) == 2


def test_local_scope_boundary_cancelled_currency_and_mixed_waybill(db, monkeypatch):
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    eligible = make_invoice(db)
    old = make_invoice(db, 2, created_at=datetime(2026, 11, 22, 23, 59))
    fedex = make_invoice(db, 3, express_channel='FEDEX9610')
    cancelled = make_invoice(db, 4, commerce_status='cancelled')
    eur = make_invoice(db, 5, currency='EUR')
    tracking(db)
    for i, inv in enumerate([eligible, old, fedex, cancelled, eur], 1):
        outbound(db, inv, i)
    tickets, invoices = build_tickets(db)
    ticket = tickets[eligible.alibaba_order_no][0]
    assert ticket['kind'] == 'exact' and ticket['amount'] == Decimal('110')
    assert [i['id'] for i in ticket['invoices']] == [1]
    assert ticket['mixed_waybill']
    assert {i['id'] for i in invoices[eligible.alibaba_order_no]} == {1, 4, 5}
    assert build_tickets(db, order_nos=['000000000000000']) == ({}, {})


def test_okki_exact_mapping_filters_other_order_on_same_outbound(db, monkeypatch):
    from app.invoice import detail_outbound_mirror
    from app.shipping_inspection import outbound_service
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    inv = make_invoice(db, transaction_mode='legacy', xiaoman_order_id='ORD1')
    tracking(db)
    inspection(db, 1)
    # The real projection must ignore a different order even if SKU matches.
    doc = {'record_id': '1', 'outbound_invoice_id': 'OUT1', 'serial_id': 'OUT1', 'record_list': [
        {'order_id': 'ORD1', 'order_record_id': '1', 'product_id': 1, 'sku_id': 1, 'outbound_count': '10'},
        {'order_id': 'OTHER', 'order_record_id': '1', 'product_id': 1, 'sku_id': 1, 'outbound_count': '99'}]}
    monkeypatch.setattr(detail_outbound_mirror, 'read', lambda *_: [doc])
    monkeypatch.setattr(outbound_service, 'order_ids_for_records', lambda *_: {'1': ['ORD1', 'OTHER']})
    tickets, _ = build_tickets(db)
    assert tickets[inv.alibaba_order_no][0]['amount'] == Decimal('110')
    assert tickets[inv.alibaba_order_no][0]['kind'] == 'exact'
    assert tickets[inv.alibaba_order_no][0]['mixed_waybill']
    doc['record_list'][0]['order_record_id'] = 'BAD'
    tickets, _ = build_tickets(db)
    assert tickets[inv.alibaba_order_no][0]['kind'] == 'unknown'


def test_rebound_audit_and_stale_local_quantities_fail_closed(db, monkeypatch):
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    inv = make_invoice(db)
    tracking(db, 1)
    tracking(db, 2)
    outbound(db, inv, 1)
    row = db.get(ShippingInspection, 1)
    row.shipment_tracking_id = 2
    row.local_outbound_version = 0
    db.flush()
    tickets, _ = build_tickets(db)
    ticket = tickets[inv.alibaba_order_no][0]
    assert ticket['shipment_tracking_id'] == 2 and ticket['bound_at'] is None
    assert ticket['kind'] == 'unknown'


def test_aggregate_overdelivery_is_unknown_not_incomplete(db, monkeypatch):
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    inv = make_invoice(db)
    tracking(db, 1)
    tracking(db, 2)
    outbound(db, inv, 1, 6, 1)
    outbound(db, inv, 2, 6, 2)
    tickets, _ = build_tickets(db)
    assert all(t['kind'] == 'unknown' for t in tickets[inv.alibaba_order_no])


def test_classic_cancelled_invoice_cannot_form_exportable_ticket(db, monkeypatch):
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    inv = make_invoice(db, status='cancelled', commerce_status='draft')
    tracking(db)
    outbound(db, inv, 1)
    tickets, invoices = build_tickets(db)
    assert tickets == {}
    assert invoices[inv.alibaba_order_no][0]['cancelled']
    inv.status = 'cancel_pending'
    db.flush()
    assert build_tickets(db)[0] == {}


def test_shared_tracking_finds_other_legacy_inspection_outside_scope(db, monkeypatch):
    from app.shipping_inspection import outbound_service
    monkeypatch.setattr(get_settings(), 'CROSS_BORDER_GO_LIVE_DATE', date(2026, 11, 23))
    inv = make_invoice(db)
    make_invoice(db, 2, transaction_mode='legacy', xiaoman_order_id='OTHER', express_channel='DHL')
    tracking(db)
    outbound(db, inv, 1)
    inspection(db, 2)
    monkeypatch.setattr(outbound_service, 'order_ids_for_records', lambda _, ids: {'2': ['OTHER']} if '2' in ids else {})
    tickets, _ = build_tickets(db)
    assert tickets[inv.alibaba_order_no][0]['mixed_waybill']
