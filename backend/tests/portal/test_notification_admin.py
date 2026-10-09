from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_notification_worker import notifications, source, rows, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.portal import notification_admin_service as service, notification_worker as worker, admin_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CommandReceipt, OrderRequest, OutboxEvent
from app.portal.schemas import NotificationRetryInput


@pytest.fixture
def failed(notifications):
    ctx = notifications; source(ctx)
    assert worker.run_once(ctx.factory) == 'expanded'
    row = rows(ctx)[0]
    row.status, row.attempt_count, row.last_error_code = 'dead', 8, 'MAIL_TRANSPORT_FAILED'
    ctx.event_id = row.public_id
    ctx.db.commit()
    return ctx


def command(ctx, **overrides):
    row = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == ctx.event_id))
    return NotificationRetryInput(fingerprint=service.fingerprint(row), reason='Mail service recovered', **overrides)


def count(ctx, model):
    return ctx.db.scalar(select(func.count()).select_from(model))


def test_list_is_scoped_paginated_and_excludes_auth_secrets(failed):
    ctx = failed
    ctx.db.add(OutboxEvent(event_key='auth-probe', event_type='auth_code', aggregate_public_id=ctx.order_id,
        payload_json={'token': 'never-visible'}, secret_envelope=b'secret', next_attempt_at=worker.beijing_now()))
    ctx.db.commit()
    data = service.list_events(ctx.db, 1, ctx.order_id, page_size=1)
    assert data['total'] == 2 and len(data['items']) == 1
    row = data['items'][0]
    assert row['id'] == ctx.event_id and row['retry_eligible']
    assert not {'payload_json', 'lease_token', 'secret_envelope', 'event_key'} & row.keys()
    assert 'never-visible' not in str(data) and '@' not in str(data)
    with pytest.raises(PortalError) as caught: service.list_events(ctx.db, 2, ctx.order_id)
    assert caught.value.status == 404


def test_retry_is_atomic_audited_and_replay_survives_later_delivery(failed):
    ctx = failed; body = command(ctx); key = uuid4()
    audit_before, receipt_before = count(ctx, AuditEvent), count(ctx, CommandReceipt)
    version = ctx.db.scalar(select(OrderRequest)).row_version
    first = service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, key, body)
    ctx.db.commit()
    assert not first['replayed'] and first['current']['status'] == 'pending'
    assert first['current']['attempt_count'] == 0
    assert count(ctx, AuditEvent) == audit_before + 1 and count(ctx, CommandReceipt) == receipt_before + 1
    event = ctx.db.scalar(select(AuditEvent).where(AuditEvent.action == 'notification.retry_requested'))
    assert event.safe_diff_json['previous']['attempt_count'] == 8
    ctx.db.commit()
    assert worker.run_once(ctx.factory, lambda mail: True) == 'sent'
    ctx.settings.PORTAL_NOTIFICATION_ENABLED = False
    replay = service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, key, body)
    assert replay['replayed'] and replay['original_receipt'] == first['original_receipt']
    assert replay['current']['status'] == 'sent'
    assert count(ctx, AuditEvent) == audit_before + 1 and count(ctx, CommandReceipt) == receipt_before + 1
    assert ctx.db.scalar(select(OrderRequest)).row_version == version
    with pytest.raises(PortalError) as caught:
        service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, key, body.model_copy(update={'reason': 'different'}))
    assert caught.value.code == 'IDEMPOTENCY_CONFLICT'


def test_retry_transaction_rollback_preserves_dead_task(failed):
    ctx = failed; before = count(ctx, CommandReceipt)
    service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, uuid4(), command(ctx))
    ctx.db.rollback()
    assert rows(ctx)[0].status == 'dead' and count(ctx, CommandReceipt) == before
    assert ctx.db.scalar(select(AuditEvent.id).where(AuditEvent.action == 'notification.retry_requested')) is None


@pytest.mark.parametrize('status,error', [('sent', None), ('sending', None), ('pending', None),
    ('cancelled', 'AUTHORIZATION_CHANGED'), ('dead', 'NOTIFICATION_SOURCE_INVALID')])
def test_terminal_or_active_tasks_cannot_be_resent(failed, status, error):
    ctx = failed; row = rows(ctx)[0]
    row.status, row.last_error_code = status, error; ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, uuid4(), command(ctx))
    assert caught.value.code == 'NOTIFICATION_NOT_RETRYABLE'


def test_stale_snapshot_and_disabled_mail_are_rejected(failed):
    ctx = failed; body = command(ctx)
    rows(ctx)[0].attempt_count += 1; ctx.db.commit()
    with pytest.raises(PortalError) as caught: service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, uuid4(), body)
    assert caught.value.code == 'VERSION_CONFLICT'
    ctx.settings.PORTAL_MAIL_ENABLED = False
    with pytest.raises(PortalError) as caught: service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, uuid4(), command(ctx))
    assert caught.value.code == 'NOTIFICATION_DISABLED'


def test_cross_owner_read_all_does_not_authorize_retry_and_replay_needs_live_permission(failed, monkeypatch):
    ctx = failed; body = command(ctx); key = uuid4()
    service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, key, body); ctx.db.commit()
    original = admin_service.employee_principal
    def reader(db, actor_id, permission):
        result = original(db, actor_id, permission)
        result['permissions'].add('portal_order:read_all')
        return result
    monkeypatch.setattr(admin_service, 'employee_principal', reader)
    assert service.list_events(ctx.db, 2, ctx.order_id)['total'] == 2
    with pytest.raises(PortalError) as caught: service.retry(ctx.db, 2, ctx.order_id, ctx.event_id, key, body)
    assert caught.value.status == 404
    def denied(*args): raise PortalError('ACTION_FORBIDDEN', 'denied', 403)
    monkeypatch.setattr(admin_service, 'employee_principal', denied)
    with pytest.raises(PortalError) as caught: service.retry(ctx.db, 1, ctx.order_id, ctx.event_id, key, body)
    assert caught.value.status == 403


def test_http_contract(failed):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx = failed
    app = FastAPI(); app.include_router(router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {'sub': '1'}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            base = '/api/portal/admin/v1/orders/' + ctx.order_id + '/notifications'
            listing = await client.get(base)
            assert listing.status_code == 200 and listing.headers['cache-control'] == 'private, no-store'
            body = command(ctx).model_dump(mode='json'); url = base + '/' + ctx.event_id + '/retry'
            assert (await client.post(url, json=body)).status_code == 428
            headers = {'Idempotency-Key': str(uuid4())}
            assert (await client.post(url, json={**body, 'email': 'injected@example.com'}, headers=headers)).status_code == 422
            first = await client.post(url, json=body, headers=headers)
            assert first.status_code == 200 and first.json()['data']['current']['status'] == 'pending'
            assert (await client.post(url, json=body, headers=headers)).json()['data']['replayed']
            assert (await client.get(base, params={'page_size': 101})).status_code == 422
    asyncio.run(scenario())
