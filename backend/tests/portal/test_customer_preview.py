from uuid import uuid4
import pytest
from sqlalchemy import func, select
from test_mapping_service import catalog, managed, portal_metadata, auth_context, body
from app.portal import mapping_service as mapping, admin_service as admin
from app.portal.errors import PortalError
from app.portal.models import MappingRevision, Quote, AuditEvent, OutboxEvent, PortalSession


def test_published_preview_is_read_only_and_scoped(catalog, monkeypatch):
    ctx, items = catalog
    mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body()); ctx.db.commit()
    counts = lambda: tuple(ctx.db.scalar(select(func.count()).select_from(model))
        for model in (MappingRevision, Quote, AuditEvent, OutboxEvent, PortalSession))
    before = counts(); version = ctx.access.row_version
    def reader(db, actor, permission):
        if permission != 'portal_mapping:read': raise PortalError('ACTION_FORBIDDEN', 'Denied', 403)
        return {'id': actor, 'roles': ['sales'], 'permissions': {'portal_mapping:read'}}
    monkeypatch.setattr(admin, 'employee_principal', reader)
    result = mapping.customer_preview(ctx.db, 1, ctx.access.public_id); ctx.db.commit()
    assert result['preview'] is True and result['mapping_version'] == 1
    assert result['items'][0]['model_name'] == 'Silk Collection'
    assert result['items'][0]['color_name'] == 'Midnight'
    assert set(result['items'][0]) == {'item_id', 'model_name', 'color_name', 'customer_sku', 'length', 'weight', 'unit'}
    assert before == counts() and ctx.access.row_version == version
    with pytest.raises(PortalError) as error: mapping.preview(ctx.db, 1, ctx.access.public_id, body(1))
    assert error.value.status == 403
    ctx.db.rollback()
    for actor, public_id in [(2, ctx.access.public_id), (1, uuid4())]:
        with pytest.raises(PortalError) as error: mapping.customer_preview(ctx.db, actor, public_id)
        assert error.value.status == 404
        ctx.db.rollback()
    items[0].status = 'disabled'; ctx.db.commit()
    result = mapping.customer_preview(ctx.db, 1, ctx.access.public_id)
    assert [row['item_id'] for row in result['items']] == [items[1].public_id]


def test_customer_preview_http_has_no_session_cookie(catalog, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import admin_router
    ctx, _ = catalog
    app = FastAPI(); app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[admin_router._require_portal_employee] = lambda: 1
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post(f'/api/portal/admin/v1/customers/{ctx.access.public_id}/preview', json={})
            assert response.status_code == 200
            assert response.json()['data']['preview'] is True
            assert 'set-cookie' not in response.headers
            assert 'no-store' in response.headers['cache-control']
    asyncio.run(run())
