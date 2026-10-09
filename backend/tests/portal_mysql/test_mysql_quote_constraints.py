"""Invalid price sources and split quantities cannot create customer quotes."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.invoice.models import StdPrice
from app.portal import auth_service as auth, pricing, router
from app.portal.models import (CatalogItem, Quote, OrderRequest, Revision, RequestLine,
    CommandReceipt, AuditEvent, OutboxEvent)


def client_app(ctx, monkeypatch):
    settings = auth.get_settings(); settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router,'get_settings',lambda:settings)
    app = FastAPI(); app.include_router(router.router,prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',51000)),
        base_url=settings.PORTAL_ORIGIN,headers={'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,
            'Cookie':router.cookie_name('session')+'='+ctx.token,'X-Portal-CSRF':ctx.csrf})


def snapshot(ctx):
    with Session(ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (Quote,OrderRequest,Revision,RequestLine,CommandReceipt,AuditEvent,OutboxEvent))


def test_bad_database_prices_and_excess_precision_never_fallback(trade, monkeypatch):
    ctx = trade
    with Session(ctx.engine) as db:
        source = db.scalar(select(StdPrice).where(StdPrice.series_grade == 'Standard Straight'))
        source_id = source.id
        original = {'price':source.price,'currency':source.currency,'length':source.length}
    async def run():
        async with client_app(ctx,monkeypatch) as client:
            positive = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
            assert positive.status_code == 201 and positive.json()['data']['items'][0]['unit_price'] == '27.0000'
            baseline = snapshot(ctx)
            for changes in ({'length':'99'}, {'price':Decimal('0')}, {'price':Decimal('-1')}, {'currency':'EUR'}):
                try:
                    with Session(ctx.engine) as db:
                        row = db.get(StdPrice,source_id)
                        for field,value in changes.items(): setattr(row,field,value)
                        db.commit()
                    detail = await client.get('/api/portal/v1/catalog/'+ctx.item_id)
                    assert detail.status_code == 200
                    assert detail.json()['data']['unit_price'] is None and detail.json()['data']['price_status'] == 'unavailable'
                    response = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
                    assert response.status_code == 503 and response.json()['data']['error_code'] == 'PRICE_UNAVAILABLE'
                    assert snapshot(ctx) == baseline
                finally:
                    with Session(ctx.engine) as db:
                        row = db.get(StdPrice,source_id)
                        for field,value in original.items(): setattr(row,field,value)
                        db.commit()
            # MySQL price columns store four places. Inject excessive precision at
            # the source resolver boundary rather than claiming it persisted as-is.
            for field in ('standard_price','customer_price'):
                invalid = {'standard_price':Decimal('30.0000'),'customer_price':Decimal('27.0000'),'currency':'USD'}
                invalid[field] = Decimal('27.00001')
                with monkeypatch.context() as scoped:
                    scoped.setattr(pricing.price_service,'resolve_price',lambda *a,**kw:invalid)
                    response = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
                    assert response.status_code == 503 and response.json()['data']['error_code'] == 'PRICE_UNAVAILABLE'
                    assert snapshot(ctx) == baseline
            positive = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
            assert positive.status_code == 201 and positive.json()['data']['product_amount'] == '81.00'
    asyncio.run(run())


def test_duplicate_sku_moq_step_and_total_quantity_are_enforced(trade, monkeypatch):
    ctx = trade
    with Session(ctx.engine) as db:
        source = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        source.min_qty = 4; source.step_qty = 2; source.row_version += 1; db.commit()
        values = {column.name:deepcopy(getattr(source,column.name)) for column in CatalogItem.__table__.columns
            if column.name not in {'id','public_id','created_at','updated_at'}}
        values['display_name'] = 'Same SKU under another display'
        db.add(CatalogItem(**values))
        with pytest.raises(IntegrityError) as caught: db.flush()
        assert caught.value.orig.args[0] == 1062 and 'uq_op_catalog_sku' in str(caught.value.orig)
        db.rollback()
    async def run():
        async with client_app(ctx,monkeypatch) as client:
            baseline = snapshot(ctx)
            for quantity in (0,True,4.0,'4',2,5,52):
                body = ctx.quote_body.model_dump(mode='json'); body['items'][0]['quantity'] = quantity
                response = await client.post('/api/portal/v1/quotes',json=body)
                expected = 409 if quantity == 52 else 422
                assert response.status_code == expected
                assert response.json()['data']['error_code'] == ('STOCK_CHANGED' if quantity == 52 else 'INVALID_INPUT')
                assert snapshot(ctx) == baseline
            # Two individually available rows (30 each) would exceed stock (50)
            # if duplicate item IDs were not rejected before row validation.
            body = ctx.quote_body.model_dump(mode='json')
            body['items'] = [{'item_id':ctx.item_id,'quantity':30},{'item_id':ctx.item_id,'quantity':30}]
            response = await client.post('/api/portal/v1/quotes',json=body)
            assert response.status_code == 422 and response.json()['data']['error_code'] == 'INVALID_INPUT'
            assert snapshot(ctx) == baseline
            body['items'] = [{'item_id':ctx.item_id,'quantity':50}]
            positive = await client.post('/api/portal/v1/quotes',json=body)
            assert positive.status_code == 201
            item = positive.json()['data']['items'][0]
            assert item['quantity'] == 50 and item['min_order_qty'] == 4 and item['step_qty'] == 2
            assert item['line_amount'] == '1350.00'
    asyncio.run(run())