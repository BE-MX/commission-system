"""验货单「上传物流单并关联」：预填口径、入库前置校验、入库后关联与失败提示。"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.shipping_inspection import shipment_link_service as link
from app.shipping_inspection import service as inspection_service
from app.shipping_inspection.schemas import InspectionShipmentCreate


def _inspection(**overrides):
    values = dict(id=7, outbound_no='KC-1', customer_name='Acme Ltd', status='submitted', edit_version=3,
                  shipment_version=0, shipment_tracking_id=None, outbound_record_id='out-1')
    values.update(overrides)
    return SimpleNamespace(**values)


def _body(**overrides):
    values = dict(waybill_no='1234567890', carrier='DHL', recipient_name='Jane', recipient_country='美国',
                  ship_date=date(2026, 10, 28), entry_source='manual', edit_version=3, shipment_version=0)
    values.update(overrides)
    return InspectionShipmentCreate(**values)


def _patch_prefill_sources(monkeypatch, *, contact='', country='', company_id='C1', order_ids=('O1',)):
    monkeypatch.setattr(link.outbound_service, 'order_ids_for_records', lambda db, ids: {'out-1': list(order_ids)})
    monkeypatch.setattr(link.outbound_service, 'get_outbound_record',
                        lambda db, rid, **kw: {'company_id': company_id} if company_id else None)
    contact_lookup = Mock(return_value=contact)
    monkeypatch.setattr(link, '_invoice_contact', contact_lookup)
    monkeypatch.setattr(link, '_customer_country', Mock(return_value=country))
    monkeypatch.setattr(link.service, 'shipment_brief', lambda db, insp: None)
    return contact_lookup


def test_prefill_uses_order_customer_contact_and_country(monkeypatch):
    contact = _patch_prefill_sources(monkeypatch, contact='Jane Doe', country='美国')
    result = link.shipment_prefill(Mock(), _inspection())
    assert result['recipient_name'] == 'Jane Doe' and result['recipient_country'] == '美国'
    assert result['order_id'] == 'O1' and result['edit_version'] == 3 and result['shipment_version'] == 0
    contact.assert_called_once()
    assert contact.call_args.args[1:] == ('C1', ['O1'])
    assert result['ship_date'] == link.beijing_today().isoformat()


def test_prefill_falls_back_to_customer_name_without_contact(monkeypatch):
    _patch_prefill_sources(monkeypatch, company_id='')
    result = link.shipment_prefill(Mock(), _inspection())
    assert result['recipient_name'] == 'Acme Ltd' and result['recipient_country'] == ''


def test_prefill_degrades_when_business_db_unavailable(monkeypatch):
    _patch_prefill_sources(monkeypatch)
    monkeypatch.setattr(link.outbound_service, 'order_ids_for_records', Mock(side_effect=RuntimeError('down')))
    db = Mock()
    result = link.shipment_prefill(db, _inspection())
    assert result['recipient_name'] == 'Acme Ltd' and result['order_id'] is None
    db.rollback.assert_called_once()


@pytest.mark.parametrize('roles,permissions,message', [
    ([], ['tracking:write'], '验货单编辑权限'),
    ([], ['shipping_inspection:write', 'tracking:read_all'], '物流单上传权限'),
])
async def test_create_requires_both_permissions_before_waybill_is_created(monkeypatch, roles, permissions, message):
    from app.auth import service as auth
    from app.tracking import upload_service
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (roles, permissions))
    create = AsyncMock()
    monkeypatch.setattr(upload_service, 'create_waybill_with_tracking', create)
    with pytest.raises(ValueError, match=message):
        await link.create_and_bind(Mock(), 7, _body(), {'sub': '5'})
    create.assert_not_called()


@pytest.mark.parametrize('inspection,body,message', [
    (_inspection(status='draft'), _body(), '验货单已变化'),
    (_inspection(edit_version=4), _body(), '验货单已变化'),
    (_inspection(shipment_version=1), _body(), '物流单关联已变化'),
])
async def test_stale_inspection_never_creates_orphan_waybill(monkeypatch, inspection, body, message):
    from app.auth import service as auth
    from app.tracking import upload_service
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (['super_admin'], []))
    create = AsyncMock()
    monkeypatch.setattr(upload_service, 'create_waybill_with_tracking', create)
    db = Mock()
    db.get.return_value = inspection
    with pytest.raises(ValueError, match=message):
        await link.create_and_bind(db, 7, body, {'sub': '5'})
    create.assert_not_called()


def _ready_db(monkeypatch, tracking):
    from app.auth import service as auth
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: (['super_admin'], []))
    db = Mock()
    db.get.return_value = _inspection()
    db.query.return_value.filter_by.return_value.first.return_value = tracking
    return db


async def test_create_reuses_tracking_flow_then_binds_inspection(monkeypatch):
    from app.tracking import upload_service
    db = _ready_db(monkeypatch, SimpleNamespace(id=10))
    create = AsyncMock(return_value={'waybill_no': '1234567890', 'short_link': 'https://s/x'})
    monkeypatch.setattr(upload_service, 'create_waybill_with_tracking', create)
    bind = Mock(return_value={'waybill_no': '1234567890', 'carrier': 'DHL', 'shipment_version': 1})
    monkeypatch.setattr(inspection_service, 'bind_shipment', bind)
    result = await link.create_and_bind(db, 7, _body(), {'sub': '5', 'username': 'staff'})
    payload = create.call_args.args[1]
    assert payload.waybill_no == '1234567890' and payload.recipient_country == '美国'
    assert not hasattr(payload, 'edit_version')
    linked = bind.call_args.args[2]
    assert (linked.waybill_no, linked.carrier, linked.edit_version, linked.shipment_version) == ('1234567890', 'DHL', 3, 0)
    assert result['shipment']['shipment_version'] == 1 and result['short_link'] == 'https://s/x'
    db.commit.assert_called_once()


async def test_bind_failure_after_create_reports_waybill_already_saved(monkeypatch):
    from app.tracking import upload_service
    db = _ready_db(monkeypatch, SimpleNamespace(id=10))
    monkeypatch.setattr(upload_service, 'create_waybill_with_tracking', AsyncMock(return_value={}))
    monkeypatch.setattr(inspection_service, 'bind_shipment', Mock(side_effect=ValueError('物流单关联已变化，请重新打开后核对')))
    with pytest.raises(link.ShipmentLinkError, match='已录入物流跟踪.*物流单关联已变化'):
        await link.create_and_bind(db, 7, _body(), {'sub': '5'})
    db.commit.assert_not_called()


async def test_missing_tracking_row_is_reported_instead_of_false_success(monkeypatch):
    from app.tracking import upload_service
    db = _ready_db(monkeypatch, None)
    monkeypatch.setattr(upload_service, 'create_waybill_with_tracking', AsyncMock(return_value={}))
    bind = Mock()
    monkeypatch.setattr(inspection_service, 'bind_shipment', bind)
    with pytest.raises(link.ShipmentLinkError, match='跟踪记录没有建成'):
        await link.create_and_bind(db, 7, _body(), {'sub': '5'})
    bind.assert_not_called()


def test_link_existing_accepts_unknown_carrier():
    from app.shipping_inspection.schemas import InspectionShipmentInput
    body = InspectionShipmentInput(waybill_no='AB-1', carrier='未知', edit_version=1, shipment_version=0)
    assert body.carrier == '未知'


def test_list_shipment_briefs_skip_deleted_tracking():
    rows = [SimpleNamespace(id=10, waybill_no='WB10', carrier='DHL')]
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = rows
    inspections = [_inspection(id=1, shipment_tracking_id=10, shipment_version=2),
                   _inspection(id=2, shipment_tracking_id=11), _inspection(id=3)]
    assert inspection_service._shipment_briefs(db, inspections) == {
        1: {'waybill_no': 'WB10', 'carrier': 'DHL', 'shipment_version': 2}}


def test_link_candidate_hidden_outside_tracking_scope(monkeypatch):
    from app.auth import service as auth
    from app.tracking import shipment_service
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: ([], ['shipping_inspection:write', 'tracking:read']))
    monkeypatch.setattr(shipment_service, 'apply_data_scope', lambda query, db, user: query)
    db = Mock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    assert link.link_candidate(db, _inspection(), 'WB1', 'DHL', 5) == {'visible': False}


def test_link_candidate_without_tracking_permission_reveals_nothing(monkeypatch):
    from app.auth import service as auth
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: ([], ['shipping_inspection:write']))
    db = Mock()
    assert link.link_candidate(db, _inspection(), 'WB1', 'DHL', 5) == {'visible': False}
    db.query.assert_not_called()


def test_link_candidate_returns_recipient_for_comparison(monkeypatch):
    from app.auth import service as auth
    from app.tracking import shipment_service
    monkeypatch.setattr(auth, 'get_live_user_authorization', lambda *args: ([], ['tracking:read_all']))
    monkeypatch.setattr(shipment_service, 'apply_data_scope', lambda query, db, user: query)
    db = Mock()
    db.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(
        id=10, receiver_name='Bob', receiver_country='德国')
    db.query.return_value.filter.return_value.scalar.return_value = 2
    assert link.link_candidate(db, _inspection(), 'WB1', 'DHL', 5) == {
        'visible': True, 'recipient_name': 'Bob', 'recipient_country': '德国', 'linked_inspections': 2}
