"""Catalog, order and PI routes reject old cookies after access closure."""
import asyncio
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.invoice.models import Invoice, InvoiceItem
from app.portal import auth_service as auth, admin_service, site_service, approval_service, pi_pdf, router
from app.portal.authority import lock_authority
from app.portal.models import (Account, Membership, CustomerAccess, Site, OrderRequest, Revision, RequestLine,
    Quote, CommandReceipt, AuditEvent, OutboxEvent, Conversion, Publication)
from app.portal.schemas import AccountUpdate, CustomerUpdate, SiteUpdate
from test_mysql_services import accepted_request


@pytest.mark.parametrize('closure', ['account', 'member', 'customer', 'site'])
def test_disabled_identity_rejects_old_cookie_on_customer_http_routes(trade, monkeypatch, closure):
    ctx = trade
    settings = auth.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    for module in (router, site_service): monkeypatch.setattr(module, 'get_settings', lambda: settings)
    rendered = []
    def render(snapshot):
        rendered.append(snapshot['total_amount'])
        return b'%PDF-1.4 isolated-render-boundary'
    monkeypatch.setattr(pi_pdf, 'render', render)
    request_id, accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,accepted); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        revision = db.get(Revision,order.accepted_revision_id)
        revision_id, proposal_hash = revision.public_id, revision.content_hash
    app = FastAPI(); app.include_router(router.router,prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (Invoice,InvoiceItem,OrderRequest,Revision,RequestLine,Quote,CommandReceipt,
                    AuditEvent,OutboxEvent,Conversion,Publication))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',51000)),
            base_url=settings.PORTAL_ORIGIN,headers={'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,
                'Cookie':router.cookie_name('session')+'='+ctx.token,'X-Portal-CSRF':ctx.csrf,
                'If-Match':chr(34)+'4'+chr(34),'Idempotency-Key':str(ctx.key)}) as client:
            path = '/orders/'+request_id
            reads = ['/session','/catalog','/catalog/'+ctx.item_id,'/orders',path,path+'/pi',
                '/quotes/'+str(ctx.body.quote_id),'/orders/by-key/'+str(ctx.key)]
            for route in reads:
                assert (await client.get('/api/portal/v1'+route)).status_code == 200
            assert rendered == ['128.00']
            with Session(ctx.engine) as db:
                access = db.get(CustomerAccess,ctx.access_id)
                if closure == 'account':
                    account = db.get(Account,ctx.account_id)
                    admin_service.update_account(db,ctx.admin,account.public_id,account.row_version,
                        AccountUpdate(status='disabled',reason='Disable customer account'))
                elif closure == 'customer':
                    admin_service.update_customer(db,ctx.admin,access.public_id,access.row_version,
                        CustomerUpdate(status='suspended',capabilities={'can_order':True,'can_view_price':True},
                            reason='Suspend customer access'))
                elif closure == 'site':
                    site = db.get(Site,access.site_id)
                    site_service.update_settings(db,ctx.admin,site.row_version,SiteUpdate(name=site.name,
                        status='disabled',policy=site.policy_json,reason='Close customer portal'))
                else:
                    # No standalone member administration endpoint exists in P0.
                    # Change persisted membership under the real authority barrier.
                    lock_authority(db,force=True)
                    member = db.scalar(select(Membership).where(Membership.account_id == ctx.account_id,
                        Membership.access_id == ctx.access_id))
                    member.status = 'disabled'
                db.commit()
            baseline = snapshot()
            expected = 503 if closure == 'site' else 401
            error_code = 'SERVICE_UNAVAILABLE' if closure == 'site' else 'AUTH_REQUIRED'
            async def check(response):
                assert response.status_code == expected
                assert response.json()['data']['error_code'] == error_code
                assert response.headers['Cache-Control'] == 'no-store'
            for route in reads + ['/catalog/'+ctx.item_id+'/image?version=1']:
                await check(await client.get('/api/portal/v1'+route))
            writes = [('/quotes',ctx.quote_body.model_dump(mode='json')),('/orders',ctx.body.model_dump(mode='json')),
                (path+'/cancel',{'reason':'Cancel from old page'}),
                (path+'/proposals/'+revision_id+'/accept',{'proposal_hash':proposal_hash}),
                (path+'/proposals/'+revision_id+'/reject',{'reason':'Reject from old page'}),
                (path+'/reorder-quote',{})]
            for route, body in writes:
                await check(await client.post('/api/portal/v1'+route,json=body))
            assert rendered == ['128.00'] and snapshot() == baseline
    asyncio.run(run())