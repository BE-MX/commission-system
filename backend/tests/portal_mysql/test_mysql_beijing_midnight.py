"""T52: Beijing midnight with non-Beijing application default and real MySQL session.

Application time is deterministic; no host clock/timezone is changed. MySQL uses
real UTC/-07 session settings. Upstream inventory and invoice numbering remain
trade fixture boundaries; schema is thin upstream plus real portal migrations.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core import time as platform_time
from app.core.database import get_db
from app.invoice.models import Invoice
from app.portal import (auth_service as auth, quote_service, order_service, order_queries,
    proposal_service, proposal_decisions, approval_service, router)
from app.portal.models import (AuditEvent, OrderRequest, OutboxEvent, PortalSession,
    Quote, Revision, Site)
from app.portal.schemas import SubmitInput, AcceptInput, ApproveInput, SitePolicy
from app.auth import utils as jwt_utils
from test_mysql_decision_recovery import proposal_body
from test_mysql_notification_process import BUSINESS


@pytest.fixture(params=[('UTC', '+00:00'), ('America/Los_Angeles', '-07:00')])
def boundary_clock(request, monkeypatch):
    clock = SimpleNamespace(before=datetime(2026, 10, 5, 23, 59, 59),
        after=datetime(2026, 10, 6, 0, 0, 1), zone=request.param[0], db_zone=request.param[1])
    clock.current = clock.before
    class DefaultServerClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.current.replace(tzinfo=platform_time.BEIJING_TIMEZONE)
            return value.astimezone(tz) if tz is not None else value.astimezone(ZoneInfo(clock.zone)).replace(tzinfo=None)
    monkeypatch.setattr(platform_time, 'datetime', DefaultServerClock)
    clock.default_now = lambda: DefaultServerClock.now()
    return clock


@pytest.fixture
def midnight_trade(boundary_clock, request):
    # Explicit ordering: auth, quote and binding fixture setup must use the frozen clock too.
    ctx = request.getfixturevalue('trade')
    def database_timezone(connection, record, proxy):
        with connection.cursor() as cursor: cursor.execute('SET time_zone = %s', (boundary_clock.db_zone,))
    event.listen(ctx.engine, 'checkout', database_timezone)
    try:
        yield ctx
    finally:
        event.remove(ctx.engine, 'checkout', database_timezone)


def stored_snapshot(ctx):
    # A successful session read/replay may legitimately renew PortalSession idle expiry.
    models = tuple(model for model in BUSINESS if model is not PortalSession) + (OutboxEvent,)
    with Session(ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)).all()) for model in models)


def test_requests_replay_audit_and_pi_dates_across_beijing_midnight(midnight_trade, boundary_clock, monkeypatch, tmp_path):
    ctx, clock = midnight_trade, boundary_clock
    config = auth.get_settings(); config.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: config)
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    assert platform_time.beijing_now() == clock.before and platform_time.beijing_today() == clock.before.date()
    assert platform_time.utc_now() == clock.before.replace(tzinfo=platform_time.BEIJING_TIMEZONE).astimezone(timezone.utc)
    with Session(ctx.engine) as db:
        assert db.scalar(text('SELECT @@session.time_zone')) == clock.db_zone
        first = order_service.submit(db, ctx.token, ctx.csrf, ctx.key, ctx.body); db.commit()
        quote_before = db.scalar(select(Quote).where(Quote.public_id == str(ctx.body.quote_id)))
        minutes = SitePolicy.model_validate(db.scalar(select(Site).where(Site.code == config.PORTAL_SITE_CODE)).policy_json).quote_valid_minutes
        assert quote_before.created_at == clock.before and quote_before.expires_at == clock.before + timedelta(minutes=minutes)
        first_revision = db.scalar(select(Revision).join(OrderRequest, Revision.id == OrderRequest.active_revision_id).where(OrderRequest.public_id == first['request_id']))
        old_evidence = (first_revision.public_id, first_revision.content_hash, first_revision.created_at, first_revision.expires_at)
    expected_first_no = 'POR-20261005-' + first['request_id'].replace('-', '').upper()
    assert first['request_no'] == expected_first_no and first['submitted_at'] == clock.before.isoformat()
    clock.current = clock.after
    assert platform_time.beijing_now() == clock.after and platform_time.beijing_today() == clock.after.date()
    assert clock.default_now().date() == clock.before.date(), 'The server default date must still be yesterday'
    absolute = clock.after.replace(tzinfo=platform_time.BEIJING_TIMEZONE).astimezone(timezone.utc)
    assert platform_time.utc_now() == absolute and platform_time.utc_now_naive() == absolute.replace(tzinfo=None)
    monkeypatch.setattr(jwt_utils, 'settings', SimpleNamespace(JWT_SECRET_KEY='midnight-isolated-jwt-key'*2, JWT_ALGORITHM='HS256', JWT_EXPIRE_MINUTES=10))
    jwt = jwt_utils.create_access_token({'sub': str(ctx.actor)})
    # Verify actual JWT signature and expiry against the deterministic protocol clock.
    from jose import jwt as jose_jwt
    class ProtocolClock(datetime):
        @classmethod
        def utcnow(cls): return platform_time.utc_now_naive()
        @classmethod
        def now(cls, tz=None):
            instant = platform_time.utc_now()
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)
    from jose.exceptions import ExpiredSignatureError
    with monkeypatch.context() as protocol:
        protocol.setattr(jose_jwt, 'datetime', ProtocolClock)
        payload = jose_jwt.decode(jwt, jwt_utils.settings.JWT_SECRET_KEY, algorithms=['HS256'])
        assert payload['iat'] == int(absolute.timestamp()) and payload['exp'] == int((absolute+timedelta(minutes=10)).timestamp())
        clock.current = clock.after + timedelta(minutes=10, seconds=1)
        with pytest.raises(ExpiredSignatureError):
            jose_jwt.decode(jwt, jwt_utils.settings.JWT_SECRET_KEY, algorithms=['HS256'])
        clock.current = clock.after
    baseline = stored_snapshot(ctx)
    with Session(ctx.engine) as db:
        sessions_before = [dict(row) for row in db.execute(select(*PortalSession.__table__.columns).order_by(PortalSession.id)).mappings()]
    async def replay_http():
        headers = {'X-Real-IP':'127.0.0.1', 'Origin':config.PORTAL_ORIGIN, 'X-Portal-CSRF':ctx.csrf,
            'Idempotency-Key':str(ctx.key), 'Cookie':router.cookie_name('session')+'='+ctx.token}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 50001)), base_url=config.PORTAL_ORIGIN, headers=headers) as client:
            responses = [await client.get('/api/portal/v1/orders/by-key/'+str(ctx.key)),
                await client.post('/api/portal/v1/orders', json=ctx.body.model_dump(mode='json'))]
            for response in responses:
                assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
                assert response.json()['data'] == {**first, 'replayed':True}
    asyncio.run(replay_http())
    assert stored_snapshot(ctx) == baseline
    with Session(ctx.engine) as db:
        sessions_after = [dict(row) for row in db.execute(select(*PortalSession.__table__.columns).order_by(PortalSession.id)).mappings()]
    expected_sessions = [dict(row) for row in sessions_before]
    for row in expected_sessions:
        if row['id'] == ctx.session_id:
            row['idle_expires_at'] = min(row['expires_at'], clock.after + timedelta(minutes=config.PORTAL_SESSION_IDLE_MINUTES))
            row['updated_at'] = clock.after
    assert sessions_after == expected_sessions, 'Replay may only renew the current session idle deadline/update time'
    with Session(ctx.engine) as db:
        first_row = db.scalar(select(OrderRequest).where(OrderRequest.public_id == first['request_id']))
        revision = db.get(Revision, first_row.active_revision_id)
        assert (revision.public_id, revision.content_hash, revision.created_at, revision.expires_at) == old_evidence
        assert first_row.created_at == first_row.submitted_at == clock.before
        quote_after = quote_service.create(db, ctx.token, ctx.csrf, ctx.quote_body); db.commit()
        second_body = SubmitInput.model_validate({**ctx.body.model_dump(mode='json'), 'quote_id':quote_after['quote_id'], 'quote_content_hash':quote_after['content_hash']})
        second = order_service.submit(db, ctx.token, ctx.csrf, uuid4(), second_body); db.commit()
        assert second['request_no'] == 'POR-20261006-' + second['request_id'].replace('-', '').upper()
        assert second['request_id'] != first['request_id'] and second['submitted_at'] == clock.after.isoformat()
        quote = db.scalar(select(Quote).where(Quote.public_id == quote_after['quote_id']))
        assert quote.created_at == clock.after and quote.expires_at == clock.after + timedelta(minutes=minutes)
        proposed = proposal_service.create(db, ctx.actor, first['request_id'], 1, proposal_body(ctx)); db.commit()
        receipt = proposed['original_receipt']
        accepted = proposal_decisions.decide(db, ctx.token, ctx.csrf, first['request_id'], receipt['revision_id'], 2,
            AcceptInput(proposal_hash=receipt['content_hash']), accept=True); db.commit()
        approval_service.approve(db, ctx.actor, first['request_id'], accepted['row_version'], ApproveInput(accepted_revision_id=receipt['revision_id'])); db.commit()
    # Fresh Session proves stored DATETIME/date, rather than a writer identity-map value.
    with Session(ctx.engine) as db:
        assert db.scalar(text('SELECT @@session.time_zone')) == clock.db_zone
        original = db.scalar(select(OrderRequest).where(OrderRequest.public_id == first['request_id']))
        next_day = db.scalar(select(OrderRequest).where(OrderRequest.public_id == second['request_id']))
        assert original.public_no == expected_first_no and original.submitted_at == original.created_at == clock.before
        assert next_day.created_at == next_day.submitted_at == clock.after
        invoice = db.get(Invoice, original.invoice_id)
        assert invoice.invoice_date == clock.after.date() and invoice.source_order_name == expected_first_no
        audits = db.scalars(select(AuditEvent).where(AuditEvent.object_public_id == original.public_id).order_by(AuditEvent.id)).all()
        assert [(row.action, row.created_at) for row in audits] == [('order.submitted',clock.before), ('order.proposed',clock.after), ('order.accepted',clock.after), ('order.invoice_created',clock.after)]
        second_audit = db.scalar(select(AuditEvent).where(AuditEvent.object_public_id == next_day.public_id, AuditEvent.action == 'order.submitted'))
        assert second_audit.created_at == clock.after
        for identifier, moment in ((original.public_id, clock.before), (next_day.public_id, clock.after)):
            message = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == identifier, OutboxEvent.event_type == 'order_submitted'))
            assert message.created_at == message.next_attempt_at == moment
        view = order_queries.customer_detail(db, ctx.token, original.public_id)
        assert view['submitted_at'] == clock.before.isoformat()
        assert view['customer_safe_timeline'] == [{'event':row.action,'at':moment.isoformat()} for row, moment in zip(audits, [clock.before, clock.after, clock.after, clock.after])]
    async def read_http():
        headers = {'X-Real-IP':'127.0.0.1', 'Cookie':router.cookie_name('session')+'='+ctx.token}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 50001)), base_url=config.PORTAL_ORIGIN, headers=headers) as client:
            results = []
            for identifier in (first['request_id'], second['request_id']):
                response = await client.get('/api/portal/v1/orders/'+identifier)
                assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
                results.append(response.json()['data'])
            listing = await client.get('/api/portal/v1/orders')
            assert listing.status_code == 200 and listing.headers['cache-control'] == 'no-store'
            return results, listing.json()['data']
    details, listing = asyncio.run(read_http())
    assert [row['submitted_at'] for row in details] == [clock.before.isoformat(), clock.after.isoformat()]
    assert details[0]['customer_safe_timeline'] == view['customer_safe_timeline']
    assert details[1]['customer_safe_timeline'] == [{'event':'order.submitted', 'at':clock.after.isoformat()}]
    assert {row['request_id'] for row in listing['items']} == {first['request_id'], second['request_id']}
    # Only synthetic, scoped customer HTTP projections; never auth cookies/JWT/credentials.
    (tmp_path/'http-time-evidence.json').write_text(json.dumps({
        'scope':'Actual ASGI HTTP projections from isolated real MySQL; synthetic upstream trade fixture',
        'server_default_zone':clock.zone, 'mysql_session_zone':clock.db_zone,
        'details':details, 'listing':listing, 'invoice_date':invoice.invoice_date.isoformat()
    }, ensure_ascii=False, indent=2), encoding='utf-8')
