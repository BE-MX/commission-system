from uuid import uuid4
import pytest
from sqlalchemy import select, func
from test_quotes import quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, body
from app.portal import quote_service as service
from app.portal.errors import PortalError
from app.portal.models import Quote, CatalogGrant


@pytest.mark.parametrize('mode', ['withdrawn', 'ungranted', 'absent'])
def test_quote_marks_only_submitted_unavailable_public_ids(quoting, mode):
    ctx = quoting
    first, second = ctx.items[:2]
    unavailable_id = second.public_id
    if mode == 'withdrawn': second.status = 'disabled'
    elif mode == 'ungranted':
        ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.access_id == ctx.access.id,
            CatalogGrant.catalog_item_id == second.id)).status = 'disabled'
    else: unavailable_id = str(uuid4())
    ctx.db.commit()
    request = body(ctx, items=[{'item_id': first.public_id, 'quantity': 3}, {'item_id': unavailable_id, 'quantity': 3}])
    before = ctx.db.scalar(select(func.count()).select_from(Quote))
    with pytest.raises(PortalError) as caught:
        service.create(ctx.db, ctx.session_token, ctx.session_csrf, request)
    assert caught.value.code == 'RESOURCE_NOT_FOUND' and caught.value.status == 404
    assert caught.value.issues == [{'item_id': unavailable_id, 'code': 'ITEM_UNAVAILABLE'}]
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Quote)) == before
    result = service.create(ctx.db, ctx.session_token, ctx.session_csrf, body(ctx))
    ctx.db.commit()
    assert [row['item_id'] for row in result['items']] == [first.public_id]
    assert result['delivery']['address_line1'] == request.delivery.address_line1


def test_quote_http_delivers_safe_issues_and_recovers(quoting, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router
    ctx = quoting
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: ctx.settings)
    ctx.items[1].status = 'disabled'; ctx.db.commit()
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.8', 'Origin': ctx.settings.PORTAL_ORIGIN, 'X-Portal-CSRF': ctx.session_csrf}) as client:
            client.cookies.set('__Host-portal_session', ctx.session_token)
            request = body(ctx, items=[{'item_id': item.public_id, 'quantity': 3} for item in ctx.items[:2]])
            response = await client.post('/api/portal/v1/quotes', json=request.model_dump(mode='json'))
            assert response.status_code == 404
            assert response.json()['data']['issues'] == [{'item_id': ctx.items[1].public_id, 'code': 'ITEM_UNAVAILABLE'}]
            assert response.headers['cache-control'] == 'no-store'
            response = await client.post('/api/portal/v1/quotes', json=body(ctx).model_dump(mode='json'))
            assert response.status_code == 201, response.text
            assert len(response.json()['data']['items']) == 1
    asyncio.run(scenario())