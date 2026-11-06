"""Keep saved line identity across edits; never infer same-SKU prices by position."""
import json
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.invoice import order_sync_execution, service, xiaoman_service
from app.invoice.schemas import InvoiceUpdate
from tests.test_invoice_okki_push import _make_invoice, _stock_item


@pytest.fixture
def saved_order(db, monkeypatch):
    monkeypatch.setattr(service.product_service, 'valid_okki_product_skus', lambda db, pairs: pairs)
    monkeypatch.setattr(service.price_service, 'resolve_price', lambda *a, **kw: {
        'standard_price': None, 'customer_price': None, 'currency': 'USD',
    })
    from app.receipt import remote
    monkeypatch.setattr(remote, 'order_receipts', lambda *a: [])
    invoice = _make_invoice(db, order_type='stock', xiaoman_order_id='401',
                            sync_status='synced', status='synced')
    invoice.items.extend([
        _stock_item(quantity=50, price_per_piece=Decimal('1.40'), xiaoman_unique_id='501'),
        _stock_item(sort_order=2, quantity=50, price_per_piece=Decimal('1.38'), xiaoman_unique_id='502'),
    ])
    service._refresh_invoice_totals(invoice)
    db.commit()
    return service.get_invoice(db, invoice.id)


def edit_body(invoice):
    return InvoiceUpdate(
        invoice_no=invoice.invoice_no, customer_id=invoice.customer_id, customer_name=invoice.customer_name,
        order_type=invoice.order_type, invoice_date=invoice.invoice_date, currency=invoice.currency,
        sales_user_id=invoice.sales_user_id, shipping_fee=invoice.shipping_fee,
        surcharge_amount=invoice.surcharge_amount, okki_new_deal=0, okki_free_shipping=0, okki_first_return=0,
        items=[{k: getattr(item, k) for k in (
            'id', 'product_kind', 'item_type', 'product_id', 'sku_id', 'product_name', 'product_display',
            'net_weight_grams', 'color', 'length', 'quantity', 'price_per_piece', 'discount_amount',
        )} for item in invoice.items],
    )


def test_repeat_save_preserves_original_ids_uids_and_split_prices(db, saved_order):
    original_ids = [item.id for item in saved_order.items]
    body = edit_body(saved_order)
    for remark in ('first saved edit', 'second saved edit'):
        body.remark = remark
        service.update_invoice(db, saved_order, body)
        db.commit()
        saved_order = service.get_invoice(db, saved_order.id)
    assert [i.id for i in saved_order.items] == original_ids
    assert [i.xiaoman_unique_id for i in saved_order.items] == ['501', '502']
    assert [i.total_price for i in saved_order.items] == [Decimal('70'), Decimal('69')]
    assert not json.loads(saved_order.xiaoman_removed_lines or '[]')
    rows, _, issues, _ = xiaoman_service._build_product_rows(db, saved_order, None, editing=True)
    assert not issues
    assert [(r['unique_id'], r['unit_price']) for r in rows] == [(501, 1.4), (502, 1.38)]


@pytest.mark.parametrize('invalid_id', [999999, -1, 0])
def test_unknown_saved_id_is_rejected_instead_of_deleting_originals(db, saved_order, invalid_id):
    original = [(i.id, i.xiaoman_unique_id) for i in saved_order.items]
    body = edit_body(saved_order)
    body.items[0].id = invalid_id
    with pytest.raises(ValueError, match='明细.*已变化|明细.*不存在'):
        service.update_invoice(db, saved_order, body)
    db.rollback()
    current = service.get_invoice(db, saved_order.id)
    assert [(i.id, i.xiaoman_unique_id) for i in current.items] == original
    assert not current.xiaoman_removed_lines


def test_reorder_add_and_delete_only_marks_the_actual_removed_line(db, saved_order):
    original = {i.xiaoman_unique_id: i.id for i in saved_order.items}
    body = edit_body(saved_order)
    new = body.items[0].model_copy(update={'id': None, 'product_id': 2, 'sku_id': 9002,
                                         'quantity': 200, 'price_per_piece': Decimal('2.03')})
    body.items = [new, body.items[1]]
    service.update_invoice(db, saved_order, body)
    db.commit()
    current = service.get_invoice(db, saved_order.id)
    assert current.items[1].id == original['502']
    assert current.items[1].xiaoman_unique_id == '502'
    assert current.items[0].xiaoman_unique_id is None
    assert current.items[0].total_price == Decimal('406')
    assert [r['unique_id'] for r in json.loads(current.xiaoman_removed_lines)] == ['501']


def test_copy_does_not_steal_original_line_identity(db, saved_order):
    original = [(i.id, i.xiaoman_unique_id) for i in saved_order.items]
    body = edit_body(saved_order)
    body.items.append(body.items[0].model_copy(update={'price_per_piece': Decimal('1.39')}))
    service.update_invoice(db, saved_order, body)
    db.commit()
    current = service.get_invoice(db, saved_order.id)
    assert [(i.id, i.xiaoman_unique_id) for i in current.items[:2]] == original
    assert current.items[2].id not in {i[0] for i in original}
    assert current.items[2].xiaoman_unique_id is None
    assert current.items[2].total_price == Decimal('69.50')


def test_unbound_duplicate_sku_names_rows_and_recovery_action(db, saved_order):
    for item in saved_order.items:
        item.xiaoman_unique_id = None
    _, _, issues, _ = xiaoman_service._build_product_rows(db, saved_order, None, editing=True)
    assert len(issues) == 1
    assert '第 1、2 行' in issues[0]['message']
    assert '独立小满行号' in issues[0]['message']
    assert '恢复行号' in issues[0]['message']
    assert [i.total_price for i in saved_order.items] == [Decimal('70'), Decimal('69')]


def test_reorder_existing_lines_preserves_price_and_remote_identity(db, saved_order):
    original = [(i.id, i.xiaoman_unique_id, i.total_price) for i in saved_order.items]
    body = edit_body(saved_order)
    body.items.reverse()
    service.update_invoice(db, saved_order, body)
    assert [(i.id, i.xiaoman_unique_id, i.total_price) for i in saved_order.items] == original[::-1]
    db.commit()
    current = service.get_invoice(db, saved_order.id)
    assert [(i.id, i.xiaoman_unique_id, i.total_price) for i in current.items] == original[::-1]
    assert not current.xiaoman_removed_lines


def test_switching_custom_and_stock_clears_old_product_mapping(db, saved_order, monkeypatch):
    from app.invoice.models import CustomProduct
    custom = CustomProduct(match_key='line-identity-custom', product_display='Raw Hair',
                           product_name='Custom Hair', color='#1', size='18', unit='100g')
    db.add(custom)
    db.flush()
    monkeypatch.setattr(service.product_service, 'load_okki_rows', lambda *a, **kw: [])
    monkeypatch.setattr(service.product_service, 'ensure_custom_product', lambda *a, **kw: {
        'custom_product_id': custom.id, 'product_id': None, 'sku_id': None,
        'product_name': 'Custom Hair', 'source': 'custom',
    })
    original_id = saved_order.items[0].id
    body = edit_body(saved_order)
    body.order_type = 'production'
    body.items[0].item_type = 'custom'
    service.update_invoice(db, saved_order, body)
    db.commit()
    current = service.get_invoice(db, saved_order.id)
    assert (current.items[0].id, current.items[0].custom_product_id) == (original_id, custom.id)
    body = edit_body(current)
    body.items[0].item_type = 'stock'
    body.items[0].product_id, body.items[0].sku_id = 1, 9001
    service.update_invoice(db, current, body)
    db.commit()
    current = service.get_invoice(db, current.id)
    assert current.items[0].id == original_id
    assert current.items[0].custom_product_id is None
    assert current.items[0].xiaoman_unique_id == '501'


@pytest.mark.parametrize('issue', [
    {'field': 'items', 'message': '第 2、3 行是同一产品，缺少原小满行号'},
    {'field': 'sales_user_id', 'message': '业务员未绑定 OKKI 账号'},
    {'field': 'default_order_status', 'message': '未配置默认订单状态'},
])
@pytest.mark.parametrize('source', ['invoice', 'payload'])
def test_prepare_exposes_concrete_mapping_issue_without_sending(db, saved_order, monkeypatch, issue, source):
    monkeypatch.setattr(order_sync_execution.edit_authority, 'prepare_recovery', lambda *a: (saved_order, {'id': 1}))
    monkeypatch.setattr(order_sync_execution, 'ensure_mutable', lambda *a: None)
    monkeypatch.setattr(order_sync_execution.facts, 'unresolved', lambda *a: [])
    monkeypatch.setattr(service, 'validate_invoice', lambda *a: [issue] if source == 'invoice' else [])
    monkeypatch.setattr(xiaoman_service.product_service, 'reconcile_custom_products', lambda *a: {})
    monkeypatch.setattr(xiaoman_service, 'build_push_payload', lambda *a: (None, [], [issue]))
    with pytest.raises(HTTPException) as error:
        order_sync_execution.prepare(db, saved_order.id, {'id': 1})
    assert error.value.status_code == 409
    assert issue['message'] in error.value.detail
