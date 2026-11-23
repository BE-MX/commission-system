"""Isolated SQLite regression tests for mobile preview, scope and binding boundaries."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.core.time import beijing_now, beijing_today
from app.cross_border import models as _cross_border_models
from app.shipping_inspection import waybill_preview_service as preview, waybill_binding_service as binding
from app.shipping_inspection import waybill_scope_service as scope, waybill_queue_service as queue_service
from app.shipping_inspection.models import ShippingInspection, ShippingOperationEvent
from app.shipping_inspection.schemas import InspectionShipmentInput, InspectionShipmentCreate, InspectionShipmentPreview
from app.shipping_inspection.waybill_photo_models import ShippingWaybillPhoto
from app.tracking.models import ShipmentTracking
from tests.test_shipping_inspection import _user, _bind_okki, outbound_scope_seed
from tests.test_cross_border_tickets import make_invoice

PERMS = ['shipping_inspection:write', 'tracking:write']


@pytest.fixture
def setup(db, outbound_scope_seed, monkeypatch):
    user = _user(db, 'mobile-sales')
    _bind_okki(db, user)
    a = ShippingInspection(outbound_record_id='OB001', outbound_no='OUT1', customer_name='Client One',
                           status='submitted', submitted_at=beijing_now(), edit_version=0, shipment_version=0)
    b = ShippingInspection(outbound_record_id='OB002', outbound_no='OUT2', customer_name='Client Two',
                           status='submitted', submitted_at=beijing_now(), edit_version=0, shipment_version=0)
    db.add_all([a, b]); db.flush()
    inv = make_invoice(db, transaction_mode='legacy', customer_id='C1', customer_name='Client One',
                       xiaoman_order_id='ORD1', contact_name='Jane', sales_user_id=user.id)
    db.execute(text("INSERT OR REPLACE INTO lsordertest.customer_info (company_id,country_name) VALUES ('C1','美国'),('C2','德国')"))
    db.add(ShippingWaybillPhoto(inspection_id=a.id, token='photo-one', rectified_path='r.jpg',
                              original_path='o.jpg', created_by=user.id, updated_by=user.id))
    db.commit()
    monkeypatch.setattr(binding, 'get_live_user_authorization', lambda *_: ([], PERMS))
    monkeypatch.setattr('app.auth.service.get_live_user_authorization', lambda *_: ([], PERMS))
    monkeypatch.setattr('app.tracking.carriers.get_adapter', lambda *_: None)
    return user, a, b, inv


def tracking(db, waybill_no='1234567890', carrier='未知'):
    row = ShipmentTracking(waybill_no=waybill_no, carrier=carrier, carrier_name=carrier, dingtalk_user_id='other-ding',
                           dingtalk_user_name='other-person', receiver_name='SECRET RECIPIENT', receiver_country='SECRET COUNTRY')
    db.add(row); db.flush()
    return row


def body(**kwargs):
    values = dict(waybill_no='1234567890', carrier='DHL', edit_version=0, shipment_version=0,
                  recipient_country='美国', recipient_name='Jane', source='mobile', photo_token='photo-one', number_source='barcode')
    values.update(kwargs)
    return InspectionShipmentInput(**values)


async def synchronize(db, setup, payload=None):
    user, a, _, _ = setup
    payload = payload or body()
    result = await preview.preview(db, a, InspectionShipmentPreview(**payload.model_dump()), user.id, [], PERMS)
    payload.preview_token = result['preview_token']
    payload.confirmed_warnings = [w['code'] for w in result['warnings'] if w['requires_confirmation']]
    return payload, result


def test_iso_cldr_country_aliases_cover_long_tail():
    for aliases, expected in [(('United States', '美国', 'USA', 'us'), 'US'),
                              (('Ivory Coast', 'Côte d’Ivoire', '科特迪瓦', 'CI'), 'CI'),
                              (('波斯尼亚和黑塞哥维那', 'Bosnia & Herzegovina', 'BA'), 'BA'),
                              (('UK', 'United Kingdom', '英国'), 'GB')]:
        for name in aliases:
            assert preview.country_code(name) == expected
    assert preview.country_code('unrecognized country') is None


@pytest.mark.parametrize('carrier,expected', [('DHL', 'failed'), ('FedEx', 'failed'), ('SF', 'failed'), ('UPS', 'unsupported')])
async def test_missing_carrier_configuration_is_failure_not_unsupported(db, setup, carrier, expected):
    _, result = await synchronize(db, setup, body(carrier=carrier))
    assert result['sync_result'] == expected and result['can_submit']
    assert not db.dirty and not db.new


async def test_invalid_dhl_and_cross_customer_are_blocked_without_token_or_identity(db, setup):
    _, result = await synchronize(db, setup, body(waybill_no='JD123'))
    assert not result['format_valid'] and not result['can_submit'] and result['preview_token'] is None
    user, a, b, _ = setup
    ship = tracking(db)
    b.shipment_tracking_id = ship.id; db.commit()
    payload, result = await synchronize(db, setup)
    assert result['existing']['blocked'] and not result['can_submit'] and result['preview_token'] is None
    assert 'SECRET' not in str(result) and 'other-person' not in str(result) and 'Client Two' not in str(result)
    with pytest.raises(ValueError, match='另一位客户'):
        binding.bind(db, a.id, body(source='pc'), user.id)
    ship.deleted_at = beijing_now(); db.commit()
    _, result = await synchronize(db, setup)
    assert result['existing']['blocked'] and not result['can_submit']
    assert ship.deleted_at is not None


async def test_outside_tracking_scope_can_bind_without_owner_transfer_and_retry_is_idempotent(db, setup):
    user, a, _, _ = setup
    ship = tracking(db); db.commit()
    payload, result = await synchronize(db, setup)
    assert result['existing']['outside_tracking_scope'] and result['existing']['carrier'] == '未知'
    assert 'SECRET' not in str(result) and 'other-person' not in str(result)
    result = binding.bind(db, a.id, payload, user.id); db.commit()
    assert result['carrier'] == '未知' and result['shipment_version'] == 1
    assert ship.dingtalk_user_id == 'other-ding'
    assert binding.bind(db, a.id, payload, user.id)['shipment_version'] == 1
    events = db.query(ShippingOperationEvent).filter_by(action='shipment_bound').all()
    assert len(events) == 1 and events[0].source == 'mobile' and events[0].payload['number_source'] == 'barcode'
    assert db.query(ShippingWaybillPhoto).filter_by(token='photo-one').one().shipment_tracking_id == ship.id


@pytest.mark.parametrize('field,value', [('waybill_no', '9999999999'), ('carrier', 'UPS'), ('recipient_country', 'CA'), ('photo_token', 'another-photo')])
async def test_preview_is_bound_to_editable_fields_and_photo(db, setup, field, value):
    user, a, _, _ = setup
    payload, _ = await synchronize(db, setup)
    setattr(payload, field, value)
    with pytest.raises(ValueError, match='重新同步'):
        preview.verify_preview(a.id, user.id, payload)


async def test_country_warning_requires_signed_confirmation_and_new_warning_cannot_be_preaccepted(db, setup):
    user, a, _, _ = setup
    ship = tracking(db, carrier='DHL'); db.commit()
    payload, result = await synchronize(db, setup, body(recipient_country='Germany'))
    assert any(w['code'] == 'recipient_country' and w['requires_confirmation'] for w in result['warnings'])
    payload.confirmed_warnings = []
    with pytest.raises(ValueError, match='确认国家'):
        binding.bind(db, a.id, payload, user.id)
    payload, _ = await synchronize(db, setup)
    db.execute(text("UPDATE lsordertest.customer_info SET country_name='加拿大' WHERE company_id='C1'"))
    payload.confirmed_warnings = ['recipient_country']
    with pytest.raises(ValueError, match='重新同步'):
        binding.bind(db, a.id, payload, user.id)


async def test_new_existing_record_after_preview_requires_resync(db, setup):
    user, a, _, _ = setup
    payload, _ = await synchronize(db, setup)
    tracking(db, carrier='DHL'); db.commit()
    with pytest.raises(ValueError, match='运单记录已变化'):
        binding.bind(db, a.id, payload, user.id)


def test_merchandiser_scope_and_nonexpress_pending_exclusion(db, setup):
    user, a, b, inv = setup
    assistant = _user(db, 'merchandiser')
    inv.merchandiser_id = assistant.id; db.commit()
    assert scope.visible_ids(db, [a, b], assistant.id, [], PERMS) == {a.id}
    queue = queue_service.queue(db, assistant.id, [], PERMS)
    assert [r['id'] for r in queue['items']] == [a.id]
    assert queue['items'][0]['quantity'] == 15 and queue['items'][0]['recipient_country'] == '美国'
    inv.express_channel = '货代/海运'; db.commit()
    assert queue_service.queue(db, assistant.id, [], PERMS)['total'] == 0
    inv.express_channel = None; db.commit()
    a.submitted_at = beijing_now() - timedelta(days=20); db.commit()
    assert queue_service.queue(db, assistant.id, [], PERMS)['total'] == 0
    assert queue_service.queue(db, assistant.id, [], PERMS, keyword='OUT1')['total'] == 1


async def test_recalled_inspection_and_missing_mobile_tracking_permission_fail(db, setup, monkeypatch):
    user, a, _, _ = setup
    ship = tracking(db, carrier='DHL'); db.commit()
    payload, _ = await synchronize(db, setup)
    monkeypatch.setattr(binding, 'get_live_user_authorization', lambda *_: ([], ['shipping_inspection:write', 'tracking:read']))
    with pytest.raises(ValueError, match='物流跟踪访问权限'):
        binding.bind(db, a.id, payload, user.id)
    monkeypatch.setattr(binding, 'get_live_user_authorization', lambda *_: ([], PERMS))
    a.status = 'draft'; db.commit()
    with pytest.raises(ValueError, match='验货单已变化'):
        binding.bind(db, a.id, payload, user.id)


def test_export_membership_uses_exact_inspection_and_old_tracking_not_alibaba_number(db, setup):
    from app.shipping_inspection.waybill_export_service import export_baseline
    user, a, b, inv = setup
    first, second = tracking(db), tracking(db, waybill_no='9999999999')
    a.shipment_tracking_id = first.id; b.shipment_tracking_id = second.id
    db.add(ShippingOperationEvent(scope='test-export', source='pc', action='shipment_exported',
        login_user_id=user.id, operator_user_id=user.id, operator_name='test', login_name='test',
        outbound_record_id=a.outbound_record_id, inspection_id=a.id,
        payload={'shipment_tracking_id': first.id, 'export_id': 1, 'content_hash': 'hash'})); db.commit()
    assert export_baseline(db, a.id) == first.id
    assert export_baseline(db, b.id) is None
    a.shipment_tracking_id = second.id; db.commit()
    assert export_baseline(db, a.id) != a.shipment_tracking_id


async def test_pc_post_duplicate_requires_confirmation_but_same_binding_retry_succeeds(db, setup):
    from app.shipping_inspection.shipment_link_service import create_and_bind
    from app.tracking.upload_service import WaybillConflict
    user, a, _, _ = setup
    ship = tracking(db); db.commit()
    request = InspectionShipmentCreate(**body(source='pc').model_dump(), ship_date=beijing_today())
    with pytest.raises(WaybillConflict) as error:
        await create_and_bind(db, a.id, request, {'sub': str(user.id), 'username': user.username})
    assert error.value.existing == {'waybill_no': request.waybill_no}
    a.shipment_tracking_id = ship.id; a.shipment_version = 1; db.commit()
    result = await create_and_bind(db, a.id, request, {'sub': str(user.id), 'username': user.username})
    assert result['shipment']['shipment_version'] == 1


async def test_mobile_create_uses_sales_owner_skips_second_poll_and_retries_without_create(db, setup, monkeypatch):
    from app.shipping_inspection.shipment_link_service import create_and_bind
    user, a, _, inv = setup
    photographer = _user(db, 'assistant-camera')
    inv.merchandiser_id = photographer.id
    user.dingtalk_id = 'sales-ding'
    photo = db.query(ShippingWaybillPhoto).filter_by(token='photo-one').one()
    photo.created_by = photographer.id; db.commit()
    payload = InspectionShipmentCreate(**body().model_dump(), ship_date=beijing_today())
    result = await preview.preview(db, a, InspectionShipmentPreview(**payload.model_dump()), photographer.id, [], PERMS)
    payload.preview_token = result['preview_token']
    calls = []
    async def create(db, request, actor, **kwargs):
        calls.append((request, actor, kwargs))
        ship = tracking(db, carrier=request.carrier)
        ship.dingtalk_user_id = kwargs['owner']['dingtalk_user_id']
        db.commit()
        return {'waybill_no': ship.waybill_no}
    monkeypatch.setattr('app.tracking.upload_service.create_waybill_with_tracking', create)
    actor = {'sub': str(photographer.id), 'username': photographer.username}
    saved = await create_and_bind(db, a.id, payload, actor)
    assert saved['shipment']['shipment_version'] == 1
    assert calls[0][2] == {'owner': {'dingtalk_user_id': 'sales-ding', 'dingtalk_user_name': user.real_name}, 'skip_initial_poll': True}
    assert calls[0][0].entry_source == 'barcode'
    # Retry with an expired/unavailable preview and changed customer metadata uses persisted receipt.
    payload.preview_token = 'expired'
    db.execute(text("UPDATE lsordertest.customer_info SET country_name='加拿大' WHERE company_id='C1'")); db.commit()
    assert (await create_and_bind(db, a.id, payload, actor))['shipment']['shipment_version'] == 1
    assert len(calls) == 1


def test_done_queue_uses_latest_actor_and_excludes_deleted_tracking(db, setup):
    user, a, _, _ = setup
    ship = tracking(db); a.shipment_tracking_id = ship.id
    for actor in [user.id + 100, user.id]:
        db.add(ShippingOperationEvent(scope='done-test', source='pc', action='shipment_bound',
            login_user_id=actor, operator_user_id=actor, operator_name='test', login_name='test',
            outbound_record_id=a.outbound_record_id, inspection_id=a.id, payload={'shipment_tracking_id': ship.id}))
        db.flush()
    db.commit()
    assert queue_service.queue(db, user.id, [], PERMS, tab='done')['total'] == 1
    ship.deleted_at = beijing_now(); db.commit()
    assert queue_service.queue(db, user.id, [], PERMS, tab='done')['total'] == 0
    assert queue_service.queue(db, user.id, [], PERMS, tab='pending')['total'] == 1


def test_exported_rebinding_survives_chain_and_clears_when_original_restored(db, setup):
    user, a, _, _ = setup
    ships = [tracking(db, waybill_no=str(number) * 10, carrier='DHL') for number in (1, 2, 3)]
    a.shipment_tracking_id = ships[0].id
    db.add(ShippingOperationEvent(scope='test-export', source='pc', action='shipment_exported',
        login_user_id=user.id, operator_user_id=user.id, operator_name='test', login_name='test',
        outbound_record_id=a.outbound_record_id, inspection_id=a.id,
        payload={'shipment_tracking_id': ships[0].id, 'export_id': 1, 'content_hash': 'hash'})); db.commit()
    for ship, expected in [(ships[1], True), (ships[2], True), (ships[0], False)]:
        binding.bind(db, a.id, body(source='pc', photo_token=None, waybill_no=ship.waybill_no,
                                  shipment_version=a.shipment_version), user.id)
        db.commit()
        event = db.query(ShippingOperationEvent).filter_by(action='shipment_bound').order_by(ShippingOperationEvent.id.desc()).first()
        assert event.payload['exported_rebind'] is expected


async def test_edited_country_cannot_erase_immutable_ocr_mismatch(db, setup):
    user, a, _, _ = setup
    ship = tracking(db, carrier='DHL')
    photo = db.query(ShippingWaybillPhoto).filter_by(token='photo-one').one()
    photo.ocr_recipient_country = 'Germany'
    photo.ocr_recipient_name = 'Other Recipient'
    db.commit()
    payload, result = await synchronize(db, setup, body(recipient_country='United States', recipient_name='Jane'))
    assert {w['code'] for w in result['warnings']} >= {'ocr_country', 'ocr_recipient_name'}
    payload.confirmed_warnings = []
    with pytest.raises(ValueError, match='确认国家'):
        binding.bind(db, a.id, payload, user.id)
    payload.confirmed_warnings = ['ocr_country']
    assert binding.bind(db, a.id, payload, user.id)['shipment_version'] == 1


def test_local_owner_without_okki_binding_has_queue_prefill_and_binding(db, setup):
    from app.customer.models import CustomerAccount
    from app.invoice.settlement_models import ShipmentOutbound
    from app.shipping_inspection.shipment_link_service import shipment_prefill
    _, _, _, _ = setup
    owner = _user(db, 'local-owner-no-okki')
    customer = CustomerAccount(customer_code='WAYBILL-LOCAL', display_name='Local Customer',
        entity_type='registered_company', identity_status='verified', relationship_stage='qualified',
        relationship_stage_changed_at=beijing_now(), relationship_stage_reason='test', record_status='active',
        identity_confidence=1, profile_completeness=80, profile_input_seq=1, primary_country_code='CA')
    db.add(customer); db.flush()
    inv = make_invoice(db, 2, local_customer_id=customer.id, sales_user_id=owner.id, contact_name='Local Jane')
    outbound = ShipmentOutbound(id=2, settlement_id=2, invoice_id=inv.id, outbound_no='LOCAL-OUT', status='local_shipped',
        payload={'transaction_mode':'local', 'outbound_version':1, 'customer_name':'Local Customer',
                 'owner_name':owner.real_name, 'items':[{'invoice_item_id':2, 'qty':4}]}, payload_hash='local-hash')
    db.add(outbound); db.flush()
    inspection = ShippingInspection(outbound_record_id='local-2', local_outbound_id=2, outbound_no='LOCAL-OUT',
        customer_name='Local Customer', status='submitted', submitted_at=beijing_now())
    db.add(inspection); db.commit()
    result = queue_service.queue(db, owner.id, [], PERMS)
    assert [r['id'] for r in result['items']] == [inspection.id]
    assert result['items'][0]['quantity'] == 4 and result['items'][0]['recipient_country'] == 'CA'
    prefill = shipment_prefill(db, inspection, strict=True)
    assert prefill['recipient_name'] == 'Local Jane' and prefill['recipient_country'] == 'CA'
    tracking(db, carrier='DHL'); db.commit()
    assert binding.bind(db, inspection.id, body(source='pc', photo_token=None), owner.id)['shipment_version'] == 1


async def test_mixed_9610_and_non_dhl_are_advisory(db, setup):
    _, _, b, _ = setup
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET company_id='C1' WHERE id='OB002'"))
    make_invoice(db, 2, transaction_mode='legacy', xiaoman_order_id='ORD2', customer_id='C1',
                 internal_payment_method='普通付款', express_channel='DHL普货')
    ship = tracking(db, carrier='UPS')
    b.shipment_tracking_id = ship.id; db.commit()
    _, result = await synchronize(db, setup)
    codes = {w['code'] for w in result['warnings']}
    assert {'mixed_waybill', 'non_dhl'} <= codes and result['can_submit']
    assert not any(w['requires_confirmation'] for w in result['warnings'])


def test_legacy_export_without_association_is_unverified_not_assigned_to_whole_order(db, setup):
    from app.cross_border.models import Declaration, ExportBatch
    from app.shipping_inspection.waybill_export_service import export_baseline, legacy_export_unverified
    user, a, _, inv = setup
    db.add(Declaration(order_no=inv.alibaba_order_no, content_hash='legacy-declaration', occurrence=1,
        base_json={}, head_json={}, line_json={}, first_import_id=1, first_row_no=1, last_import_id=1))
    export = ExportBatch(created_by=user.id, content_hashes=['legacy-declaration'], order_file=b'old-orders', receipt_file=b'old-receipts')
    db.add(export); db.flush()
    assert legacy_export_unverified(db, a, [inv])
    assert export_baseline(db, a.id) is None
    db.add(ShippingOperationEvent(scope='test-export', source='pc', action='shipment_exported',
        login_user_id=user.id, operator_user_id=user.id, operator_name='test', login_name='test',
        outbound_record_id='different-split', inspection_id=999,
        payload={'shipment_tracking_id': 999, 'export_id': export.id, 'content_hash': 'legacy-declaration'})); db.flush()
    assert not legacy_export_unverified(db, a, [inv])
    assert export_baseline(db, a.id) is None
