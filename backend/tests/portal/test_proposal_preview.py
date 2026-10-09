from decimal import Decimal

import pytest
from sqlalchemy import func, select
from test_proposals import proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, body, propose
from app.invoice.models import StdPrice
from app.portal import proposal_preview_service as service, proposal_service, admin_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CatalogGrant, CommandReceipt, OrderRequest, OutboxEvent, Quote, RequestLine, Revision


def counts(db):
    return [db.scalar(select(func.count()).select_from(model)) for model in (Revision, RequestLine, Quote, CommandReceipt, AuditEvent, OutboxEvent)]


def test_preview_prices_current_changes_and_creates_no_records(proposing):
    ctx, order = proposing
    original_counts = counts(ctx.db)
    ctx.db.get(StdPrice, 1).price = Decimal('40')
    ctx.db.commit()
    result = service.preview(ctx.db, 1, order['request_id'], 1, body(ctx))
    ctx.db.commit()
    assert result['items'][0]['unit_price'] == '36.0000'
    assert result['product_amount'] == '108.00' and result['total_amount'] == '155.00'
    assert result['previous_product_amount'] == '81.00' and result['previous_total_amount'] is None
    assert result['changes'][0]['kind'] == 'changed' and 'unit_price' in result['changes'][0]['changed_fields']
    assert result['changes'][0]['before']['unit_price'] == '27.0000'
    assert result['requires_customer_acceptance'] and result['binding'] is False
    assert counts(ctx.db) == original_counts
    assert ctx.db.scalar(select(OrderRequest)).row_version == 1
    assert not {'price_fingerprint', 'inventory_snapshot', 'standard_snapshot', 'rule'} & result['items'][0].keys()


def test_catalog_scope_search_and_preview_added_removed_lines(proposing):
    ctx, order = proposing
    result = service.catalog(ctx.db, 1, order['request_id'], keyword='102')
    assert result['total'] == 1 and result['items'][0]['item_id'] == ctx.items[1].public_id
    assert 'unit_price' not in result['items'][0]
    preview = service.preview(ctx.db, 1, order['request_id'], 1, body(ctx, items=[{'item_id': ctx.items[1].public_id, 'quantity': 3}]))
    assert {row['kind'] for row in preview['changes']} == {'added', 'removed'}
    grant = ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == ctx.items[1].id))
    grant.status = 'disabled'; ctx.db.commit()
    assert service.catalog(ctx.db, 1, order['request_id'], keyword='102')['total'] == 0
    with pytest.raises(PortalError) as caught:
        service.preview(ctx.db, 1, order['request_id'], 1, body(ctx, items=[{'item_id': ctx.items[1].public_id, 'quantity': 3}]))
    assert caught.value.status == 404


@pytest.mark.parametrize('endpoint', ['catalog', 'preview'])
def test_other_salesperson_cannot_read_proposal_preparation(proposing, endpoint):
    ctx, order = proposing
    with pytest.raises(PortalError) as caught:
        if endpoint == 'catalog': service.catalog(ctx.db, 2, order['request_id'])
        else: service.preview(ctx.db, 2, order['request_id'], 1, body(ctx))
    assert caught.value.status == 404


def test_preview_stale_version_unavailable_inventory_and_disabled_capability(proposing):
    ctx, order = proposing
    before = counts(ctx.db)
    with pytest.raises(PortalError) as caught:
        service.preview(ctx.db, 1, order['request_id'], 9, body(ctx))
    assert caught.value.code == 'VERSION_CONFLICT'
    ctx.db.rollback(); ctx.observations = {}
    with pytest.raises(PortalError) as caught:
        service.preview(ctx.db, 1, order['request_id'], 1, body(ctx))
    assert caught.value.code == 'INVENTORY_UNAVAILABLE'
    ctx.db.rollback(); ctx.access.can_order = False; ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.catalog(ctx.db, 1, order['request_id'])
    assert caught.value.status == 403
    assert counts(ctx.db) == before


def test_preview_does_not_replace_proposal_receipt_or_customer_confirmation(proposing):
    ctx, order = proposing
    service.preview(ctx.db, 1, order['request_id'], 1, body(ctx))
    ctx.db.get(StdPrice, 1).price = Decimal('40'); ctx.db.commit()
    result = propose(ctx, order)
    row = ctx.db.scalar(select(OrderRequest))
    assert row.status == 'awaiting_customer' and row.accepted_revision_id is None
    assert ctx.db.get(Revision, row.active_revision_id).total_amount == Decimal('155.00')
    ctx.observations = {}
    replay = propose(ctx, order)
    assert replay['replayed'] and replay['original_receipt'] == result['original_receipt']
    with pytest.raises(PortalError) as caught:
        service.preview(ctx.db, 1, order['request_id'], row.row_version, body(ctx))
    assert caught.value.code == 'VERSION_CONFLICT'


def test_current_read_permission_is_required_before_price_read(proposing, monkeypatch):
    ctx, order = proposing
    original = admin_service.employee_principal
    def principal(db, actor_id, permission):
        if permission == 'portal_order:read': raise PortalError('ACTION_FORBIDDEN', 'denied', 403)
        return original(db, actor_id, permission)
    monkeypatch.setattr(admin_service, 'employee_principal', principal)
    monkeypatch.setattr(proposal_service.quote_service, 'build_lines', lambda *args: pytest.fail('unauthorized price read'))
    with pytest.raises(PortalError) as caught:
        service.preview(ctx.db, 1, order['request_id'], 1, body(ctx))
    assert caught.value.status == 403


def test_preview_http_requires_version_and_returns_private_nonbinding_result(proposing):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx, order = proposing
    app = FastAPI()
    app.include_router(router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {'sub': '1'}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            base = '/api/portal/admin/v1/orders/' + order['request_id']
            selection = await client.get(base + '/proposal-catalog', params={'page_size': 1})
            assert selection.status_code == 200 and len(selection.json()['data']['items']) == 1
            assert selection.json()['data']['total'] == 2
            assert selection.headers['cache-control'] == 'private, no-store'
            payload = body(ctx).model_dump(mode='json')
            missing = await client.post(base + '/proposal-preview', json=payload)
            assert missing.status_code == 428
            response = await client.post(base + '/proposal-preview', json=payload, headers={'If-Match': '"1"'})
            assert response.status_code == 200 and response.json()['data']['binding'] is False
            assert response.headers['cache-control'] == 'private, no-store'
            assert response.json()['data']['total_amount'] == '128.00'
            extra = await client.post(base + '/proposal-preview', json={**payload, 'unit_price': '1.0000'}, headers={'If-Match': '"1"'})
            assert extra.status_code == 422
    asyncio.run(scenario())
