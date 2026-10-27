"""Actual order POST -> existing outbound edit with production session expiry.

JWT, authority, transactions, claims and readback verification are real. Only
supplier HTTP/details and the external mirror are synthetic. Stock policy is
covered separately; this supplier fixture has no target-warehouse identity.
"""
from copy import deepcopy
from decimal import Decimal
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.invoice import edit_authority, outbound_followup_service as followup
from app.invoice.models import InvoiceItem, InvoiceSyncLog
from app.shipping_inspection import outbound_service, outbound_sync_service as sync
from app.shipping_inspection.models import ShippingOperationEvent
from test_mysql_outbound_prepare import setup
from test_mysql_order_push_execution import execute


def changed_order(editor, monkeypatch, tmp_path, change):
    original_followup = followup.safely_run
    case = setup(editor, monkeypatch, tmp_path)
    monkeypatch.setattr(followup, 'safely_run', original_followup)
    monkeypatch.setattr(outbound_service, 'get_record_by_outbound_invoice_id',
                        lambda *args, **kwargs: deepcopy(case.record))
    case.route = f'/api/invoice/invoices/{editor.invoice_id}/sync'
    case.order_posts, case.outbound_posts = [], []
    with Session(editor.ctx.engine, autoflush=False) as db:
        invoice, _ = edit_authority.prepare_recovery(db, editor.invoice_id,
                                                    {'id': editor.ctx.admin}, 'invoice:sync')
        first = invoice.items[0]
        if change == 'replace_product':
            first.product_id += 100000
            first.sku_id += 100000
            first.product_name = 'Updated grade / ' + first.product_name
            first.model = 'Updated grade'
        else:
            values = {column.name: deepcopy(getattr(first, column.name))
                      for column in InvoiceItem.__table__.columns
                      if column.name not in {'id', 'created_at', 'updated_at'}}
            values.update(product_id=first.product_id + 100000, sku_id=first.sku_id + 100000,
                          product_name='New specification / ' + first.product_name,
                          model='New specification', xiaoman_unique_id=None,
                          quantity=first.quantity - 1, total_price=first.price_per_piece * (first.quantity - 1),
                          sort_order=99)
            if change == 'replace_line':
                values.update(quantity=first.quantity, total_price=first.total_price)
                invoice.xiaoman_removed_lines = json.dumps([{
                    'unique_id': first.xiaoman_unique_id, 'product_id': first.product_id, 'sku_id': first.sku_id}])
                db.delete(first)
            else:
                assert first.quantity > 1
                first.quantity, first.total_price = 1, first.price_per_piece
            db.add(InvoiceItem(**values))
        invoice.remark = 'Latest packing instructions'
        invoice.status, invoice.sync_status = 'ready', 'not_synced'
        db.commit()

    def post(url, *, headers, json, timeout):
        if url.endswith('/order/push'):
            case.order_posts.append(deepcopy(json))
            with Session(editor.ctx.engine) as db:
                local = db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == editor.invoice_id)).all()
                products = {(str(row.product_id), str(row.sku_id)): row for row in local}
                rows = []
                for index, row in enumerate(json['product_list']):
                    if row.get('remove'):
                        continue
                    item = products[(str(row['product_id']), str(row['sku_id']))]
                    rows.append({**deepcopy(row), 'unique_id': row.get('unique_id') or str(9001 + index),
                                 'product_name': item.product_name, 'product_model': item.model or '',
                                 'product_cn_name': '', 'unit': 'Piece'})
            amount = sum((Decimal(str(row['cost_amount'])) for row in rows), Decimal(0))
            amount += sum((Decimal(str(row['cost'])) for row in json.get('cost_list', [])), Decimal(0))
            case.order.update(product_list=rows, amount=str(amount), name=json['name'],
                              update_time='2026-10-27 09:50:00')
            return httpx.Response(200, json={'code': 200, 'data': deepcopy(case.order)})
        assert url.endswith('/outbound/push')
        case.outbound_posts.append(deepcopy(json))
        rows = {str(row['order_record_id']): deepcopy(row) for row in case.outbound['record_list']}
        for index, row in enumerate(json['record_list']):
            key = str(row['order_record_id'])
            if row.get('remove'):
                rows.pop(key, None)
            else:
                rows[key] = {**rows.get(key, {'outbound_record_id': 9901 + index, 'cost_unit_price_rmb': 0}),
                             **deepcopy(row)}
        case.outbound.update(record_list=list(rows.values()), remark=json['remark'],
                             update_time='2026-10-27 09:51:00')
        return httpx.Response(200, json={'code': 200, 'data': {'outbound_invoice_id': 701}})

    monkeypatch.setattr(sync.okki_client.httpx, 'post', post)
    return case


@pytest.mark.parametrize('change', ['replace_product', 'split_quantity', 'replace_line'])
def test_order_update_reaches_original_outbound_and_verifies_all_rows(editor, monkeypatch, tmp_path, change):
    case = changed_order(editor, monkeypatch, tmp_path, change)
    before = deepcopy(case.outbound)
    response = execute(case)
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['ok'] is True and result['outbound_sync']['status'] == 'done', result
    assert len(case.order_posts) == len(case.outbound_posts) == 1
    assert str(case.order_posts[0]['order_id']) == str(case.order['order_id'])
    assert case.outbound_posts[0]['outbound_invoice_id'] == before['outbound_invoice_id']
    assert 'status' not in case.outbound_posts[0] and 'serial_id' not in case.outbound_posts[0]
    expected = {str(row['unique_id']): row for row in case.order['product_list']}
    actual = {str(row['order_record_id']): row for row in case.outbound['record_list']}
    assert set(actual) == set(expected)
    for identity, row in expected.items():
        for key in ('product_id', 'sku_id', 'product_name'):
            assert str(actual[identity][key]) == str(row[key])
        assert Decimal(str(actual[identity]['outbound_count'])) == Decimal(str(row['count']))
        assert Decimal(str(actual[identity]['sale_price'])) == Decimal(str(row['unit_price']))
    for row in before['record_list']:
        if str(row['order_record_id']) in actual:
            assert actual[str(row['order_record_id'])]['outbound_record_id'] == row['outbound_record_id']
    assert case.outbound['remark'] == 'Latest packing instructions'
    with Session(editor.ctx.engine) as db:
        event = db.scalar(select(ShippingOperationEvent).where(
            ShippingOperationEvent.scope == 'outbound-invoice-sync',
            ShippingOperationEvent.request_id == case.record['outbound_record_id']))
        assert event.action == 'sync_done' and event.result['verified']
        assert len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id == editor.invoice_id,
            InvoiceSyncLog.action == 'update', InvoiceSyncLog.success == 1)).all()) == 1


@pytest.mark.parametrize('code', [409, 503])
def test_order_success_survives_existing_outbound_preparation_failure(editor, monkeypatch, tmp_path, code):
    case = changed_order(editor, monkeypatch, tmp_path, 'replace_product')
    before = deepcopy(case.outbound)
    def reject(*args, **kwargs):
        raise HTTPException(code, '出库资料需要重新核对')
    monkeypatch.setattr(sync, 'preview', reject)
    response = execute(case)
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['ok'] is True and result['outbound_sync']['status'] == 'manual'
    assert result['outbound_sync']['message'] == '出库资料需要重新核对'
    assert len(case.order_posts) == 1 and case.outbound_posts == []
    assert case.outbound == before


def test_order_success_preserves_uncertain_outbound_without_resending(editor, monkeypatch, tmp_path):
    from test_mysql_outbound_execution import event, rows
    from app.shipping_inspection import outbound_facts
    case = changed_order(editor, monkeypatch, tmp_path, 'replace_product')
    original = sync.okki_client.httpx.post
    def post(url, **kwargs):
        if url.endswith('/outbound/push'):
            case.outbound_posts.append(deepcopy(kwargs['json']))
            raise httpx.ReadTimeout('Synthetic lost outbound response')
        return original(url, **kwargs)
    monkeypatch.setattr(sync.okki_client.httpx, 'post', post)
    response = execute(case)
    assert response.status_code == 200, response.text
    result = response.json()['data']
    assert result['ok'] is True and result['outbound_sync']['status'] == 'manual'
    assert event(case)[0] == 'sync_uncertain'
    facts = rows(case, outbound_facts.FACT)
    assert len(facts) == 1 and facts[0][2]['result_class'] == 'unknown'
    with Session(editor.ctx.engine, autoflush=False) as db:
        result = followup.safely_run(db, SimpleNamespace(id=editor.invoice_id),
                                    {'id': editor.ctx.admin}, force_authority=True)
    assert result['status'] == 'manual'
    assert event(case)[0] == 'sync_uncertain'
    assert rows(case, outbound_facts.FACT) == facts
    assert len(case.order_posts) == len(case.outbound_posts) == 1
