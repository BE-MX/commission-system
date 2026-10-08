"""Fee rows do not require physical evidence; actual products still do."""
import pytest
from sqlalchemy import text

from app.shipping_inspection import service, outbound_sync_state as state
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from tests.test_shipping_inspection import product_display_source, _user


@pytest.fixture
def recheck(db):
    user = _user(db)
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_name='Other Items' WHERE id='IT002'"))
    inspection = ShippingInspection(outbound_record_id='OB001', status='draft', created_by=user.id)
    db.add(inspection)
    db.flush()
    event = ShippingOperationEvent(scope=state.SCOPE, request_id='OB001', source='pc', action='sync_done',
        login_user_id=user.id, operator_user_id=user.id, operator_name='Inspector', login_name='Inspector',
        outbound_record_id='OB001', result={'required_recheck_ids': ['__all_items__'], 'stale_media_ids': []})
    db.add(event)
    db.commit()
    return user, inspection, event


def photo(db, inspection, item_id, media_type='image'):
    row = ShippingInspectionPhoto(inspection_id=inspection.id, item_id=item_id, file_path='test.jpg', media_type=media_type)
    db.add(row)
    db.commit()
    return row


def test_real_product_photos_unlock_submission_without_other_items_photo(db, recheck):
    user, inspection, event = recheck
    photo(db, inspection, 'IT001')
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'
    assert event.result['required_recheck_ids'] == []


@pytest.mark.parametrize('coverage', ['fee', 'whole', 'stale', 'video'])
def test_fee_or_old_evidence_never_replaces_actual_product_photos(db, recheck, coverage):
    user, inspection, event = recheck
    row = photo(db, inspection, 'IT002' if coverage == 'fee' else None if coverage == 'whole' else 'IT001',
                'video' if coverage == 'video' else 'image')
    if coverage == 'stale':
        event.result = {**event.result, 'stale_media_ids': [row.id]}
        db.commit()
    with pytest.raises(ValueError, match='补拍'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


def test_whole_order_requirement_remains_after_fee_exclusion(db, recheck):
    user, inspection, event = recheck
    event.result = {**event.result, 'required_recheck_ids': ['__all_items__', '__whole__']}
    photo(db, inspection, 'IT001')
    with pytest.raises(ValueError, match='补拍'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_explicit_fee_id_is_excluded_and_actual_product_id_still_checked(db, recheck):
    user, inspection, event = recheck
    event.result = {**event.result, 'required_recheck_ids': ['IT001', 'IT002']}
    db.commit()
    with pytest.raises(ValueError, match='补拍'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, 'IT001')
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_scan_and_detail_return_the_same_recheck_exclusion(db, recheck):
    _, inspection, _ = recheck
    scanned = service.scan_payload(db, 'OB001')
    detailed = service.get_record_detail(db, inspection.id)
    for payload in (scanned, detailed):
        rules = {item['item_id']: item['requires_recheck_photo'] for item in payload['items']}
        assert rules == {'IT001': True, 'IT002': False}


def test_unknown_explicit_item_is_not_silently_excluded(db, recheck):
    user, inspection, event = recheck
    event.result = {**event.result, 'required_recheck_ids': ['UNKNOWN', 'IT002']}
    photo(db, inspection, 'IT001')
    with pytest.raises(ValueError, match='补拍'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


def test_fee_only_outbound_keeps_the_minimum_whole_order_photo_rule(db, recheck):
    user, inspection, _ = recheck
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_name='Other Items' WHERE id='IT001'"))
    db.commit()
    with pytest.raises(ValueError, match='至少上传'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_missing_mirror_is_still_blocked(db, recheck):
    user, inspection, _ = recheck
    db.execute(text("DELETE FROM lsordertest.okki_outbound_record_items WHERE outbound_record_id='OB001'"))
    photo(db, inspection, None)
    with pytest.raises(ValueError, match='刷新'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


def test_fee_only_outbound_cannot_complete_recheck_using_only_old_photos(db, recheck):
    user, inspection, event = recheck
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_name='Other Items' WHERE id='IT001'"))
    old = photo(db, inspection, None)
    event.result = {**event.result, 'stale_media_ids': [old.id]}
    db.commit()
    with pytest.raises(ValueError, match='当前版本'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


@pytest.mark.parametrize('name,expected', [('Other Items', False), (' OTHER ITEMS ', False),
    ('Other', True), ('Other Items Hair/22', True), ('Hair', True), (None, True)])
def test_exclusion_matches_only_the_other_items_name(name, expected):
    assert state.requires_recheck_photo({'product_name': name}) is expected
