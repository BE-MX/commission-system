"""HTTP login challenges hide eligibility and never authenticate an email alone."""
import asyncio
from datetime import timedelta
from uuid import UUID, uuid4
import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.portal import auth_service as auth, router
from app.portal.models import Account, OutboxEvent, PortalSession


def test_http_email_only_and_enumeration_boundary(trade, monkeypatch):
    ctx = trade
    settings = auth.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    current = auth.beijing_now() + timedelta(seconds=61)
    monkeypatch.setattr(auth, 'beijing_now', lambda: current)
    with Session(ctx.engine) as db:
        active_email = db.get(Account, ctx.account_id).email_normalized
    def counts():
        with Session(ctx.engine) as db:
            return (db.scalar(select(func.count()).select_from(PortalSession)),
                db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == 'auth_code')))
    app = FastAPI()
    app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    async def run():
        responses = []
        for index, (email, expected_mail) in enumerate(((active_email, 1), (uuid4().hex + '@example.test', 0), (active_email, 0))):
            if index == 2:
                # Keep the same verified account, membership and customer access;
                # only its status changes, so missing membership cannot mask a bug.
                with Session(ctx.engine) as db:
                    account = db.get(Account, ctx.account_id)
                    assert account.status == 'active' and account.verified_at is not None
                    account.status = 'disabled'
                    db.commit()
                monkeypatch.setattr(auth, 'beijing_now', lambda: current + timedelta(seconds=61))
            before = counts()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 51000)),
                base_url=settings.PORTAL_ORIGIN, headers={'X-Real-IP': '127.0.0.1', 'Origin': settings.PORTAL_ORIGIN}) as client:
                bootstrap = await client.get('/api/portal/v1/auth/bootstrap')
                assert bootstrap.status_code == 200
                response = await client.post('/api/portal/v1/auth/challenges', json={'email': email, 'purpose': 'login'},
                    headers={'X-Portal-CSRF': bootstrap.json()['data']['csrf_token']})
                assert response.status_code == 202
                assert 'no-store' in response.headers['cache-control']
                assert 'set-cookie' not in response.headers
                assert router.cookie_name('session') not in client.cookies
                assert email not in response.text
                value = response.json()
                UUID(value['data']['challenge_id'])
                value['data']['challenge_id'] = '<opaque>'
                responses.append(value)
                after = counts()
                assert after == (before[0], before[1] + expected_mail)
                # Both catalogue and identity routes must reject an unverified browser.
                for path in ('/catalog', '/session'):
                    protected = await client.get('/api/portal/v1' + path)
                    assert protected.status_code == 401
                    assert router.cookie_name('session') not in client.cookies
                assert counts() == after
        assert responses[0] == responses[1] == responses[2]
    asyncio.run(run())