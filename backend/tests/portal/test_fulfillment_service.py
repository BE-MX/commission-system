from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.invoice.models import Invoice
from app.core.time import beijing_today
from app.portal.fulfillment_service import view, shipment_view
from app.portal.models import OrderRequest
from app.shipping_inspection import service as inspection_service


@pytest.fixture
def source_invoice():
    engine = create_engine('sqlite:///:memory:')
    Invoice.__table__.create(engine)
    with Session(engine) as db:
        db.execute(Invoice.__table__.insert().values(id=1, invoice_no='TEST', customer_id='1',
            customer_name='Customer', invoice_date=beijing_today(), order_type='stock', currency='USD',
            status='draft', source_type='portal', source_order_id='request'))
        db.commit()
        order = SimpleNamespace(invoice_id=1, status='invoice_created', public_id='request', okki_company_id_snapshot='1')
        yield db, order
    engine.dispose()


def test_unsent_invoice_processing_matches_ark(source_invoice):
    db, order = source_invoice
    assert view(db, order) == {'processing_status': 'PI prepared'}


def test_missing_mirror_is_pending_and_does_not_poison_transaction(source_invoice):
    db, order = source_invoice
    db.execute(Invoice.__table__.update().values(xiaoman_order_id='remote-order'))
    db.commit()
    assert view(db, order, details=True) == {'processing_status': 'Processing details need review'}
    assert db.scalar(select(Invoice.id)) == 1


def test_wrong_customer_invoice_never_projects_fulfillment(source_invoice):
    db, order = source_invoice
    order.okki_company_id_snapshot = 'unrelated'
    assert view(db, order, details=True) == {'processing_status': 'Processing details need review'}


def test_customer_shipment_uses_allowlist_and_exact_waybill_carrier():
    db = Mock()
    db.scalars.return_value.all.return_value = [SimpleNamespace(event_time=__import__('datetime').datetime(2026, 10, 28, 12), description='Departed', location='Paris', raw_response='private')]
    shipment = SimpleNamespace(waybill_no='ABC', carrier='DHL', unified_status='in_transit', current_status='raw', estimated_delivery_date=None, dingtalk_user_name='private', source_image_url='private')
    result = shipment_view(db, shipment)
    assert set(result) == {'waybill_no', 'carrier', 'status', 'estimated_delivery_at', 'events'}
    assert result['status'] == 'In transit' and 'private' not in str(result)
    statement = str(db.scalars.call_args.args[0])
    assert 'tracking_events.waybill_no =' in statement and 'tracking_events.carrier =' in statement


@pytest.mark.parametrize('status,version', [('draft', 3), ('submitted', 2)])
def test_stale_or_unsubmitted_inspection_cannot_bind(monkeypatch, status, version):
    from app.auth import service as auth
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (['super_admin'], []))
    monkeypatch.setattr(inspection_service, '_lock_inspection', lambda *args: SimpleNamespace(status=status, edit_version=version))
    db = Mock()
    with pytest.raises(ValueError, match='已变化'):
        inspection_service.bind_shipment(db, 1, SimpleNamespace(edit_version=3, shipment_version=0), 1)
    db.query.assert_not_called()


@pytest.mark.parametrize('issue', ['missing', 'deleted', 'no_upload', 'valid'])
def test_inspection_binding_requires_visible_uploaded_shipment(monkeypatch, issue):
    from app.auth import service as auth
    from app.tracking import shipment_service
    inspection = SimpleNamespace(status='submitted', edit_version=3, shipment_version=0, shipment_tracking_id=None, outbound_record_id='out-1', id=1)
    shipment = None if issue == 'missing' else SimpleNamespace(id=10, deleted_at=object() if issue == 'deleted' else None,
        source_image_url='' if issue == 'no_upload' else 'private.jpg', waybill_no='ABC', carrier='DHL')
    monkeypatch.setattr(inspection_service, '_lock_inspection', lambda *args: inspection)
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (['super_admin'], []))
    scope = Mock(side_effect=lambda query, *args: query)
    monkeypatch.setattr(shipment_service, 'apply_data_scope', scope)
    audit = Mock()
    monkeypatch.setattr(inspection_service.audit_service, 'record', audit)
    db = Mock()
    db.query.return_value.filter_by.return_value.with_for_update.return_value.populate_existing.return_value.first.return_value = shipment
    db.get.side_effect = lambda model, identifier: shipment if identifier == 10 else SimpleNamespace(username='staff')
    body = SimpleNamespace(waybill_no='ABC', carrier='DHL', edit_version=3, shipment_version=0)
    if issue == 'valid':
        assert inspection_service.bind_shipment(db, 1, body, 5) == {'waybill_no': 'ABC', 'carrier': 'DHL', 'shipment_version': 1}
        assert inspection.shipment_tracking_id == 10 and inspection.edit_version == 3 and inspection.shipment_version == 1
        audit.assert_called_once()
    else:
        with pytest.raises(ValueError, match='上传'):
            inspection_service.bind_shipment(db, 1, body, 5)
        assert inspection.shipment_tracking_id is None and inspection.edit_version == 3
        audit.assert_not_called()
    scope.assert_called_once()



@pytest.mark.parametrize('blocked', ['none', 'sync_pending', 'required_recheck', 'stale_mirror'])
def test_exact_outbound_inspection_limits_customer_shipment_details(source_invoice, monkeypatch, blocked):
    from app.models.business import OkkiOrder
    from app.invoice import detail_outbound_mirror
    from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
    from app.tracking.models import ShipmentTracking, TrackingEvent
    from app.core.time import beijing_now
    db, order = source_invoice
    connection = db.connection()
    schema = connection.dialect.identifier_preparer.quote(OkkiOrder.__table__.schema)
    connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS " + schema)
    for model in (OkkiOrder, ShipmentTracking, TrackingEvent, ShippingInspection, ShippingOperationEvent):
        model.__table__.create(connection)
    db.execute(Invoice.__table__.update().values(xiaoman_order_id='remote-order'))
    db.execute(OkkiOrder.__table__.insert().values(order_id='remote-order', company_id='1', status_name='已发货'))
    for identity in (10, 11, 12, 13):
        db.execute(ShipmentTracking.__table__.insert().values(id=identity, waybill_no=f'WB{identity}', carrier='DHL',
            carrier_name='DHL', dingtalk_user_id='private', dingtalk_user_name='private', source_image_url='private.jpg',
            deleted_at=beijing_now() if identity == 12 else None, unified_status='in_transit'))
        db.execute(TrackingEvent.__table__.insert().values(id=identity, waybill_no=f'WB{identity}', carrier='DHL',
            event_time=beijing_now(), description='Departed', raw_response='private'))
        db.execute(ShippingInspection.__table__.insert().values(id=identity,
            outbound_record_id='other-outbound' if identity == 11 else f'own-{identity}',
            shipment_tracking_id=identity, status='draft' if identity == 13 else 'submitted'))
    if blocked != 'none':
        evidence = {'required_recheck_ids': ['line']} if blocked == 'required_recheck' else (
            {'verified': {'update_time': '2026-10-28 12:00:00'}} if blocked == 'stale_mirror' else {})
        db.execute(ShippingOperationEvent.__table__.insert().values(id=1, scope='outbound-invoice-sync',
            request_id='own-10', source='pc', action='sync_pending' if blocked == 'sync_pending' else 'sync_done',
            login_user_id=1, operator_user_id=1, operator_name='Staff', login_name='Staff',
            outbound_record_id='own-10', result=evidence))
    db.commit()
    monkeypatch.setattr(detail_outbound_mirror, 'read', lambda db, invoice, scope: [
        {'record_id': f'own-{identity}'} for identity in (10, 12, 13)])
    result = view(db, order, details=True)
    assert result['processing_status'] == 'Shipped'
    assert result['dispatch_recorded'] is True
    assert [row['waybill_no'] for row in result['shipments']] == (['WB10'] if blocked == 'none' else [])
    if blocked == 'none':
        assert result['shipments'][0]['events'][0]['description'] == 'Departed'
    assert 'private' not in str(result)


@pytest.mark.parametrize('roles,permissions', [([], []), ([], ['tracking:read_all']), ([], ['shipping_inspection:write'])])
def test_revoked_live_permission_blocks_shipment_binding(monkeypatch, roles, permissions):
    from app.auth import service as auth
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (roles, permissions))
    lock = Mock()
    monkeypatch.setattr(inspection_service, '_lock_inspection', lock)
    with pytest.raises(ValueError, match='权限'):
        inspection_service.bind_shipment(Mock(), 1, SimpleNamespace(edit_version=3, shipment_version=0), 1)
    lock.assert_not_called()


def test_removed_live_scope_blocks_binding_before_tracking_lookup(monkeypatch):
    from app.auth import service as auth
    from app.tracking import shipment_service
    permissions = ['shipping_inspection:write', 'tracking:read_all']
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: ([], permissions))
    monkeypatch.setattr(inspection_service, '_lock_inspection', lambda *args: SimpleNamespace(status='submitted', edit_version=3, shipment_version=0, outbound_record_id='out'))
    db = Mock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    lookup = Mock()
    monkeypatch.setattr(shipment_service, 'apply_data_scope', lookup)
    with pytest.raises(ValueError, match='授权范围'):
        inspection_service.bind_shipment(db, 1, SimpleNamespace(edit_version=3, shipment_version=0), 1)
    lookup.assert_not_called()



def test_stale_shipment_version_cannot_replace_link(monkeypatch):
    from app.auth import service as auth
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (['super_admin'], []))
    inspection = SimpleNamespace(status='submitted', edit_version=3, shipment_version=2, shipment_tracking_id=10)
    monkeypatch.setattr(inspection_service, '_lock_inspection', lambda *args: inspection)
    db = Mock()
    with pytest.raises(ValueError, match='物流单关联已变化'):
        inspection_service.bind_shipment(db, 1, SimpleNamespace(edit_version=3, shipment_version=1), 1)
    assert inspection.edit_version == 3 and inspection.shipment_version == 2 and inspection.shipment_tracking_id == 10
    db.query.assert_not_called()
