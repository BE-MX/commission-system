"""Real access administration revokes old sessions and denies new read-only writes."""
import asyncio
from datetime import timedelta
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.portal import auth_service as auth, admin_service, order_service, proposal_service, router
from app.portal.models import (Account, CustomerAccess, OrderRequest, Revision, RequestLine,
    CommandReceipt, OutboxEvent, AuditEvent, Quote)
from app.portal.schemas import CustomerUpdate, ProposalInput, ChallengeInput, VerifyInput
from app.portal.security import open_secret


@pytest.mark.parametrize('view_price', [True, False])
def test_order_capability_revocation_denies_old_and_new_session_writes(trade, monkeypatch, view_price):
    ctx = trade
    settings = auth.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    with Session(ctx.engine) as db:
        submitted = order_service.submit(db, ctx.token, ctx.csrf, ctx.key, ctx.body); db.commit()
        request_id = submitted['request_id']
        proposed = proposal_service.create(db, ctx.actor, request_id, 1, ProposalInput.model_validate({
            **ctx.quote_body.model_dump(mode='json'),
            'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
            'payment_terms':'prepaid', 'valid_for_hours':24, 'reason':'Review complete order terms'}))
        db.commit()
        revision = proposed['original_receipt']
        account_email = db.get(Account, ctx.account_id).email_normalized
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest, Revision, RequestLine, CommandReceipt, OutboxEvent, AuditEvent, Quote))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1',51000)),
            base_url=settings.PORTAL_ORIGIN, headers={'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,
                'Cookie':router.cookie_name('session')+'='+ctx.token, 'X-Portal-CSRF':ctx.csrf,
                'If-Match':chr(34)+'2'+chr(34)}) as client:
            path = '/api/portal/v1/orders/'+request_id
            before = await client.get(path)
            assert before.status_code == 200 and before.json()['data']['status'] == 'awaiting_customer'
            with Session(ctx.engine) as db:
                access = db.get(CustomerAccess, ctx.access_id)
                admin_service.update_customer(db, ctx.admin, access.public_id, access.row_version,
                    CustomerUpdate(status='enabled', capabilities={'can_order':False, 'can_view_price':view_price},
                        reason='Restrict procurement to read-only access'))
                db.commit()
            async def denied(status):
                baseline = snapshot()
                for tail, body in (
                    ('/proposals/'+revision['revision_id']+'/accept', {'proposal_hash':revision['content_hash']}),
                    ('/proposals/'+revision['revision_id']+'/reject', {'reason':'Decline proposal'}),
                    ('/cancel', {'reason':'Cancel request'})):
                    response = await client.post(path+tail, json=body)
                    assert response.status_code == status
                    assert response.json()['data']['error_code'] == ('AUTH_REQUIRED' if status == 401 else 'ACTION_FORBIDDEN')
                    assert response.headers['Cache-Control'] == 'no-store'
                assert snapshot() == baseline
            await denied(401)
            assert (await client.get(path)).status_code == 401
            # A new genuine OTP session inherits the reduced capabilities.
            clock = auth.beijing_now() + timedelta(seconds=61)
            monkeypatch.setattr(auth, 'beijing_now', lambda: clock)
            with Session(ctx.engine) as db:
                preauth, token, csrf = auth.bootstrap(db, '127.0.0.1'); db.commit()
                challenge = auth.challenge(db, auth.require_preauth(db, token, csrf),
                    ChallengeInput(email=account_email, purpose='login'), '127.0.0.1'); db.commit()
                event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge.public_id))
                code = open_secret(settings.PORTAL_MAIL_KEYS['v1'], event.secret_envelope,
                    event_key=event.event_key, purpose='login', object_id=challenge.public_id)
                principal, session, new_token = auth.verify(db, auth.require_preauth(db, token, csrf),
                    VerifyInput(challenge_id=challenge.public_id, code=code), '127.0.0.1')
                new_csrf = auth._csrf(session); db.commit()
                assert not principal.access.can_order and principal.access.can_view_price == view_price
            client.headers.update({'Cookie':router.cookie_name('session')+'='+new_token, 'X-Portal-CSRF':new_csrf})
            await denied(403)
            result = await client.get(path)
            assert result.status_code == 200
            data = result.json()['data']
            assert data['status'] == 'awaiting_customer' and data['available_actions'] == []
            assert ('total_amount' in data) is view_price
            assert ('unit_price' in data['items'][0]) is view_price
            assert ('proposal' in data) is view_price
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                saved = db.get(Revision, order.active_revision_id)
                assert order.row_version == 2 and order.accepted_revision_id is None
                assert saved.customer_accepted_by is None and saved.customer_accepted_at is None
    asyncio.run(run())