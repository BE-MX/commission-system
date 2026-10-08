"""All customer POST routes reject cross-origin and absent/incorrect CSRF tokens."""
import asyncio
from datetime import timedelta
import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.portal import auth_service as auth, router
from app.portal.models import (Account, OrderRequest, Revision, RequestLine, Quote, CommandReceipt,
    AuditEvent, OutboxEvent, PortalSession, PreauthSession, AuthChallenge, RateBucket)
from app.portal.schemas import ChallengeInput
from app.portal.security import open_secret
from test_mysql_services import accepted_request


def test_every_customer_post_checks_exact_origin_and_csrf(trade, monkeypatch):
    ctx = trade
    settings = auth.get_settings(); settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router,'get_settings',lambda:settings)
    request_id, accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        revision = db.get(Revision,order.accepted_revision_id)
        revision_id, proposal_hash = revision.public_id, revision.content_hash
        email = db.get(Account,ctx.account_id).email_normalized
        clock = auth.beijing_now()+timedelta(seconds=61)
        monkeypatch.setattr(auth,'beijing_now',lambda:clock)
        preauth, pre_token, pre_csrf = auth.bootstrap(db,'127.0.0.1'); db.commit()
        challenge = auth.challenge(db,auth.require_preauth(db,pre_token,pre_csrf),
            ChallengeInput(email=email,purpose='login'),'127.0.0.1'); db.commit()
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge.public_id))
        code = open_secret(settings.PORTAL_MAIL_KEYS['v1'],event.secret_envelope,
            event_key=event.event_key,purpose='login',object_id=challenge.public_id)
        challenge_id = challenge.public_id
    paths = {
        '/auth/challenges': {'email':email,'purpose':'login'},
        '/auth/verify': {'challenge_id':challenge_id,'code':code},
        '/auth/logout': {}, '/quotes': ctx.quote_body.model_dump(mode='json'),
        '/orders': ctx.body.model_dump(mode='json'),
        '/orders/{request_id}/cancel': {'reason':'Cancel order'},
        '/orders/{request_id}/proposals/{revision_id}/accept': {'proposal_hash':proposal_hash},
        '/orders/{request_id}/proposals/{revision_id}/reject': {'reason':'Decline terms'},
        '/orders/{request_id}/reorder-quote': {},
    }
    registered = {route.path for route in router.router.routes if 'POST' in route.methods}
    assert set(paths) == registered  # A new POST route must receive coverage too.
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)).all())
                for model in (OrderRequest,Revision,RequestLine,Quote,CommandReceipt,AuditEvent,OutboxEvent,
                    PortalSession,PreauthSession,AuthChallenge,RateBucket))
    app = FastAPI(); app.include_router(router.router,prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        baseline = snapshot()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',51000)),
            base_url=settings.PORTAL_ORIGIN) as client:
            for path, body in paths.items():
                csrf = pre_csrf if path in {'/auth/challenges','/auth/verify'} else ctx.csrf
                for attack in ('sibling_origin','null_origin','missing_origin','missing_csrf','wrong_csrf'):
                    headers = {'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,'X-Portal-CSRF':csrf,
                        'Cookie':router.cookie_name('session')+'='+ctx.token+'; '+router.cookie_name('preauth')+'='+pre_token,
                        'If-Match':chr(34)+'3'+chr(34),'Idempotency-Key':str(ctx.key)}
                    if attack == 'sibling_origin': headers['Origin'] = 'https://sibling.example.test'
                    elif attack == 'null_origin': headers['Origin'] = 'null'
                    elif attack == 'missing_origin': headers.pop('Origin')
                    elif attack == 'missing_csrf': headers.pop('X-Portal-CSRF')
                    else: headers['X-Portal-CSRF'] = '0'*64
                    url = path.replace('{request_id}',request_id).replace('{revision_id}',revision_id)
                    response = await client.post('/api/portal/v1'+url,json=body,headers=headers)
                    assert response.status_code == 403, (path,attack,response.text)
                    assert response.json()['data']['error_code'] == 'CSRF_REJECTED'
                    assert response.headers['Cache-Control'] == 'no-store'
                    assert 'set-cookie' not in response.headers
                    assert snapshot() == baseline
            # Correct-origin controls prove both session kinds are otherwise valid.
            headers = {'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,
                'Cookie':router.cookie_name('session')+'='+ctx.token+'; '+router.cookie_name('preauth')+'='+pre_token}
            quoted = await client.post('/api/portal/v1/quotes',json=paths['/quotes'],
                headers={**headers,'X-Portal-CSRF':ctx.csrf})
            assert quoted.status_code == 201
            verified = await client.post('/api/portal/v1/auth/verify',json=paths['/auth/verify'],
                headers={**headers,'X-Portal-CSRF':pre_csrf})
            assert verified.status_code == 200 and 'set-cookie' in verified.headers
    asyncio.run(run())