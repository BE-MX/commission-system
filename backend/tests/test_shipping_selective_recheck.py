"""Selective evidence rules and audited recovery, using isolated SQLite only."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.shipping_inspection import outbound_recheck as recheck, outbound_sync_state as state, service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from app.invoice.models import InvoiceItem
from app.shipping_inspection import outbound_sync_service as sync, outbound_service
from app.shipping_inspection.outbound_sync_plan import physical_changes
from tests.test_shipping_snapshot_refresh import caught_up, sync_case, case, product_display_source, outbound_scope_seed


def row(remote, order, **values):
    return dict(outbound_record_id=remote, order_record_id=order, product_name='Hair', **values)


def media(identity, item):
    return SimpleNamespace(id=identity, item_id=item)


def line(remote, order, *, product_id=11, sku_id=110, name='Hair', count=1):
    return dict(outbound_record_id=remote, order_record_id=order, product_id=product_id,
                sku_id=sku_id, product_name=name, product_model='Weft', product_unit='Piece',
                outbound_count=count)


def test_changed_product_keeps_other_products_and_stales_whole():
    old = [row(701, 100), row(702, 101)]
    plan = dict(before={'record_list': old}, material_order_ids=['100'], removed_order_ids=[], remark_changed=False)
    links = [dict(local_item_id='LOCAL1', remote_item_id=701), dict(local_item_id='LOCAL2', remote_item_id=702)]
    stale, required = recheck.changes(plan, {'record_list': old}, links,
                                    [media(1, 'LOCAL1'), media(2, 'LOCAL2'), media(3, None), media(4, 'okki:702')], {})
    assert stale == [1, 3]
    assert required == ['__whole__']


def test_added_and_removed_products_preserve_other_evidence_and_clear_deleted_requirements():
    plan = dict(before={'record_list': [row(701, 100), row(702, 101)]},
                material_order_ids=['102'], removed_order_ids=['100'], remark_changed=False)
    stale, required = recheck.changes(plan, {'record_list': [row(702, 101), row(703, 102)]},
        [dict(local_item_id='LOCAL1', remote_item_id=701), dict(local_item_id='LOCAL2', remote_item_id=702)],
        [media(1, 'LOCAL1'), media(2, 'LOCAL2'), media(3, None)],
        {'stale_media_ids': [9], 'required_recheck_ids': ['okki:701', 'LOCAL1', 'okki:702']})
    assert stale == [1, 3, 9]
    assert required == ['__whole__']


def test_changed_fee_row_needs_only_whole_photo():
    plan = dict(before={'record_list': [row(701, 100)]}, material_order_ids=['100'], removed_order_ids=[], remark_changed=False)
    stale, required = recheck.changes(plan, {'record_list': [dict(row(701, 100), product_name='Other Items')]}, [],
                                     [media(1, 'okki:701'), media(2, None)], {})
    assert stale == [1, 2] and required == ['__whole__']


@pytest.mark.parametrize('operation', ['add', 'change', 'remove'])
def test_fee_only_changes_keep_whole_and_product_evidence(operation):
    hair, fee = row(701, 100), dict(row(702, 101), product_name='Other Items')
    old = [hair] if operation == 'add' else [hair, fee]
    after = [hair] if operation == 'remove' else [hair, fee]
    plan = dict(before={'record_list': old}, material_order_ids=[] if operation == 'remove' else ['101'],
                removed_order_ids=['101'] if operation == 'remove' else [], remark_changed=False)
    stale, required = recheck.changes(plan, {'record_list': after},
        [dict(local_item_id='LOCAL1', remote_item_id=701)],
        [media(1, 'LOCAL1'), media(2, None)], {})
    assert stale == []
    assert required == []


def test_fee_only_changes_preserve_prior_recheck_and_remark_changes_still_need_whole():
    old = [row(701, 100), dict(row(702, 101), product_name='Other Items')]
    plan = dict(before={'record_list': old}, material_order_ids=[], removed_order_ids=['101'], remark_changed=False)
    previous = {'stale_media_ids': [1], 'required_recheck_ids': ['okki:701', '__whole__']}
    stale, required = recheck.changes(plan, {'record_list': old[:1]}, [], [media(1, 'UNKNOWN'), media(2, None)], previous)
    assert stale == [1] and required == ['__whole__']
    plan['remark_changed'] = True
    stale, required = recheck.changes(plan, {'record_list': old[:1]}, [], [media(2, None)], {})
    assert stale == [2] and required == ['__whole__']


@pytest.mark.parametrize('before_name,after_name', [
    ('Hair', 'Other Items'), ('Other Items', 'Hair'), ('Other', 'Other Items'), (None, 'Other Items'),
])
def test_product_fee_transitions_and_unknown_names_are_still_physical(before_name, after_name):
    before = [dict(row(701, 100), product_name=before_name)]
    after = [dict(row(701, 100), product_name=after_name)]
    assert physical_changes(before, after, ['100'], []) == ({'100'}, set())


def test_missing_changed_or_removed_identity_is_not_assumed_to_be_a_fee():
    assert physical_changes([], [], ['100'], ['101']) == ({'100'}, {'101'})


def test_unknown_legacy_local_photo_cannot_be_guessed_from_product_name():
    plan = dict(before={'record_list': [row(701, 100)]}, material_order_ids=['100'], removed_order_ids=[], remark_changed=False)
    stale, required = recheck.changes(plan, {'record_list': [row(701, 100)]}, [], [media(1, 'UNKNOWN')], {})
    assert stale == [1] and required == ['__whole__']


def test_previously_stale_deleted_photo_does_not_invalidate_unchanged_products_on_next_edit():
    old = [row(702, 101), row(703, 102)]
    plan = dict(before={'record_list': old}, material_order_ids=['101'], removed_order_ids=[], remark_changed=False)
    stale, required = recheck.changes(plan, {'record_list': old},
        [dict(local_item_id='LOCAL2', remote_item_id=702), dict(local_item_id='LOCAL3', remote_item_id=703)],
        [media(1, 'DELETED_LOCAL1'), media(2, 'LOCAL2'), media(3, 'LOCAL3')], {'stale_media_ids': [1]})
    assert stale == [1, 2] and required == ['__whole__']


def test_verified_invoice_sync_invalidates_only_the_changed_product(db, sync_case):
    user, invoice, _, fake = sync_case
    invoice.remark = fake['outbound']['remark']
    db.add(InvoiceItem(invoice_id=invoice.id, sort_order=2, product_id=33, sku_id=330,
        product_name='Cookies Cream', product_display='Cookies Cream', color='Cookies Cream', length='22', quantity=2,
        price_per_piece=20, total_price=40, xiaoman_unique_id='101'))
    fake['order']['product_list'].append(dict(unique_id=101, product_id=33, sku_id=330, count=2,
        unit_price=20, product_name='Cookies Cream', unit='Piece', product_model='Weft'))
    fake['outbound']['record_list'].append(dict(outbound_record_id=702, order_id=123, order_record_id=101,
        product_id=33, sku_id=330, outbound_count=2, sale_price=20, product_name='Cookies Cream',
        product_model='Weft', product_cn_name='', product_unit='Piece', cost_unit_price_rmb=0, sku_code='33'))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_record_id='701' WHERE id='IT001'"))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_record_id='702' WHERE id='IT002'"))
    inspection = ShippingInspection(outbound_record_id='OB001', status='draft', created_by=user.id)
    db.add(inspection)
    db.flush()
    photos = [ShippingInspectionPhoto(inspection_id=inspection.id, item_id=key, file_path='old.jpg')
              for key in ('IT001', 'IT002', None)]
    db.add_all(photos)
    db.commit()
    actor = {'sub': str(user.id), 'permissions': ['shipping_inspection:write', 'invoice:sync', 'invoice:read_all']}
    record = outbound_service.get_outbound_record(db, 'OB001')
    preview = sync.preview(db, record, actor)
    assert sync.synchronize(db, record, actor, preview['version'], confirm_recheck=True)['status'] == 'sync_done'
    event = db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE).one()
    assert event.result['stale_media_ids'] == [photos[0].id, photos[2].id]
    assert event.result['required_recheck_ids'] == ['__whole__']


@pytest.fixture
def legacy(db, caught_up):
    user, event = caught_up
    for key in ('sku_id', 'product_cn_name', 'order_record_id'):
        db.execute(text(f'ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN {key} TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET sku_id='11',product_cn_name='',order_id='99',order_record_id='100' WHERE id='LOCAL1'"))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET product_name='Hair/22',sku_id='22',product_cn_name='',order_id='99',order_record_id='101' WHERE id='LOCAL2'"))
    snapshot = deepcopy(event.result['verified'])
    snapshot['items'][1]['product_name'] = 'Hair/22'
    inspection = ShippingInspection(outbound_record_id='OB001', status='draft', edit_version=2, created_by=user.id)
    db.add(inspection)
    db.flush()
    photos = [ShippingInspectionPhoto(inspection_id=inspection.id, item_id=item, file_path='old.jpg')
              for item in (None, 'LOCAL1', 'LOCAL1', 'LOCAL2', 'LOCAL2')]
    db.add_all(photos)
    db.flush()
    actual = recheck.outbound_service.inspection_item_links(db, 'OB001')
    expected = [{**item, 'outbound_record_id': item['remote_item_id']} for item in actual]
    before = deepcopy(expected)
    before[1]['product_name'] = 'Hair/24'
    plan = dict(before={'record_list': before}, expected=expected,
                inspection={'id': inspection.id, 'edit_version': 1, 'media_ids': [photo.id for photo in photos]},
                material_order_ids=['101'], removed_order_ids=[], remark_changed=False,
                serial_after=snapshot['serial_id'], remark_after=snapshot['remark'])
    history = ShippingOperationEvent(scope='outbound-sync-history', source='pc', action='recheck_required',
        login_user_id=user.id, operator_user_id=user.id, operator_name='Inspector', login_name='Inspector',
        outbound_record_id='OB001', payload={'plan': plan}, result={})
    db.add(history)
    event.result = {'verified': snapshot, 'stale_media_ids': [photo.id for photo in photos], 'required_recheck_ids': ['__all_items__']}
    db.commit()
    return user, inspection, event, history, photos


def test_audited_legacy_recovery_is_read_only_and_keeps_unchanged_photos(db, legacy):
    _, inspection, event, history, photos = legacy
    original = deepcopy(event.result)
    payload = service.scan_payload(db, 'OB001')
    assert payload['required_recheck_ids'] == ['__whole__']
    assert [photo['stale'] for photo in payload['photos']] == [True, False, False, True, True]
    assert service.get_record_detail(db, inspection.id)['required_recheck_ids'] == payload['required_recheck_ids']
    assert recheck.effective_result(db, event)['selective_recheck_history_id'] == history.id
    assert event.result == original


@pytest.mark.parametrize('proof_failure', ['version', 'missing_photo', 'prior_round', 'changed_mirror', 'replaced_id', 'missing_history', 'later_version'])
def test_legacy_recovery_fails_closed_without_complete_proof(db, legacy, proof_failure):
    _, inspection, event, history, photos = legacy
    if proof_failure == 'version': inspection.edit_version += 1
    if proof_failure == 'missing_photo': db.delete(photos[1])
    if proof_failure == 'prior_round': history.result = {'stale_media_ids': [photos[1].id]}
    if proof_failure == 'changed_mirror':
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET sku_id='OTHER' WHERE id='LOCAL1'"))
    if proof_failure == 'replaced_id':
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_record_id='999' WHERE id='LOCAL1'"))
    if proof_failure == 'missing_history': db.delete(history)
    if proof_failure == 'later_version':
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET update_time='2026-10-08 07:10:56' WHERE id='OB001'"))
    db.commit()
    assert recheck.effective_result(db, event) == event.result


def test_legacy_recovery_collapses_unknown_detail_links_to_whole(db, legacy):
    _, _, event, _, photos = legacy
    photos[1].item_id = 'UNKNOWN'
    db.commit()
    assert recheck.effective_result(db, event)['required_recheck_ids'] == ['__whole__']


def test_recovered_round_requires_only_a_fresh_whole_photo_then_audits_submission(db, legacy):
    user, inspection, event, history, photos = legacy
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, item_id=None, file_path='whole.jpg'))
    db.commit()
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id, edit_version=2).status == 'submitted'
    assert event.result['stale_media_ids'] == [photos[0].id, photos[3].id, photos[4].id]
    assert event.result['required_recheck_ids'] == []
    audit = db.query(ShippingOperationEvent).filter_by(action='selective_recheck_recovered').one()
    assert audit.payload['history_id'] == history.id


def test_wrong_submission_version_does_not_persist_recovery(db, legacy):
    user, inspection, event, _, _ = legacy
    original = deepcopy(event.result)
    db.add_all([ShippingInspectionPhoto(inspection_id=inspection.id, item_id=key, file_path='new.jpg')
                for key in ('LOCAL2', None)])
    db.commit()
    with pytest.raises(ValueError, match='撤回更新'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id, edit_version=1)
    assert event.result == original
    assert db.query(ShippingOperationEvent).filter_by(action='selective_recheck_recovered').count() == 0


def test_legacy_item_requirement_collapses_to_whole_photo(db, caught_up):
    user, event = caught_up
    inspection = ShippingInspection(outbound_record_id='OB001', status='draft', created_by=user.id)
    db.add(inspection)
    db.flush()
    event.result = {**event.result, 'required_recheck_ids': ['okki:701']}
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, item_id='LOCAL1', file_path='new.jpg'))
    db.commit()
    assert state.evidence(db, 'OB001')[1] == ['__whole__']
    with pytest.raises(ValueError, match='整单'):
        service.submit(db, outbound_record_id='OB001', user_id=user.id)
    db.add(ShippingInspectionPhoto(inspection_id=inspection.id, item_id=None, file_path='whole.jpg'))
    db.commit()
    assert service.submit(db, outbound_record_id='OB001', user_id=user.id).status == 'submitted'


def test_recreated_same_product_line_inherits_photo_without_new_evidence():
    old = [line(701, 100)]
    after = [line(702, 101)]
    plan = dict(before={'record_list': old}, material_order_ids=['101'],
                removed_order_ids=['100'], remark_changed=False)
    links = [dict(local_item_id='LOCAL1', remote_item_id=701)]
    stale, required = recheck.changes(plan, {'record_list': after}, links,
                                     [media(1, 'LOCAL1'), media(2, None)], {})
    assert stale == [] and required == []


def test_recreated_product_with_changed_quantity_still_needs_fresh_evidence():
    old = [line(701, 100, count=2)]
    after = [line(702, 101, count=1)]
    plan = dict(before={'record_list': old}, material_order_ids=['101'],
                removed_order_ids=['100'], remark_changed=False)
    links = [dict(local_item_id='LOCAL1', remote_item_id=701)]
    stale, required = recheck.changes(plan, {'record_list': after}, links,
                                     [media(1, 'LOCAL1'), media(2, None)], {})
    assert stale == [1, 2]
    assert required == ['__whole__']


@pytest.mark.parametrize('after_sku', [110, 999])
def test_recreated_line_requires_same_product_and_sku_identity(after_sku):
    old = [line(701, 100)]
    after = [line(702, 101, sku_id=after_sku)]
    plan = dict(before={'record_list': old}, material_order_ids=['101'],
                removed_order_ids=['100'], remark_changed=False)
    links = [dict(local_item_id='LOCAL1', remote_item_id=701)]
    stale, required = recheck.changes(plan, {'record_list': after}, links,
                                     [media(1, 'LOCAL1'), media(2, None)], {})
    if after_sku == 110:
        assert stale == [] and required == []
    else:
        assert stale == [1, 2] and required == ['__whole__']


def test_duplicate_same_product_rows_are_not_guessed():
    old = [line(701, 100), line(703, 102)]
    after = [line(702, 101)]
    plan = dict(before={'record_list': old}, material_order_ids=['101'],
                removed_order_ids=['100', '102'], remark_changed=False)
    links = [dict(local_item_id='LOCAL1', remote_item_id=701),
             dict(local_item_id='LOCAL2', remote_item_id=703)]
    stale, required = recheck.changes(plan, {'record_list': after}, links,
                                     [media(1, 'LOCAL1'), media(2, 'LOCAL2'), media(3, None)], {})
    assert stale == [1, 2, 3]
    assert required == ['__whole__']


def test_already_stale_photo_is_not_revived_by_a_recreated_line():
    old = [line(701, 100)]
    after = [line(702, 101)]
    plan = dict(before={'record_list': old}, material_order_ids=['101'],
                removed_order_ids=['100'], remark_changed=False)
    links = [dict(local_item_id='LOCAL1', remote_item_id=701)]
    stale, required = recheck.changes(plan, {'record_list': after}, links,
                                     [media(1, 'LOCAL1'), media(2, None)],
                                     {'stale_media_ids': [1]})
    assert stale == [1, 2]
    assert required == ['__whole__']
