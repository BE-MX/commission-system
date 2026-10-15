"""Actual JWT/ASGI/owned MySQL inventory gates; supplier reads controlled."""
from sqlalchemy.orm import Session
from app.invoice import shipment_inventory_service as inventory
from app.invoice.models import InvoiceItem
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, body_for, authorize, path, snapshot, created  # noqa: F401
import pytest


def url(c):return f'/api/invoices/{c.invoice_id}/shipment-inventory'


def setup(client,c):
    root=login(client,c,c.root_name);authorize(client,c,root)
    return root,login(client,c,c.owner_name)


def test_live_stock_read_no_business_writes_and_replay_bypasses_current_stock(shipment_app,monkeypatch):
    c=shipment_app
    with c.app.client() as client:
        root,owner=setup(client,c);before=snapshot(c)
        result=client.get(url(c),headers=owner)
        assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
        assert result.json()['data']['items'][0]['available_stock']=='100' and snapshot(c)==before
        body=body_for(client,c,owner,payment=False);response=client.post(path(c),headers=owner,json=body);created(c,body,response)
        before=snapshot(c)
        def forbidden(*_a,**_k):raise AssertionError('Replay must not query new stock')
        monkeypatch.setattr(inventory,'observe',forbidden)
        replay=client.post(path(c),headers=owner,json=body)
        assert replay.status_code==200 and replay.json()['data']['id']==response.json()['data']['id'] and snapshot(c)==before


def test_create_rechecks_decreased_stock_without_any_financial_writes(shipment_app):
    c=shipment_app
    with c.app.client() as client:
        _,owner=setup(client,c);body=body_for(client,c,owner,payment=False);before=snapshot(c);c.stock='3'
        result=client.post(path(c),headers=owner,json=body)
        assert result.status_code==409 and '可用库存' in result.text and snapshot(c)==before and c.calls==[]
        c.stock='99'  # New stock is sufficient; unchanged financial quote remains valid.
        created(c,body,client.post(path(c),headers=owner,json=body))


@pytest.mark.parametrize('phase',['read','quote','create'])
def test_revocation_during_unlocked_stock_read_rechecks_authority(shipment_app,monkeypatch,phase):
    c=shipment_app
    with c.app.client() as client:
        root,owner=setup(client,c);body=body_for(client,c,owner,payment=False);before=snapshot(c)
        original=inventory.observe
        def revoked(*args,**kwargs):
            change_user(client,c,root,{'is_active':False})
            return original(*args,**kwargs)
        monkeypatch.setattr(inventory,'observe',revoked)
        result=(client.get(url(c),headers=owner) if phase=='read' else
            client.post(path(c) if phase=='create' else f'/api/invoices/{c.invoice_id}/shipment-quotes',headers=owner,
                json=body if phase=='create' else {'items':body['items'],'freight_amount':'20.00'}))
        assert result.status_code==403 and result.headers['cache-control']=='private, no-store'
        assert snapshot(c)==before and c.calls==[]


def test_same_sku_lines_aggregate_and_unknown_fails_closed(shipment_app,monkeypatch):
    c=shipment_app
    with c.app.client() as client:
        _,owner=setup(client,c)
        with Session(c.ctx.engine) as db:
            row=InvoiceItem(invoice_id=c.invoice_id,product_id=1,sku_id=2,xiaoman_unique_id='102',
                product_name='same SKU',quantity=10,total_price=100,price_per_piece=10)
            db.add(row);db.commit();second=row.id
        c.stock='6';before=snapshot(c)
        draft={'items':[{'invoice_item_id':c.item_id,'quantity':4},{'invoice_item_id':second,'quantity':3}],'freight_amount':'0'}
        response=client.post(f'/api/invoices/{c.invoice_id}/shipment-quotes',headers=owner,json=draft)
        assert response.status_code==409 and '合计超过' in response.text and snapshot(c)==before
        def denied(*a,**kw):raise inventory.okki_client.OkkiApiError('denied')
        monkeypatch.setattr(inventory.okki_client,'fetch_token',denied)
        result=client.get(url(c),headers=owner)
        assert result.status_code==200 and all(row['available_stock'] is None for row in result.json()['data']['items'])
        assert snapshot(c)==before
