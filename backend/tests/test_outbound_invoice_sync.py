"""Isolated SQLite and fake OKKI only; no shared database or network writes."""
from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy import text
from app.invoice.models import InvoiceItem
from app.invoice import lifecycle_guard, okki_client
from app.invoice.xiaoman_service import _build_product_rows as build_product_rows
from app.shipping_inspection import outbound_sync_service as sync, outbound_sync_state as state
from app.shipping_inspection import outbound_sync_plan as plans, outbound_service, service
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection
from tests.test_outbound_delete import case, BASE
from tests.test_shipping_inspection import _pc_client, _user, _bind_okki, outbound_scope_seed, product_display_source

PERMS = ['shipping_inspection:read', 'shipping_inspection:write', 'shipping_inspection:read_all', 'invoice:sync', 'invoice:read_all']


@pytest.fixture
def sync_case(db, case, monkeypatch):
    user, inv, task, _ = case
    inv.status = inv.sync_status = 'synced'
    inv.remark = 'new note'
    item = InvoiceItem(invoice_id=inv.id, sort_order=1, product_id=22, sku_id=220,
        product_name='Weft/22/#1006/60g', product_display='Weft', length='22', color='#1006',
        quantity=2, price_per_piece=Decimal('120.27'), total_price=Decimal('240.54'), xiaoman_unique_id='100')
    db.add(item)
    db.commit()
    old = dict(outbound_record_id=701, order_id=123, order_record_id=100, product_id=18, sku_id=180,
        outbound_count=1, sale_price=81.84, product_name='Weft/18/#1006/60g', product_model='Weft',
        product_cn_name='', product_unit='Piece', cost_unit_price_rmb='0', sku_code='18')
    order = dict(order_id=123, company_id='C1', currency='USD', update_time='2026-09-23 09:00:00',
        create_time='2026-09-23 08:00:00', product_list=[dict(unique_id=100, product_id=22, sku_id=220,
        count=2, unit_price=120.27, product_name=item.product_name, unit='Piece', product_model='Weft')])
    outbound = dict(outbound_invoice_id=77, serial_id='CK2026001', status=1, company_info={'id': 'C1'},
        currency='USD', handler_info=[{'user_id':'9001', 'nickname':'Test owner'}], invoice_warehouse_info={'id':1},
        remark='old note', update_time='2026-09-23 08:00:00', record_list=[old])
    fake = dict(order=order, outbound=outbound, posts=[], timeout=False, reject=False)

    def read(db, path, params):
        return deepcopy(fake['outbound'] if path.endswith('outbound/info') else fake['order'])

    def post(path, token, payload, **kwargs):
        assert path == '/v1/invoices/outbound/push' and 'status' not in payload
        event = db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE).one()
        assert event.action == 'sync_sending'
        fake['posts'].append(deepcopy(payload))
        if fake['reject']:
            raise okki_client.OkkiApiError('unknown')
        rows = {r['outbound_record_id']: r for r in fake['outbound']['record_list']}
        for patch in payload['record_list']:
            if patch.get('remove'):
                # OKKI validates mandatory fields even on a removal row.
                assert all(patch.get(key) is not None for key in ('outbound_count', 'sale_price', 'product_id', 'sku_id'))
                rows.pop(patch['outbound_record_id'])
            else:
                identity = patch.get('outbound_record_id', 800 + len(rows))
                rows[identity] = {**rows.get(identity, {}), **patch, 'outbound_record_id': identity, 'sku_code': str(patch['product_id']), 'cost_unit_price_rmb': '0'}
        fake['outbound'].update(record_list=list(rows.values()), remark=payload['remark'], update_time='2026-09-23 10:00:00')
        if fake['timeout']:
            raise okki_client.OkkiApiError('timeout')
        return {'outbound_invoice_id':77}

    monkeypatch.setattr(sync.remote, 'read', read)
    monkeypatch.setattr(sync.okki_client, 'ensure_access_token', lambda db: 'test')
    monkeypatch.setattr(sync.okki_client, 'get_outbound_info', lambda *args: deepcopy(fake['outbound']))
    monkeypatch.setattr(sync.okki_client, '_post_json', post)
    monkeypatch.setattr(sync.linked_outbound_service, 'find_related', lambda *args: [deepcopy(fake['outbound'])])
    monkeypatch.setattr(sync.xiaoman_service, 'get_settings_row', lambda db: None)
    def products(db, invoice, settings, **kwargs):
        bindings = [([i], {'unique_id':int(i.xiaoman_unique_id), 'product_id':i.product_id,
            'sku_id':i.sku_id, 'count':i.quantity, 'unit_price':float(i.price_per_piece)}) for i in invoice.items]
        return [r for _, r in bindings], bindings, [], []
    monkeypatch.setattr(sync.xiaoman_service, '_build_product_rows', products)
    return user, inv, item, fake


def test_sync_updates_original_line_quantity_price_remark_and_prints_before_mirror_catches_up(db, sync_case):
    user, inv, item, fake = sync_case
    with _pc_client(db, user, PERMS) as client:
        preview = client.post(f'{BASE}/OB001/invoice-sync/preview')
        assert preview.status_code == 200, preview.text
        data = preview.json()['data']
        assert data['changes'][0]['after']['quantity'] == 2
        response = client.post(f'{BASE}/OB001/invoice-sync', json={'expected_version':data['version']})
        assert response.status_code == 200, response.text
        assert response.json()['data']['status'] == 'sync_done'
        printed = client.get(f'{BASE}/OB001/print-data')
        assert printed.status_code == 200, printed.text
        assert printed.json()['data']['items'][0]['size'] == '22'
        assert printed.json()['data']['record']['remark'] == 'new note'
    assert len(fake['posts']) == 1
    assert fake['outbound']['record_list'][0]['outbound_record_id'] == 701
    assert fake['outbound']['status'] == 1
    with pytest.raises(ValueError, match='刷新'):
        service.get_or_create_draft(db, 'OB001', user.id)


@pytest.mark.parametrize('operation', ['add', 'replace', 'remove'])
def test_accessories_sync_with_hair_and_appear_in_print(db, sync_case, monkeypatch, operation):
    user, inv, _, fake = sync_case
    # Exercise the actual shared invoice builder, including accessory validation.
    monkeypatch.setattr(sync.xiaoman_service, '_build_product_rows', build_product_rows)
    validated = []
    monkeypatch.setattr(sync.xiaoman_service.accessory_price_service, 'validate_active_identity',
                        lambda db, **identity: validated.append(identity))
    if operation != 'add':
        fake['outbound']['record_list'].append(dict(
            outbound_record_id=702, order_id=123, order_record_id=102, product_id=44, sku_id=440,
            outbound_count=1, sale_price=192, product_name='hair hangers', product_model='Hangers',
            product_cn_name='', product_unit='Piece', cost_unit_price_rmb='0', sku_code='44'))
    if operation != 'remove':
        db.add(InvoiceItem(invoice_id=inv.id, sort_order=2, product_kind='accessory', item_type='stock',
            product_id=33, sku_id=330, product_name='Tool Kit', product_display='Tool Kit', color='Kit',
            quantity=2, price_per_piece=Decimal('96'), total_price=Decimal('192'), xiaoman_unique_id='102'))
        db.commit()
        fake['order']['product_list'].append(dict(unique_id=102, product_id=33, sku_id=330,
            count=2, unit_price=96, product_name='Tool Kit', unit='Piece', product_model='Tools'))
    with _pc_client(db, user, PERMS) as client:
        preview = client.post(f'{BASE}/OB001/invoice-sync/preview')
        assert preview.status_code == 200, preview.text
        data = preview.json()['data']
        change = next(c for c in data['changes'] if (c['after'] or c['before'])['name'] in ('Tool Kit', 'hair hangers'))
        assert change['action'] == {'add': '新增', 'replace': '修改', 'remove': '删除'}[operation]
        applied = client.post(f'{BASE}/OB001/invoice-sync', json={'expected_version': data['version']})
        assert applied.status_code == 200 and applied.json()['data']['status'] == 'sync_done'
        printed = client.get(f'{BASE}/OB001/print-data')
        assert printed.status_code == 200, printed.text
        items = printed.json()['data']['items']
    assert len(fake['posts']) == 1
    assert any(r['product_name'] == 'Weft/22/#1006/60g' for r in items)
    assert not any(r['product_name'] == 'hair hangers' for r in items)
    accessories = [r for r in items if r['product_kind'] == 'accessory']
    if operation == 'remove':
        assert not accessories and not validated
    else:
        assert len(accessories) == 1
        assert accessories[0]['product_name'] == 'Tool Kit' and accessories[0]['qty'] == 2
        actual = next(r for r in fake['outbound']['record_list'] if r['order_record_id'] == 102)
        assert actual['product_id'] == 33 and actual['sku_id'] == 330 and actual['sale_price'] == 96
        assert validated and all(v == {'product_id': 33, 'sku_id': 330} for v in validated)
        if operation == 'replace':
            assert actual['outbound_record_id'] == 702


def test_stale_preview_never_posts(db, sync_case):
    user, inv, item, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    before = sync.preview(db, record, actor)
    fake['outbound']['remark'] = 'warehouse changed'
    with pytest.raises(ValueError, match='重新预览'):
        sync.synchronize(db, record, actor, before['version'])
    assert not fake['posts']


@pytest.mark.parametrize('block', ['shipped', 'inspection', 'split', 'unsynced', 'order_changed', 'duplicate'])
def test_unsafe_states_never_post(db, sync_case, monkeypatch, block):
    user, inv, item, fake = sync_case
    if block == 'shipped': fake['outbound']['status'] = 2
    if block == 'inspection': db.add(ShippingInspection(outbound_record_id='OB001', status='draft', created_by=user.id))
    if block == 'split': monkeypatch.setattr(sync.linked_outbound_service, 'find_related', lambda *args: [fake['outbound'], {'outbound_invoice_id':88}])
    if block == 'unsynced': inv.sync_status = 'not_synced'
    if block == 'order_changed': fake['order']['product_list'][0]['count'] = 9
    if block == 'duplicate': fake['outbound']['record_list'].append(deepcopy(fake['outbound']['record_list'][0]))
    db.commit()
    with _pc_client(db, user, PERMS) as client:
        response = client.post(f'{BASE}/OB001/invoice-sync/preview')
        assert response.status_code == 409, response.text
    assert not fake['posts']


def test_timeout_recovers_by_read_only_and_blocks_invoice_mutation(db, sync_case):
    user, inv, item, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    fake['reject'] = True
    assert sync.synchronize(db, record, actor, preview['version'])['status'] == 'sync_uncertain'
    with pytest.raises(ValueError, match='出库单'):
        lifecycle_guard.ensure_mutable(db, inv)
    assert sync.synchronize(db, record, actor, preview['version'])['status'] == 'sync_uncertain'
    assert len(fake['posts']) == 1
    patch = fake['posts'][0]['record_list'][0]
    fake['outbound']['record_list'][0].update(patch)
    fake['outbound']['remark'] = 'new note'
    fake['outbound']['update_time'] = '2026-09-23 10:00:00'
    assert sync.synchronize(db, record, actor, preview['version'])['status'] == 'sync_done'
    assert len(fake['posts']) == 1


def test_timeout_after_remote_success_is_verified_without_replay(db, sync_case):
    user, _, _, fake = sync_case
    fake['timeout'] = True
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    assert sync.synchronize(db, record, actor, preview['version'])['status'] == 'sync_done'
    assert len(fake['posts']) == 1


def test_permissions_and_invoice_scope(db, sync_case):
    user, _, _, fake = sync_case
    for missing in ('invoice:sync', 'shipping_inspection:write'):
        with _pc_client(db, user, [p for p in PERMS if p != missing]) as client:
            assert client.post(f'{BASE}/OB001/invoice-sync/preview').status_code == 403
    other = _user(db, 'sync-other')
    _bind_okki(db, other, '9001')
    with _pc_client(db, other, [p for p in PERMS if p != 'invoice:read_all']) as client:
        assert client.post(f'{BASE}/OB001/invoice-sync/preview').status_code == 404
    assert not fake['posts']


def test_plan_uses_explicit_deletion_and_preserves_existing_identity(db, sync_case):
    _, _, _, fake = sync_case
    before = fake['outbound']
    old = deepcopy(before['record_list'][0]); old.update(outbound_record_id=702, order_record_id=101)
    before['record_list'].append(old)
    new = deepcopy(fake['order']['product_list'][0]); new.update(unique_id=102, product_id=33, sku_id=330)
    fake['order']['product_list'].append(new)
    plan = plans.build(before, fake['order'], fake['order']['product_list'], '')
    assert [c['action'] for c in plan['changes']] == ['修改', '新增', '删除']
    removed = plan['payload']['record_list'][-1]
    assert removed['outbound_record_id'] == 702 and removed['remove'] == 1
    for key in ('outbound_count', 'sale_price', 'product_id', 'sku_id'):
        assert removed[key] == old[key]
    assert plan['payload']['record_list'][0]['outbound_record_id'] == 701
    assert 'outbound_record_id' not in plan['payload']['record_list'][1]
    assert plan['payload']['remark'] == ''


def test_overlay_expires_when_mirror_is_newer(db, sync_case):
    user, _, _, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    sync.synchronize(db, record, actor, preview['version'])
    assert state.overlay(db, record)
    record['mirror_updated_at'] = '2026-09-23 10:00:01'
    assert state.overlay(db, record) is None


def test_recovery_cannot_steal_prepared_sender_and_check_only_never_posts(db, sync_case, monkeypatch):
    user, _, _, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    assert sync.synchronize(db, record, actor, None, check_only=True)['requires_preview']
    original = sync.commit
    calls = 0
    def interleave(session):
        nonlocal calls
        original(session)
        calls += 1
        if calls == 1:
            assert sync.synchronize(db, record, actor, None, check_only=True)['status'] == 'sync_pending'
    monkeypatch.setattr(sync, 'commit', interleave)
    assert sync.synchronize(db, record, actor, preview['version'])['status'] == 'sync_done'
    assert len(fake['posts']) == 1


def test_uncertain_blocks_print_and_word_even_with_old_verified_overlay(db, sync_case):
    user, _, _, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    sync.synchronize(db, record, actor, preview['version'])
    event = db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE).one()
    event.action = 'sync_uncertain'
    db.commit()
    with _pc_client(db, user, PERMS) as client:
        assert client.get(f'{BASE}/OB001/print-data').status_code == 409
        assert client.get(f'{BASE}/OB001/word').status_code == 409


def test_add_delete_and_update_complete_in_one_verified_post(db, sync_case):
    user, inv, item, fake = sync_case
    obsolete = deepcopy(fake['outbound']['record_list'][0])
    obsolete.update(order_record_id=101, outbound_record_id=702)
    fake['outbound']['record_list'].append(obsolete)
    added = InvoiceItem(invoice_id=inv.id, sort_order=2, product_id=33, sku_id=330,
        product_name='Tape', product_display='Tape', color='Clear', quantity=1,
        price_per_piece=Decimal('5'), total_price=Decimal('5'), xiaoman_unique_id='102')
    db.add(added); db.commit()
    fake['order']['product_list'].append(dict(unique_id=102, product_id=33, sku_id=330,
        count=1, unit_price=5, product_name='Tape', unit='Piece', product_model='Tape'))
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    assert [c['action'] for c in preview['changes']] == ['修改', '新增', '删除']
    assert sync.synchronize(db, record, actor, preview['version'])['status'] == 'sync_done'
    assert len(fake['posts']) == 1
    assert {r['order_record_id'] for r in fake['outbound']['record_list']} == {100,102}
    assert len(outbound_service.list_outbound_items(db, 'OB001')) == 2


def test_safe_auth_rejection_keeps_previous_verified_print_snapshot(db, sync_case, monkeypatch):
    user, inv, item, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    sync.synchronize(db, record, actor, preview['version'])
    item.quantity = 3; item.total_price = Decimal('360.81'); db.commit()
    fake['order']['product_list'][0]['count'] = 3
    preview = sync.preview(db, record, actor)
    monkeypatch.setattr(sync.okki_client, '_post_json', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='凭证'):
        sync.synchronize(db, record, actor, preview['version'])
    event = state.ensure_printable(db, 'OB001')
    assert event.action == 'sync_failed'
    assert state.overlay(db, record, event=event)['items'][0]['qty'] == 2


def test_print_uses_current_event_after_wait_not_cached_header(db, sync_case):
    import json
    user, _, _, fake = sync_case
    record = outbound_service.get_outbound_record(db, 'OB001')
    actor = {'sub':str(user.id), 'permissions':PERMS}
    preview = sync.preview(db, record, actor)
    sync.synchronize(db, record, actor, preview['version'])
    event = state.ensure_printable(db, 'OB001')
    prior = deepcopy(event.result)
    newer = deepcopy(prior)
    newer['verified']['remark'] = 'newer verified note'
    newer['verified']['items'][0]['qty'] = 3
    db.execute(text('UPDATE ark_shipping_operation_events SET result=:result WHERE id=:id'),
        {'result':json.dumps(newer), 'id':event.id})
    assert event.result == prior  # Cached ORM object is intentionally stale.
    current = state.ensure_printable(db, 'OB001')
    assert state.apply_header(db, record, event=current)['remark'] == 'newer verified note'
    assert outbound_service.list_outbound_items(db, 'OB001', sync_event=current)[0]['qty'] == 3
