"""Repeated SKU reconciliation uses commercial identity, never row ordering."""
from copy import deepcopy
from types import SimpleNamespace
from decimal import Decimal

import pytest

from app.invoice import xiaoman_service, order_sync_execution
from tests.test_invoice_okki_push import _make_invoice, _stock_item, _seed_settings, _seed_binding


def case():
    rows = [dict(product_id=1, sku_id=11, count=5, unit_price=18.20, cost_amount=91),
            dict(product_id=1, sku_id=11, count=1, unit_price=18.21, cost_amount=18.21)]
    items = [SimpleNamespace(xiaoman_unique_id=None) for _ in rows]
    binding = [([item], row) for item, row in zip(items, rows)]
    response = [dict(rows[1], unique_id='502'), dict(rows[0], unique_id='501')]
    return SimpleNamespace(id=1), items, binding, response


def test_existing_order_reconciliation_allows_split_sku_without_relaxing_edit_send(db):
    invoice = _make_invoice(db, xiaoman_order_id='401')
    invoice.items.extend([_stock_item(quantity=5), _stock_item(sort_order=2, quantity=1)])
    db.flush()
    assert xiaoman_service._build_product_rows(db, invoice, None, editing=True)[2]
    rows, binding, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, None, editing=True, reconciling=True)
    assert not issues and len(rows) == len(binding) == 2


def test_reordered_duplicate_sku_assigns_ids_by_quantity_price_and_amount():
    invoice, items, binding, response = case()
    before = deepcopy(response)
    assert xiaoman_service._assign_unique_ids(invoice, binding, response) == 0
    assert [i.xiaoman_unique_id for i in items] == ['501', '502']
    assert response == before


def test_push_response_without_amount_matches_reversed_same_sku_prices():
    invoice, items, binding, response = case()
    for row, price in zip((binding[0][1], binding[1][1]), (35, 81.84)):
        row.update(count=1, unit_price=price, cost_amount=price)
    response = [dict(binding[1][1], unique_id='502'), dict(binding[0][1], unique_id='501')]
    for row in response:
        row.pop('cost_amount')
    assert xiaoman_service._assign_unique_ids(invoice, binding, response) == 0
    assert [item.xiaoman_unique_id for item in items] == ['501', '502']


@pytest.mark.parametrize('fault', ['extra_same_sku', 'extra_other_sku', 'missing_anchor',
    'anchor_price', 'anchor_sku', 'duplicate_uid', 'invalid_uid', 'missing_price'])
def test_incomplete_or_extra_response_never_partially_binds(fault):
    invoice, items, binding, response = case()
    binding[0][1]['unique_id'] = 501
    items[0].xiaoman_unique_id = '501'
    if fault.startswith('extra'):
        response.append(dict(response[0], unique_id='503',
                             product_id=99 if fault == 'extra_other_sku' else 1))
    elif fault == 'missing_anchor':
        response[1]['unique_id'] = '999'
    elif fault == 'anchor_price':
        response[1]['unit_price'] = 999
    elif fault == 'anchor_sku':
        response[1]['sku_id'] = 99
    elif fault == 'duplicate_uid':
        response[0]['unique_id'] = '501'
    elif fault == 'invalid_uid':
        response[0]['unique_id'] = '0'
    else:
        response[0].pop('unit_price')
    assert xiaoman_service._assign_unique_ids(invoice, binding, response) > 0
    assert [item.xiaoman_unique_id for item in items] == ['501', None]


def test_single_merged_fee_cannot_bind_old_fee_with_extra_remote_rows():
    item = SimpleNamespace(xiaoman_unique_id=None)
    row = dict(product_id=1, sku_id=11, count=1, unit_price=116.84, cost_amount=116.84)
    response = [dict(row, unique_id=str(uid), unit_price=price, cost_amount=price)
                for uid, price in [(501, 35), (502, 81.84), (503, 116.84)]]
    assert xiaoman_service._assign_unique_ids(SimpleNamespace(id=1067), [([item], row)], response) > 0
    assert item.xiaoman_unique_id is None


@pytest.mark.parametrize('with_amount', [True, False])
def test_identical_new_lines_require_full_commercial_evidence(with_amount):
    invoice, items, binding, _ = case()
    binding[1][1].update(binding[0][1])
    response = [dict(binding[0][1], unique_id=502), dict(binding[0][1], unique_id=501)]
    if not with_amount:
        for row in response: row.pop('cost_amount')
    assert (xiaoman_service._assign_unique_ids(invoice, binding, response) == 0) == with_amount
    assert [item.xiaoman_unique_id for item in items] == (['501','502'] if with_amount else [None,None])


def test_identical_lines_can_recover_after_strict_original_order_readback(db):
    from app.invoice import uncertain_recovery
    invoice = _make_invoice(db, xiaoman_order_id='401', sync_status='sync_uncertain',
                            total_amount=Decimal('85'), product_amount=Decimal('70'))
    invoice.items.extend([_stock_item(sort_order=i, quantity=1, price_per_piece=Decimal('35'),
                                     total_price=Decimal('35')) for i in (1,2)])
    db.flush()
    rows,_,issues,_ = xiaoman_service._build_product_rows(db,invoice,None,editing=True,reconciling=True)
    assert not issues
    uncertain_recovery.confirm_existing(db, invoice, '已回读原订单全部明细和总额一致', 1, evidence={
        'order_id':'401','company_id':invoice.customer_id,'currency':'USD','amount':80,
        'product_list':[dict(rows[0],unique_id=502),dict(rows[1],unique_id=501)],
    })
    assert invoice.sync_status=='not_synced'
    assert [item.xiaoman_unique_id for item in invoice.items]==['501','502']


@pytest.mark.parametrize('fault', ['missing_fields', 'wrong_quantity', 'wrong_price', 'wrong_amount'])
def test_ambiguous_or_changed_split_sku_is_not_assigned(fault):
    invoice, items, binding, response = case()
    if fault == 'missing_fields':
        response = [{k: r[k] for k in ('product_id', 'sku_id', 'unique_id')} for r in response]
    else:
        response[0][{'wrong_quantity': 'count', 'wrong_price': 'unit_price', 'wrong_amount': 'cost_amount'}[fault]] = 999
    assert xiaoman_service._assign_unique_ids(invoice, binding, response) > 0
    assert all(i.xiaoman_unique_id is None for i in items)


def test_reconciliation_keeps_known_row_identity(db):
    invoice = _make_invoice(db, xiaoman_order_id='401')
    invoice.items.extend([_stock_item(xiaoman_unique_id='501'), _stock_item(sort_order=2)])
    db.flush()
    rows, _, issues, _ = xiaoman_service._build_product_rows(
        db, invoice, None, editing=True, reconciling=True)
    assert not issues and rows[0]['unique_id'] == 501 and 'unique_id' not in rows[1]


@pytest.mark.parametrize('fault', [None, 'swapped_anchor', 'wrong_total', 'wrong_customer'])
def test_duplicate_readback_preserves_anchored_commercial_line_and_order_amount(monkeypatch, fault):
    _, _, binding, response = case()
    sent = [deepcopy(row) for _, row in binding]
    sent[0]['unique_id'] = 501
    payload = dict(company_id=7, currency='USD', name='Test', product_list=sent,
                   cost_list=[dict(percent_type=0, cost=60)])
    data = dict(order_id='401', company_id=7, currency='USD', name='Test',
                amount=169.21, product_list=response)
    if fault == 'swapped_anchor':
        response[0]['unique_id'], response[1]['unique_id'] = '501', '502'
    elif fault == 'wrong_total':
        data['amount'] = 999
    elif fault == 'wrong_customer':
        data['company_id'] = 99
    monkeypatch.setattr(order_sync_execution.okki_client, '_get_json', lambda *a, **kw: data)
    result = order_sync_execution.read_accepted_products('synthetic', SimpleNamespace(payload=payload),
                                                       dict(provider_reference='401'))
    assert ('product_list' in result) == (fault is None)


@pytest.mark.parametrize('fault', [None, 'extra_row', 'missing_amount', 'unavailable', 'token_unavailable'])
@pytest.mark.parametrize('identical', [False, True])
@pytest.mark.parametrize('whole_order_revision', [False, True])
def test_legacy_repeated_push_reads_exact_order_before_completion(db, monkeypatch, fault, identical,whole_order_revision):
    _seed_settings(db)
    _seed_binding(db)
    invoice = _make_invoice(db)
    second_price = Decimal('35' if identical else '81.84')
    invoice.items.extend([_stock_item(quantity=1, price_per_piece=Decimal('35'), total_price=Decimal('35')),
        _stock_item(sort_order=2, quantity=1, price_per_piece=second_price, total_price=second_price)])
    if whole_order_revision:
        invoice.order_type='presale'
        invoice.items.pop()
        invoice.presale_order_revision={'schema_version':1,'mode':'whole_order','sources':{},'revision':1}
    db.flush()
    monkeypatch.setattr(xiaoman_service.product_service, 'reconcile_custom_products', lambda _db: {})
    monkeypatch.setattr(xiaoman_service.get_settings(), 'OKKI_OUTBOUND_AUTO_ENABLED', True)
    monkeypatch.setattr(xiaoman_service.outbound_task_service, 'enqueue_outbound_task',
                        lambda *_a: enqueue.append(1))
    sends, reads, enqueue = [], [], []
    def push(_db, payload, **kwargs):
        sends.append(deepcopy(payload))
        return {'order_id':401, 'product_list':[
            {k:v for k,v in dict(row,unique_id=501+i).items() if k!='cost_amount'}
            for i,row in reversed(list(enumerate(payload['product_list'])))]}
    def read(*_a, **_kw):
        reads.append(1)
        if fault == 'unavailable':
            raise xiaoman_service.okki_client.OkkiApiError('read unavailable')
        payload=sends[0]
        rows=[dict(row,unique_id=501+i) for i,row in reversed(list(enumerate(payload['product_list'])))]
        if fault == 'extra_row': rows.append(dict(rows[0],unique_id=999))
        if fault == 'missing_amount': rows[0].pop('cost_amount')
        return dict(order_id=401,company_id=payload['company_id'],currency='USD',name=payload['name'],
                    amount=Decimal('45')+(0 if whole_order_revision else second_price),product_list=rows)
    def token(_db):
        if fault=='token_unavailable': raise xiaoman_service.okki_client.OkkiApiError('auth unavailable')
        return 'synthetic'
    monkeypatch.setattr(xiaoman_service.okki_client,'push_order',push)
    monkeypatch.setattr(xiaoman_service.okki_client,'ensure_access_token',token)
    monkeypatch.setattr(xiaoman_service.okki_client,'_get_json',read)
    result=xiaoman_service.sync_invoice(db,invoice,operator_id=1)
    assert len(sends)==1 and len(reads)==(0 if fault=='token_unavailable' else 1)
    assert result['ok']==(fault is None)
    if fault is None:
        assert [item.xiaoman_unique_id for item in invoice.items]==(['501'] if whole_order_revision else ['501','502'])
        assert enqueue==([] if whole_order_revision else [1])
        if whole_order_revision:assert invoice.presale_order_revision['synced_projection']['501']['amount']=='35.00'
    else:
        assert invoice.sync_status=='sync_uncertain' and invoice.xiaoman_order_id=='401'
        assert all(item.xiaoman_unique_id is None for item in invoice.items)
        assert not enqueue
        assert not xiaoman_service.sync_invoice(db,invoice,operator_id=1)['ok']
        assert len(sends)==1
        if whole_order_revision:assert 'synced_projection' not in invoice.presale_order_revision


@pytest.mark.parametrize('complete',[False,True])
def test_modern_non_repeated_revision_reads_full_amount_before_finalization(db,monkeypatch,complete):
    from types import SimpleNamespace
    attempt=SimpleNamespace(payload={'product_list':[{'product_id':1,'sku_id':11}]},
        data={'requires_commercial_readback':True})
    post={'order_id':'401','product_list':[{'product_id':1,'sku_id':11,'unique_id':'501','count':1,'unit_price':35}]}
    observation={'result_class':'accepted','provider_reference':'401'}
    monkeypatch.setattr(order_sync_execution,'prepare',lambda *a:(None,attempt.payload))
    monkeypatch.setattr(order_sync_execution,'token',lambda *a:'synthetic')
    monkeypatch.setattr(order_sync_execution,'claim',lambda *a:attempt)
    monkeypatch.setattr(order_sync_execution,'send',lambda *a:(observation,post))
    calls=[]
    def read(*a):
        calls.append('GET')
        return {'order_id':'401','product_list':[dict(post['product_list'][0],cost_amount=35)]} if complete else {'order_id':'401'}
    monkeypatch.setattr(order_sync_execution,'read_accepted_products',read)
    def persist(*a,**kw):
        if kw.get('finish') is False:
            calls.append('accepted');return
        calls.append('finalize')
        assert calls==['accepted','GET','finalize']
        return {'ok':bool(a[-1].get('product_list'))}
    monkeypatch.setattr(order_sync_execution,'persist',persist)
    monkeypatch.setattr(order_sync_execution,'response',lambda *a:a[-1])
    result=order_sync_execution.run(db,1,None,follow_outbound=False)
    assert result['ok']==complete
