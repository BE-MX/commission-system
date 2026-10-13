"""Repeated SKU reconciliation uses commercial identity, never row ordering."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.invoice import xiaoman_service, order_sync_execution
from tests.test_invoice_okki_push import _make_invoice, _stock_item


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
