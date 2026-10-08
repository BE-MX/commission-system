"""Stable mirror photo identities must leave the upload/scan contract usable."""
from copy import deepcopy

from app.shipping_inspection import outbound_service, outbound_sync_state as state, service
from app.shipping_inspection.models import ShippingInspectionPhoto
from tests.test_shipping_snapshot_refresh import caught_up
from tests.test_outbound_invoice_sync import sync_case, case, product_display_source, outbound_scope_seed


def test_relinked_photo_groups_with_local_rows_and_remote_verified_audit_stays_intact(db, caught_up):
    user, event = caught_up
    before = deepcopy(event.result)
    inspection = service.get_or_create_draft(db, 'OB001', user.id)
    # State after the mirror's atomic okki:701 -> LOCAL1 photo association update.
    photo = ShippingInspectionPhoto(inspection_id=inspection.id, item_id='LOCAL1',
        file_path='shipping-inspection/relinked.jpg', created_by=user.id)
    db.add(photo)
    db.commit()
    assert outbound_service.mirror_matches_snapshot(db, 'OB001', event.result['verified'])
    assert state.overlay(db, outbound_service.get_outbound_record(db, 'OB001'), event=event) is None
    state.ensure_inspection_idle(db, 'OB001', user.id)
    payload = service.scan_payload(db, 'OB001')
    item_ids = {item['item_id'] for item in payload['items']}
    linked = next(row for row in payload['photos'] if row['id'] == photo.id)
    assert linked['item_id'] == 'LOCAL1' and linked['item_id'] in item_ids
    fresh = service.add_photo(db, outbound_record_id='OB001', item_id='LOCAL1',
        file_path='shipping-inspection/next.jpg', user_id=user.id)
    assert fresh.item_id == 'LOCAL1'
    assert event.result == before
    assert event.result['verified']['items'][0]['item_id'] == 'okki:701'
