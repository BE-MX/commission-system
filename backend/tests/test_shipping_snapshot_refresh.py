"""Mirror catch-up uses outbound rows, independent of product display metadata."""
from copy import deepcopy

import pytest
from sqlalchemy import text

from app.shipping_inspection import outbound_service, outbound_sync_state as state, service
from app.shipping_inspection.models import ShippingOperationEvent
from tests.test_outbound_invoice_sync import sync_case, case, product_display_source, outbound_scope_seed


@pytest.fixture
def caught_up(db, sync_case):
    user, _, _, _ = sync_case
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN update_time TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET update_time='2026-10-08 07:10:55', remark='note' WHERE id='OB001'"))
    db.execute(text("DELETE FROM lsordertest.okki_outbound_record_items WHERE outbound_invoice_id='77'"))
    db.execute(text("""INSERT INTO lsordertest.okki_outbound_record_items
        (id, outbound_record_id, outbound_invoice_id, product_id, product_name, quantity, unit, spec, sku)
        VALUES ('LOCAL1', '701', '77', 101, 'Weft', 1, 'Piece', 'Weft', '5813'),
               ('LOCAL2', '702', '77', 102, 'Other Items', 1, 'Piece', 'Fee', '6614')"""))
    db.execute(text("UPDATE lsordertest.okki_products SET size='24', color='#5ATP5A/1006' WHERE product_id=101"))
    db.execute(text("UPDATE lsordertest.okki_products SET size='Fee', color='Fee' WHERE product_id=102"))
    snapshot = {'update_time': '2026-10-08 07:10:55', 'serial_id': 'CK2026001', 'remark': 'note', 'items': [
        {'item_id': 'okki:701', 'product_id': '101', 'product_name': 'Weft', 'qty': 1.0,
         'unit': 'Piece', 'spec': 'Weft', 'sku': '5813', 'model': 'Weft', 'size': '24', 'color': '5ATP5A/1006'},
        {'item_id': 'okki:702', 'product_id': '102', 'product_name': 'Other Items', 'qty': 1.0,
         'unit': 'Piece', 'spec': 'Fee', 'sku': '6614', 'model': 'Fee', 'size': None, 'color': 'Fee'},
    ]}
    event = ShippingOperationEvent(scope=state.SCOPE, request_id='OB001', source='pc', action='sync_done',
        login_user_id=user.id, operator_user_id=user.id, operator_name='Inspector', login_name='Inspector',
        outbound_record_id='OB001', payload={}, result={'verified': snapshot})
    db.add(event)
    db.commit()
    outbound_service._columns_cache.clear()
    return user, event


def test_caught_up_mirror_unlocks_draft_and_photo_despite_product_metadata_difference(db, caught_up):
    user, event = caught_up
    record = outbound_service.get_outbound_record(db, 'OB001')
    assert state.overlay(db, record, event=event) is None
    draft = service.get_or_create_draft(db, 'OB001', user.id)
    photo = service.add_photo(db, outbound_record_id='OB001', item_id='LOCAL1',
                              file_path='shipping-inspection/test.jpg', user_id=user.id)
    assert photo.inspection_id == draft.id
    assert photo.item_id == 'LOCAL1'
    assert [r['item_id'] for r in outbound_service.list_outbound_items(db, 'OB001')] == ['LOCAL1', 'LOCAL2']


@pytest.mark.parametrize('change', [
    "DELETE FROM lsordertest.okki_outbound_record_items WHERE id='LOCAL2'",
    "UPDATE lsordertest.okki_outbound_record_items SET quantity=2 WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET quantity=NULL WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET outbound_record_id='999' WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET outbound_record_id=NULL WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET product_id=999 WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET sku='old' WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET spec='old' WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET product_name='old' WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_record_items SET unit='old' WHERE id='LOCAL1'",
    "UPDATE lsordertest.okki_outbound_records SET remark='old' WHERE id='OB001'",
    "UPDATE lsordertest.okki_outbound_records SET outbound_no='old' WHERE id='OB001'",
    "UPDATE lsordertest.okki_outbound_records SET update_time='2026-10-08 07:10:54' WHERE id='OB001'",
])
def test_incomplete_or_different_outbound_still_blocks_upload(db, caught_up, change):
    user, event = caught_up
    db.execute(text(change))
    db.commit()
    record = outbound_service.get_outbound_record(db, 'OB001')
    assert state.overlay(db, record, event=event)
    with pytest.raises(ValueError, match='刷新'):
        service.add_photo(db, outbound_record_id='OB001', item_id='LOCAL1',
                          file_path='shipping-inspection/test.jpg', user_id=user.id)


def test_snapshot_row_order_does_not_affect_catch_up(db, caught_up):
    _, event = caught_up
    snapshot = deepcopy(event.result['verified'])
    snapshot['items'].reverse()
    event.result = {'verified': snapshot}
    db.commit()
    assert state.overlay(db, outbound_service.get_outbound_record(db, 'OB001'), event=event) is None


@pytest.mark.parametrize('action', state.BLOCKED)
def test_sync_in_progress_still_blocks_caught_up_mirror(db, caught_up, action):
    user, event = caught_up
    event.action = action
    db.commit()
    with pytest.raises(ValueError, match='同步|核对'):
        service.get_or_create_draft(db, 'OB001', user.id)
