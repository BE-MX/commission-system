from uuid import uuid4
import pytest
from sqlalchemy import select, func, text
from test_catalog_admin import source, imported, body
from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context
from app.portal import catalog_admin_service as service
from app.portal.models import CatalogItem, AuditEvent
from app.portal.errors import PortalError


def test_source_preview_never_imports_or_invents_conversion(source):
    ctx=source
    result=service.inspect_source(ctx.db,1,product_id='101',sku_id='201',product_kind='hair')
    assert result['existing_item'] is None and result['expected_version']==0
    assert result['source']['standard_json']['price_unit']=='20g'
    assert 'conversion_factor' not in result['source']
    assert ctx.db.scalar(select(func.count()).select_from(CatalogItem))==0
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent))==0
    first=imported(ctx)
    result=service.inspect_source(ctx.db,1,product_id='101',sku_id='201',product_kind='hair')
    assert result['existing_item']['id']==first['id'] and result['expected_version']==1
    with pytest.raises(PortalError) as caught:
        service.inspect_source(ctx.db,1,product_id='101',sku_id='201',product_kind='accessory')
    assert caught.value.status==422


def test_import_recovery_and_detail_work_without_source_mirror(source):
    ctx=source
    assert service.lookup_import(ctx.db,1,product_id='101',sku_id='201')=={'found':False,'item':None}
    first=imported(ctx)
    ctx.db.execute(text('DROP TABLE okki_product_skus'));ctx.db.commit()
    assert service.lookup_import(ctx.db,1,product_id='101',sku_id='201')['item']['id']==first['id']
    assert service.get_item(ctx.db,1,first['id'])['status']=='draft'
    with pytest.raises(PortalError) as caught:
        service.get_item(ctx.db,1,uuid4())
    assert caught.value.status==404


def test_inspection_enforces_admin_and_canonical_ids(source):
    ctx=source
    for method,kwargs in [(service.inspect_source,dict(product_id='101',sku_id='201',product_kind='hair')),(service.lookup_import,dict(product_id='101',sku_id='201'))]:
        with pytest.raises(PortalError) as caught: method(ctx.db,3,**kwargs)
        assert caught.value.status==403
        ctx.db.rollback()
    for product_id in ['00101','101%','9223372036854775808']:
        with pytest.raises(PortalError) as caught: service.lookup_import(ctx.db,1,product_id=product_id,sku_id='201')
        assert caught.value.status==422
        ctx.db.rollback()


def test_admin_search_is_literal_or_exact_source_id(source):
    ctx=source;first=imported(ctx)
    for keyword in ['Straight','Natural','101','201']:
        assert service.list_items(ctx.db,1,keyword=keyword)['items'][0]['id']==first['id']
    for keyword in ['%','_','10','20']:
        assert service.list_items(ctx.db,1,keyword=keyword)['total']==0
    ctx.settings.PORTAL_SITE_CODE='other'
    with pytest.raises(PortalError): service.get_item(ctx.db,1,first['id'])


def test_import_rejects_same_identity_changed_since_source_preview(source):
    ctx=source
    preview=service.inspect_source(ctx.db,1,product_id='101',sku_id='201',product_kind='hair')
    ctx.db.commit()
    ctx.db.execute(text("UPDATE okki_products SET unit='25g'"));ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.import_item(ctx.db,1,0,body(standard_fingerprint=preview['source']['standard_fingerprint']))
    assert caught.value.code=='SKU_CHANGED'
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(CatalogItem))==0
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent))==0


def test_inspection_http_routes_and_fingerprint_required(source):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx=source
    app=FastAPI();app.include_router(router,prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db]=lambda:ctx.db
    claims={'sub':'1'}
    app.dependency_overrides[get_current_user]=lambda:claims
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            base='/api/portal/admin/v1/catalog'
            params={'product_id':'101','sku_id':'201','product_kind':'hair'}
            response=await client.get(base+'/source',params=params)
            assert response.status_code==200 and response.json()['data']['expected_version']==0
            assert 'no-store' in response.headers['cache-control']
            invalid=body().model_dump();invalid.pop('standard_fingerprint')
            assert (await client.post(base+'/import',json=invalid,headers={'If-Match':'"0"'})).status_code==422
            first=imported(ctx)
            for path,query in [(base+'/import-status',params),(base+'/'+first['id'],{}),(base,{'keyword':'101'})]:
                response=await client.get(path,params=query)
                assert response.status_code==200 and 'no-store' in response.headers['cache-control']
            assert (await client.get(base+'/import-status',params={'product_id':'01','sku_id':'201'})).status_code==422
            claims['sub']='3'
            for path,query in [(base+'/source',params),(base+'/import-status',params),(base+'/'+first['id'],{})]:
                assert (await client.get(path,params=query)).status_code==403
    asyncio.run(scenario())
