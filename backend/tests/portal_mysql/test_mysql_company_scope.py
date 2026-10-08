"""Two valid companies on the same site cannot exchange order capabilities."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.portal import auth_service as auth, approval_service, quote_service, router, pi_service
from app.portal.access_policy import binding_fingerprint
from app.portal.models import CustomerAccess, CatalogGrant, OrderRequest, Revision, CommandReceipt, AuditEvent, OutboxEvent, Quote, RequestLine, Publication
from app.portal.schemas import VerifyInput, SubmitInput
from test_mysql_invitation_race import invite, challenge
from test_mysql_services import accepted_request


def test_same_site_companies_cannot_access_each_others_orders(trade, monkeypatch):
    first = trade
    settings = auth.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    second = SimpleNamespace(**vars(first))
    with Session(first.engine) as db:
        original = db.get(CustomerAccess, first.access_id)
        company = CustomerAccount(display_name='Other buyer', canonical_company_name='Other company',
            record_status='active', identity_status='verified')
        db.add(company); db.flush()
        identity = CustomerExternalIdentity(customer_id=company.id, source_system='okki', source_account_key='okki:test',
            identifier_type='company_id', raw_value=str(company.id), normalized_value=str(company.id),
            identity_strength='strong', cardinality='one_to_one', verification_status='verified', status='active')
        assignment = CustomerAssignment(customer_id=company.id, user_id=first.actor, assignment_role='primary',
            assignment_status='active', assignment_source='manual', effective_from=beijing_now()-timedelta(days=1))
        db.add_all([identity, assignment]); db.flush()
        access = CustomerAccess(site_id=original.site_id, customer_id=company.id, okki_namespace='okki:test',
            okki_company_id=str(company.id), external_identity_id=identity.id, assignment_id=assignment.id,
            sales_user_id=first.actor, status='enabled', can_order=True, can_view_price=True,
            binding_fingerprint=binding_fingerprint(company.id, identity, assignment))
        db.add(access); db.flush()
        for grant in db.scalars(select(CatalogGrant).where(CatalogGrant.access_id == original.id)).all():
            db.add(CatalogGrant(access_id=access.id, catalog_item_id=grant.catalog_item_id))
        second.access_id = access.id
        db.commit()
        invitation = invite(second, db)
        attempt = challenge(db, invitation)
        principal, session, token = auth.verify(db, auth.require_preauth(db, attempt.token, attempt.csrf),
            VerifyInput(challenge_id=attempt.public_id, code=attempt.code), '127.0.0.1')
        assert principal.access.id == second.access_id and principal.access.customer_id != original.customer_id
        second.token, second.csrf, second.account_id = token, auth._csrf(session), principal.account.id
        db.commit()
        quoted = quote_service.create(db, second.token, second.csrf, second.quote_body)
        db.commit()
        second.key = uuid4()
        second.body = SubmitInput(quote_id=quoted['quote_id'], quote_content_hash=quoted['content_hash'],
            customer_po=second.quote_body.customer_po, remark='')
    orders = []
    for ctx in (first, second):
        request_id, accepted = accepted_request(ctx)
        with Session(ctx.engine) as db:
            approval_service.approve(db, ctx.actor, request_id, 3, accepted)
            db.commit()
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            revision = db.get(Revision, order.accepted_revision_id)
            _, ticket, _ = pi_service.capture(db, ctx.token, request_id)
            assert ticket['request_id'] == request_id
            orders.append((request_id, revision.public_id, revision.content_hash))
    def business_snapshot():
        with Session(first.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest, Revision, CommandReceipt, AuditEvent, OutboxEvent, Quote, RequestLine, Publication))
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(first.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        baseline = business_snapshot()
        for index, ctx in enumerate((first, second)):
            own, foreign = orders[index], orders[1-index]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 51000)),
                base_url=settings.PORTAL_ORIGIN, headers={'X-Real-IP':'127.0.0.1', 'Origin':settings.PORTAL_ORIGIN,
                    'X-Portal-CSRF':ctx.csrf, 'If-Match':chr(34)+'4'+chr(34), 'Cookie':router.cookie_name('session')+'='+ctx.token}) as client:
                own_response = await client.get('/api/portal/v1/orders/' + own[0])
                assert own_response.status_code == 200 and own_response.json()['data']['request_id'] == own[0]
                listing = await client.get('/api/portal/v1/orders')
                assert listing.status_code == 200 and listing.json()['data']['total'] == 1
                assert [item['request_id'] for item in listing.json()['data']['items']] == [own[0]]
                own_quote = await client.get('/api/portal/v1/quotes/' + str(ctx.body.quote_id))
                assert own_quote.status_code == 200
                def normalized(response):
                    data = response.json()
                    data['data'].pop('trace_id', None)
                    return data
                other_ctx = (first, second)[1-index]
                foreign_quote = await client.get('/api/portal/v1/quotes/' + str(other_ctx.body.quote_id))
                missing_quote = await client.get('/api/portal/v1/quotes/' + str(uuid4()))
                assert foreign_quote.status_code == missing_quote.status_code == 404
                assert normalized(foreign_quote) == normalized(missing_quote)
                for tail in ('', '/pi'):
                    response = await client.get('/api/portal/v1/orders/' + foreign[0] + tail)
                    assert response.status_code == 404
                    assert foreign[0] not in response.text
                    missing = await client.get('/api/portal/v1/orders/' + str(uuid4()) + tail)
                    assert missing.status_code == 404 and normalized(response) == normalized(missing)
                for action, body in (('accept', {'proposal_hash':foreign[2]}), ('reject', {'reason':'Decline foreign request'})):
                    response = await client.post('/api/portal/v1/orders/' + foreign[0] + '/proposals/' + foreign[1] + '/' + action, json=body)
                    assert response.status_code == 404
                    mixed = await client.post('/api/portal/v1/orders/' + own[0] + '/proposals/' + foreign[1] + '/' + action, json=body)
                    missing = await client.post('/api/portal/v1/orders/' + own[0] + '/proposals/' + str(uuid4()) + '/' + action, json=body)
                    assert mixed.status_code == missing.status_code == 404
                    assert normalized(mixed) == normalized(missing)
                response = await client.post('/api/portal/v1/orders/' + foreign[0] + '/cancel', json={'reason':'Cancel foreign request'})
                assert response.status_code == 404
        assert business_snapshot() == baseline
    asyncio.run(run())