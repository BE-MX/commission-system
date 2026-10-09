"""Lost HTTP responses recover committed requests even after quotation expiry."""
import asyncio
from datetime import timedelta
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.portal import auth_service as auth, order_service, quote_service, router
from app.portal.models import OrderRequest, Revision, RequestLine, Quote, AuditEvent, OutboxEvent


def test_http_response_loss_recovers_original_after_quote_expiry(trade, monkeypatch):
    ctx = trade
    settings = auth.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest, Revision, RequestLine, Quote, AuditEvent, OutboxEvent))
    class LoseFirstResponse(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.ASGITransport(app=app, client=('127.0.0.1', 51000))
            self.lost = None
        async def handle_async_request(self, request):
            response = await self.inner.handle_async_request(request)
            if request.method == 'POST' and request.url.path.endswith('/orders') and self.lost is None:
                await response.aread()
                assert response.status_code == 201
                self.lost = response.json()['data']
                await response.aclose()
                # The real route has returned only after its MySQL commit.
                raise httpx.ReadError('Test transport lost committed response', request=request)
            return response
        async def aclose(self):
            await self.inner.aclose()
    async def run():
        transport = LoseFirstResponse()
        headers = {'X-Real-IP':'127.0.0.1', 'Origin':settings.PORTAL_ORIGIN, 'X-Portal-CSRF':ctx.csrf,
            'Idempotency-Key':str(ctx.key), 'Cookie':router.cookie_name('session')+'='+ctx.token}
        async with httpx.AsyncClient(transport=transport, base_url=settings.PORTAL_ORIGIN, headers=headers) as client:
            with pytest.raises(httpx.ReadError, match='lost committed'):
                await client.post('/api/portal/v1/orders', json=ctx.body.model_dump(mode='json'))
            original = transport.lost
            assert original is not None and original['replayed'] is False
            with Session(ctx.engine) as db:
                orders = db.scalars(select(OrderRequest).where(OrderRequest.access_id == ctx.access_id)).all()
                assert len(orders) == 1 and orders[0].public_id == original['request_id']
                quote = db.scalar(select(Quote).where(Quote.public_id == str(ctx.body.quote_id)))
                assert quote.status == 'consumed'
                after_expiry = quote.expires_at + timedelta(seconds=1)
            baseline = snapshot()
            for module in (auth, quote_service, order_service):
                monkeypatch.setattr(module, 'beijing_now', lambda: after_expiry)
            recovered = await client.get('/api/portal/v1/orders/by-key/' + str(ctx.key))
            replayed = await client.post('/api/portal/v1/orders', json=ctx.body.model_dump(mode='json'))
            assert recovered.status_code == replayed.status_code == 200
            for response in (recovered, replayed):
                assert response.json()['data'] == {**original, 'replayed':True}
                assert 'no-store' in response.headers['cache-control']
            assert snapshot() == baseline
    asyncio.run(run())