"""Owned MySQL/current employee execution; provider HTTP is synthetic."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.invoice import edit_authority, lifecycle_remote, okki_client, order_push_facts as facts
from app.invoice.models import InvoiceItem, OkkiOutboundTask
from app.portal.authority import lock_authority
from app.receipt.models import ReceiptIntent
from test_mysql_order_push_execution import setup_push, execute, business
from test_mysql_order_push_recovery import recover, read_evidence


def setup_duplicates(editor, monkeypatch, tmp_path, *, read_failure=False):
    c = setup_push(editor, monkeypatch, tmp_path)
    with Session(editor.ctx.engine) as db:
        lock_authority(db)
        invoice = edit_authority.lock_document(db, editor.invoice_id)
        first = invoice.items[0]
        first.quantity, first.price_per_piece, first.total_price = 5, Decimal('18.20'), Decimal('91')
        clone = InvoiceItem(**{column.name: getattr(first, column.name) for column in first.__table__.columns
                              if column.name not in {'id', 'created_at', 'updated_at'}})
        clone.quantity, clone.price_per_piece, clone.total_price, clone.sort_order = 1, Decimal('18.21'), Decimal('18.21'), 2
        invoice.items.append(clone)
        invoice.product_amount = Decimal('109.21')
        invoice.total_amount = invoice.product_amount + (invoice.shipping_fee or 0) + (invoice.internal_accessory or 0) + (invoice.surcharge_amount or 0)
        db.commit()
    def post(url, *, headers, json, timeout):
        c.posts.append(deepcopy(json))
        # Sparse acceptance cannot safely anchor differently priced same-SKU rows.
        data = c.accepted(json)
        data['product_list'] = [{k: row[k] for k in ('product_id', 'sku_id', 'unique_id')}
                                for row in data['product_list']]
        return httpx.Response(200, json={'code': 200, 'data': data})
    monkeypatch.setattr(okki_client.httpx, 'post', post)
    c.reads = []
    def get(url, **kwargs):
        assert url.endswith('/v1/invoices/order/info')
        c.reads.append(kwargs['params'])
        if read_failure:
            raise httpx.ReadTimeout('synthetic read unavailable')
        data = read_evidence(c)
        data['name'] = c.posts[0]['name']
        data['product_list'].reverse()
        return httpx.Response(200, json={'code': 200, 'data': data})
    monkeypatch.setattr(okki_client.httpx, 'get', get)
    return c


def test_first_create_split_sku_reads_original_and_finishes_without_another_post(editor, monkeypatch, tmp_path):
    c = setup_duplicates(editor, monkeypatch, tmp_path)
    response = execute(c)
    assert response.status_code == 200 and response.json()['data']['ok'], response.text
    assert len(c.posts) == len(c.reads) == 1
    with Session(editor.ctx.engine) as db:
        invoice = edit_authority.lock_document(db, editor.invoice_id)
        assert invoice.sync_status == 'synced' and invoice.xiaoman_order_id == c.target
        assert [i.xiaoman_unique_id for i in invoice.items] == ['501', '502']
        assert facts.unresolved(db, invoice) == []


@pytest.mark.parametrize('drift', [None, 'remote_price', 'local_amount'])
def test_accepted_split_sku_recovers_original_without_post_or_outbound_task(editor, monkeypatch, tmp_path, drift):
    c = setup_duplicates(editor, monkeypatch, tmp_path, read_failure=True)
    response = execute(c)
    assert response.status_code == 200 and response.json()['data']['okki_accepted'], response.text
    with Session(editor.ctx.engine) as db:
        lock_authority(db)
        invoice = edit_authority.lock_document(db, editor.invoice_id)
        assert invoice.sync_status == 'sync_uncertain'
        assert all(i.xiaoman_unique_id is None for i in invoice.items)
        invoice.sync_attempt = {**invoice.sync_attempt, 'lease_until': (beijing_now() - timedelta(minutes=1)).isoformat()}
        intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id == invoice.id))
        intent.lease_until = beijing_now() - timedelta(minutes=1)
        db.commit()
    evidence = read_evidence(c)
    evidence['product_list'].reverse()
    if drift == 'remote_price':
        evidence['product_list'][0]['unit_price'] = 999
    def read(*args):
        if drift == 'local_amount':
            with Session(editor.ctx.engine) as changed:
                lock_authority(changed)
                edit_authority.lock_document(changed, editor.invoice_id).total_amount += 1
                changed.commit()
        return deepcopy(evidence)
    monkeypatch.setattr(lifecycle_remote, 'read', read)
    before = business(editor)
    response = recover(c, 'confirm_existing')
    assert response.status_code == (409 if drift else 200), response.text
    assert len(c.posts) == 1
    with Session(editor.ctx.engine) as db:
        invoice = edit_authority.lock_document(db, editor.invoice_id)
        assert invoice.xiaoman_order_id == c.target
        assert db.scalar(select(OkkiOutboundTask.id).where(OkkiOutboundTask.invoice_id == invoice.id)) is None
        if drift:
            assert invoice.sync_status == 'sync_uncertain'
            assert all(i.xiaoman_unique_id is None for i in invoice.items)
            if drift == 'remote_price':
                assert business(editor) == before
        else:
            assert invoice.sync_status == 'not_synced' and invoice.sync_attempt is None
            assert [i.xiaoman_unique_id for i in invoice.items] == ['501', '502']
            assert facts.unresolved(db, invoice) == []
