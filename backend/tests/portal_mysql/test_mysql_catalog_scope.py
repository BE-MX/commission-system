"""Catalog authorization applies before search, facets and quote creation."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.portal import auth_service as auth, router
from app.portal.models import (CatalogItem, CatalogGrant, Quote, OrderRequest,
    Revision, CommandReceipt, AuditEvent, OutboxEvent)


def test_catalog_hidden_items_cannot_be_searched_or_quoted(trade, monkeypatch):
    ctx = trade
    settings = auth.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    hidden = []
    with Session(ctx.engine) as db:
        source = db.scalar(select(CatalogItem).where(CatalogItem.public_id == ctx.item_id))
        internal_id = source.sku_id
        for index, (status, grant_status) in enumerate((('published', None), ('draft', 'enabled'),
                ('disabled', 'enabled'), ('published', 'disabled'))):
            values = {column.name: deepcopy(getattr(source, column.name)) for column in CatalogItem.__table__.columns
                if column.name not in {'id', 'public_id', 'created_at', 'updated_at'}}
            values.update(product_id='hidden-'+str(index), sku_id='hidden-'+str(index), status=status,
                display_name='SecretModel'+str(index), color_name='SecretColor'+str(index), product_kind='accessory')
            item = CatalogItem(**values)
            db.add(item); db.flush()
            if grant_status:
                db.add(CatalogGrant(access_id=ctx.access_id, catalog_item_id=item.id, status=grant_status))
            hidden.append((item.public_id, item.display_name, item.color_name))
        db.commit()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (Quote, OrderRequest, Revision, CommandReceipt, AuditEvent, OutboxEvent))
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 51000)),
            base_url=settings.PORTAL_ORIGIN, headers={'X-Real-IP':'127.0.0.1', 'Origin':settings.PORTAL_ORIGIN,
                'X-Portal-CSRF':ctx.csrf, 'Cookie':router.cookie_name('session')+'='+ctx.token}) as client:
            assert (await client.get('/api/portal/v1/catalog/'+ctx.item_id)).status_code == 200
            assert (await client.post('/api/portal/v1/quotes', json=ctx.quote_body.model_dump(mode='json'))).status_code == 201
            baseline = snapshot()
            listing = await client.get('/api/portal/v1/catalog')
            assert listing.status_code == 200 and listing.headers['Cache-Control'] == 'no-store'
            data = listing.json()['data']
            assert data['total'] == 1 and [row['item_id'] for row in data['items']] == [ctx.item_id]
            assert data['facets'] == {'categories':['hair'], 'colors':['Black']}
            assert not {'sku_id','product_id','quantity','source_namespace'} & data['items'][0].keys()
            for identifier, model, color in hidden:
                for keyword in (model, color):
                    result = await client.get('/api/portal/v1/catalog', params={'keyword':keyword})
                    assert result.status_code == 200
                    found = result.json()['data']
                    assert found['total'] == 0 and found['items'] == []
                    assert found['facets'] == {'categories':[], 'colors':[]}
            filtered = await client.get('/api/portal/v1/catalog', params={'category':'accessory'})
            assert filtered.status_code == 200 and filtered.json()['data']['total'] == 0
            missing_detail = await client.get('/api/portal/v1/catalog/'+str(uuid4()))
            def normalized(response):
                data = response.json(); data['data'].pop('trace_id', None)
                return data
            assert missing_detail.status_code == 404
            for identifier in [row[0] for row in hidden] + [str(uuid4())]:
                detail = await client.get('/api/portal/v1/catalog/'+identifier)
                assert detail.status_code == 404 and normalized(detail) == normalized(missing_detail)
                body = ctx.quote_body.model_dump(mode='json')
                body['items'].append({'item_id':identifier, 'quantity':1})
                response = await client.post('/api/portal/v1/quotes', json=body)
                assert response.status_code == 404
                assert response.json()['data']['error_code'] == 'RESOURCE_NOT_FOUND'
                assert response.json()['data']['issues'] == [{'item_id':identifier, 'code':'ITEM_UNAVAILABLE'}]
            body = ctx.quote_body.model_dump(mode='json')
            body['items'][0]['item_id'] = internal_id
            assert (await client.post('/api/portal/v1/quotes', json=body)).status_code == 422
            assert (await client.get('/api/portal/v1/catalog/'+internal_id)).status_code == 422
            assert snapshot() == baseline
    asyncio.run(run())