"""After a change only a fresh whole-order photo is mandatory; detail photos are optional."""
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


def test_whole_photo_is_required_and_unlocks_submission(db, recheck):
    user, inspection, event = recheck
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, 'IT001')  # A detail photo no longer replaces the whole photo.
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'
    assert event.result['required_recheck_ids'] == []


@pytest.mark.parametrize('coverage', ['fee', 'item', 'video', 'stale'])
def test_only_a_fresh_whole_image_unlocks_submission(db, recheck, coverage):
    user, inspection, event = recheck
    item = 'IT002' if coverage == 'fee' else 'IT001'
    row = photo(db, inspection, item, 'video' if coverage == 'video' else 'image')
    if coverage == 'stale':
        event.result = {**event.result, 'stale_media_ids': [row.id]}
        db.commit()
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


def test_whole_order_requirement_remains_after_fee_exclusion(db, recheck):
    user, inspection, event = recheck
    event.result = {**event.result, 'required_recheck_ids': ['__all_items__', '__whole__']}
    photo(db, inspection, 'IT001')
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_explicit_item_requirements_collapse_to_whole(db, recheck):
    user, inspection, event = recheck
    event.result = {**event.result, 'required_recheck_ids': ['IT001', 'IT002']}
    db.commit()
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, 'IT001')
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_scan_and_detail_return_the_same_recheck_exclusion(db, recheck):
    _, inspection, _ = recheck
    scanned = service.scan_payload(db, 'OB001')
    detailed = service.get_record_detail(db, inspection.id)
    for payload in (scanned, detailed):
        rules = {item['item_id']: item['requires_recheck_photo'] for item in payload['items']}
        assert rules == {'IT001': True, 'IT002': False}


def test_unknown_explicit_item_still_requires_whole_photo(db, recheck):
    user, inspection, event = recheck
    event.result = {**event.result, 'required_recheck_ids': ['UNKNOWN', 'IT002']}
    photo(db, inspection, 'IT001')
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


def test_fee_only_outbound_keeps_the_minimum_whole_order_photo_rule(db, recheck):
    user, inspection, _ = recheck
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_name='Other Items' WHERE id='IT001'"))
    db.commit()
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_missing_mirror_does_not_block_whole_photo_submission(db, recheck):
    user, inspection, _ = recheck
    db.execute(text("DELETE FROM lsordertest.okki_outbound_record_items WHERE outbound_record_id='OB001'"))
    photo(db, inspection, None)
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_fee_only_outbound_cannot_complete_recheck_using_only_old_photos(db, recheck):
    user, inspection, event = recheck
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_name='Other Items' WHERE id='IT001'"))
    old = photo(db, inspection, None)
    event.result = {**event.result, 'stale_media_ids': [old.id]}
    db.commit()
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)


@pytest.mark.parametrize('name,expected', [('Other Items', False), (' OTHER ITEMS ', False),
    ('Other', True), ('Other Items Hair/22', True), ('Hair', True), (None, True)])
def test_exclusion_matches_only_the_other_items_name(name, expected):
    assert state.requires_recheck_photo({'product_name': name}) is expected
