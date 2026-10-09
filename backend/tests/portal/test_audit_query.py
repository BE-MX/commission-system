from uuid import uuid4

import pytest
from test_order_queries import submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.portal import audit_query_service as service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent


def test_scoped_projection_and_pagination(submitted):
    ctx, order = submitted
    request_id = order['request_id']
    ctx.db.add(AuditEvent(actor_type='employee', actor_id=1, access_id=ctx.access.id,
        object_type='order_request', object_public_id=request_id, action='order.proposed',
        before_version=1, after_version=2, reason='Freight confirmed', trace_id=str(uuid4()),
        safe_diff_json={'revision_id': str(uuid4()), 'line_count': 2, 'token': 'never-visible',
                        'invoice_id': {'password': 'never-visible'}}))
    ctx.db.add(AuditEvent(actor_type='customer', actor_id=1, access_id=ctx.access.id,
        object_type='session', object_public_id=request_id, action='auth.logout',
        reason='never-visible', trace_id=str(uuid4()), safe_diff_json={}))
    ctx.db.commit()
    result = service.list_events(ctx.db, 1, request_id, page_size=1)
    assert result['total'] == 2 and len(result['items']) == 1
    item = result['items'][0]
    assert item['actor_id'] == 1 and item['before_version'] == 1 and item['after_version'] == 2
    assert item['changes']['line_count'] == 2 and item['reason'] == 'Freight confirmed'
    assert 'never-visible' not in str(result) and 'invoice_id' not in item['changes']
    assert service.list_events(ctx.db, 1, request_id, page=2, page_size=1)['items'][0]['action'] == 'order.submitted'
    with pytest.raises(PortalError) as caught:
        service.list_events(ctx.db, 2, request_id)
    assert caught.value.status == 404
    with pytest.raises(PortalError) as caught:
        service.list_events(ctx.db, 1, uuid4())
    assert caught.value.status == 404


@pytest.mark.parametrize('value', [None, [], {'line_count': True}, {'revision_id': 'secret'},
    {'status': 'secret'}, {'line_count': -1}, {'publication_count': 2**64}])
def test_malformed_changes_are_not_exposed(value):
    assert service.safe_changes(value) == {}


def test_failure_audit_with_null_access_remains_visible(submitted):
    ctx, order = submitted
    ctx.db.add(AuditEvent(actor_type='system', access_id=None, object_type='order_request',
        object_public_id=order['request_id'], action='order.approval_failed', reason='PRICE_CHANGED',
        trace_id=str(uuid4()), safe_diff_json={'employee_id': 1}))
    ctx.db.commit()
    result = service.list_events(ctx.db, 1, order['request_id'])
    assert result['total'] == 2
    assert result['items'][0]['action'] == 'order.approval_failed'
    assert result['items'][0]['changes'] == {'employee_id': 1}


def test_related_objects_use_database_lineage_not_json_claims(submitted):
    from sqlalchemy import select
    from app.core.time import beijing_now
    from app.portal.models import Conversion, OrderRequest, OutboxEvent, Revision
    ctx, result = submitted
    order = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.scalar(select(Revision))
    conversion = Conversion(request_id=order.id, approved_revision_id=revision.id,
        operation_key=str(uuid4()), payload_hash='a'*64, status='pending', created_by=1)
    ctx.db.add(conversion)
    notification = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == order.public_id))
    unrelated = OutboxEvent(event_key=str(uuid4()), event_type='business_mail',
        aggregate_public_id=str(uuid4()), payload_json={'request_id': order.public_id}, next_attempt_at=beijing_now())
    auth_event = OutboxEvent(event_key=str(uuid4()), event_type='auth_code',
        aggregate_public_id=order.public_id, payload_json={}, next_attempt_at=beijing_now())
    ctx.db.add_all([unrelated, auth_event]); ctx.db.flush()
    expected = set()
    for kind, target, action, visible in [
        ('invoice', conversion.public_id, 'invoice.portal_withdrawn', True),
        ('notification', notification.public_id, 'notification.retry_requested', True),
        ('notification', unrelated.public_id, 'notification.retry_requested', False),
        ('notification', auth_event.public_id, 'notification.retry_requested', False),
        ('invoice', str(uuid4()), 'invoice.portal_withdrawn', False),
        ('order_request', str(uuid4()), 'order.submitted', False),
    ]:
        row = AuditEvent(actor_type='system', access_id=None, object_type=kind, object_public_id=target,
            action=action, reason='visible' if visible else 'excluded-secret', trace_id=str(uuid4()),
            safe_diff_json={'request_id': order.public_id})
        ctx.db.add(row); ctx.db.flush()
        if visible: expected.add(row.public_id)
    ctx.db.commit()
    data = service.list_events(ctx.db, 1, result['request_id'])
    assert data['total'] == 3 and expected <= {row['id'] for row in data['items']}
    assert 'excluded-secret' not in str(data)


def test_history_grant_revocation_and_current_function_permission(submitted, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import select
    from app.core.time import beijing_now
    from app.portal import admin_service
    from app.portal.models import HistoryGrant, OrderRequest
    ctx, result = submitted
    order = ctx.db.scalar(select(OrderRequest))
    grant = HistoryGrant(access_id=ctx.access.id, grantee_user_id=2, scope='order', order_request_id=order.id,
        reason='handoff', expires_at=beijing_now()+timedelta(days=1), created_by=1)
    ctx.db.add(grant); ctx.db.commit()
    assert service.list_events(ctx.db, 2, order.public_id)['total'] == 1
    grant.revoked_at = beijing_now(); ctx.db.commit()
    with pytest.raises(PortalError) as caught: service.list_events(ctx.db, 2, order.public_id)
    assert caught.value.status == 404
    def denied(*args): raise PortalError('ACTION_FORBIDDEN', 'denied', 403)
    monkeypatch.setattr(admin_service, 'employee_principal', denied)
    with pytest.raises(PortalError) as caught: service.list_events(ctx.db, 1, order.public_id)
    assert caught.value.status == 403


def test_http_audit_contract(submitted):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx, order = submitted
    app = FastAPI(); app.include_router(router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {'sub': '1'}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = '/api/portal/admin/v1/orders/' + order['request_id'] + '/audit'
            response = await client.get(url)
            assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
            assert response.json()['data']['items'][0]['action'] == 'order.submitted'
            for params in ({'page': 0}, {'page_size': 0}, {'page_size': 101}):
                assert (await client.get(url, params=params)).status_code == 422
            assert (await client.get(url, params={'page': 2})).json()['data']['items'] == []
    asyncio.run(scenario())
