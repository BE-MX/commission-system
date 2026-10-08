"""Committed accept/approve receipts recover without activating replaced revisions."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
import secrets
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import router as employee_router, service as employee_auth, utils
from app.auth.models import ArkUser
from app.core.database import get_db
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import (auth_service as auth, router, admin_router, approval_service, proposal_service,
    proposal_decisions, catalog_service, pricing, pi_service, pi_revision_source,
    pi_amendment_service as amendments)
from app.portal.errors import PortalError
from app.portal.models import (OrderRequest, Revision, RequestLine, CommandReceipt, Conversion,
    Publication, PiAmendment, AuditEvent, OutboxEvent)
from app.portal.schemas import ProposalInput, PiProposalInput
from test_mysql_services import accepted_request, submit, count


def snapshot(ctx):
    with Session(ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (Invoice,InvoiceItem,ReceiptIntent,OrderRequest,Revision,RequestLine,
                CommandReceipt,Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent))


def proposal_body(ctx):
    return ProposalInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
        'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
        'payment_terms':'prepaid','valid_for_hours':24,'reason':'Confirm current complete terms'})


def make_app(ctx, monkeypatch):
    settings = auth.get_settings(); settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router,'get_settings',lambda:settings)
    monkeypatch.setattr(pi_revision_source,'get_settings',auth.get_settings)
    jwt_settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48),JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15,REFRESH_TOKEN_EXPIRE_DAYS=1,COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30,LOGIN_MAX_FAIL=5)
    for module in (employee_router,employee_auth,utils): monkeypatch.setattr(module,'settings',jwt_settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        employee = db.get(ArkUser,ctx.actor); employee.password_hash = utils.hash_password(password)
        username = employee.username; db.commit()
    app = FastAPI(); app.include_router(employee_router.router,prefix='/api/auth')
    app.include_router(router.router,prefix='/api/portal/v1')
    app.include_router(admin_router.router,prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    headers = {'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,
        'Cookie':router.cookie_name('session')+'='+ctx.token,'X-Portal-CSRF':ctx.csrf}
    return app,settings,headers,{'username':username,'password':password}


class LoseResponse(httpx.AsyncBaseTransport):
    def __init__(self,app,path):
        self.inner = httpx.ASGITransport(app=app,client=('127.0.0.1',51000))
        self.path = path; self.lost = None
    async def handle_async_request(self,request):
        response = await self.inner.handle_async_request(request)
        if request.method == 'POST' and request.url.path == self.path and self.lost is None:
            await response.aread(); assert response.status_code == 200
            self.lost = response.json()['data']; await response.aclose()
            raise httpx.ReadError('Lost committed decision response',request=request)
        return response
    async def aclose(self): await self.inner.aclose()


@pytest.mark.parametrize('operation',['accept','approve'])
@pytest.mark.parametrize('change',['expiry','replacement'])
@pytest.mark.parametrize('unavailable',['price','inventory'])
def test_accept_and_approve_recover_after_response_loss(trade,monkeypatch,operation,change,unavailable):
    ctx = trade
    if operation == 'approve':
        request_id,body = accepted_request(ctx)
        command = body.model_dump(mode='json'); expected = 3
        path = '/api/portal/admin/v1/orders/'+request_id+'/approve'
        revision_id = str(body.accepted_revision_id)
    else:
        with Session(ctx.engine) as db:
            initial = submit(ctx,db); db.commit(); request_id = initial['request_id']
            proposed = proposal_service.create(db,ctx.actor,request_id,1,proposal_body(ctx)); db.commit()
            receipt = proposed['original_receipt']; revision_id = receipt['revision_id']
        command = {'proposal_hash':receipt['content_hash']}; expected = 2
        path = '/api/portal/v1/orders/'+request_id+'/proposals/'+revision_id+'/accept'
    app,settings,headers,login_body = make_app(ctx,monkeypatch)
    async def run():
        transport = LoseResponse(app,path)
        async with httpx.AsyncClient(transport=transport,base_url=settings.PORTAL_ORIGIN,headers=headers) as client:
            login = await client.post('/api/auth/login',json=login_body)
            assert login.status_code == 200
            client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
            original_match = {'If-Match':'"'+str(expected)+'"'}
            with pytest.raises(httpx.ReadError,match='Lost committed'):
                await client.post(path,json=command,headers=original_match)
            original = transport.lost
            assert original is not None and not original['replayed']
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                revision = db.scalar(select(Revision).where(Revision.public_id == revision_id))
                assert order.row_version == expected+1 and revision.customer_accepted_by == ctx.account_id
                if operation == 'approve': assert order.invoice_id == original['original_receipt']['invoice_id']
                expiry = revision.expires_at
                if change == 'replacement':
                    if operation == 'accept':
                        replacement = proposal_body(ctx); replacement.fees.shipping_amount = '46.00'
                        proposal_service.create(db,ctx.actor,request_id,order.row_version,replacement); db.commit()
                    else:
                        invoice = db.get(Invoice,order.invoice_id); invoice.remark = 'PI B needs customer confirmation'; db.commit()
                        amendments.create(db,ctx.actor,request_id,order.row_version,PiProposalInput(
                            invoice_document_version=invoice.portal_document_version,reason='Confirm revised PI B')); db.commit()
            if change == 'expiry': monkeypatch.setattr(proposal_decisions,'beijing_now',lambda:expiry+timedelta(seconds=1))
            baseline = snapshot(ctx)
            calls = []
            def unavailable_source(*args,**kwargs):
                calls.append(unavailable)
                raise PortalError('PRICE_UNAVAILABLE' if unavailable == 'price' else 'INVENTORY_UNAVAILABLE','Test source unavailable',503)
            target,name = (pricing,'resolve') if unavailable == 'price' else (catalog_service,'load_observations')
            with monkeypatch.context() as scoped:
                scoped.setattr(target,name,unavailable_source)
                fresh = await client.post('/api/portal/v1/quotes',json=ctx.quote_body.model_dump(mode='json'))
                assert fresh.status_code == 503 and calls
                assert fresh.json()['data']['error_code'] == ('PRICE_UNAVAILABLE' if unavailable == 'price' else 'INVENTORY_UNAVAILABLE')
                assert snapshot(ctx) == baseline
                calls.clear()
                replay = await client.post(path,json=command,headers=original_match)
                assert replay.status_code == 200 and 'no-store' in replay.headers['cache-control']
                data = replay.json()['data']
                assert data['replayed'] and data['original_receipt'] == original['original_receipt']
                assert calls == [] and snapshot(ctx) == baseline
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                revision = db.scalar(select(Revision).where(Revision.public_id == revision_id))
                saved = db.scalars(select(CommandReceipt).where(CommandReceipt.object_public_id == request_id,
                    CommandReceipt.action == operation)).all()
                assert len(saved) == 1 and saved[0].first_actor_id == (ctx.actor if operation == 'approve' else ctx.account_id)
                assert revision.customer_accepted_by == ctx.account_id
                assert data['row_version'] == order.row_version and data['current_state'] == order.status
                if operation == 'accept':
                    assert count(db,Invoice,Invoice.source_order_id == request_id) == 0
                    if change == 'replacement':
                        assert order.status == 'awaiting_customer' and order.accepted_revision_id is None
                        assert order.active_revision_id != revision.id
                else:
                    assert count(db,Invoice,Invoice.source_order_id == request_id) == 1
                    if change == 'replacement':
                        amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
                        assert amendment.status == 'pending_customer' and amendment.accepted_revision_id is None
                        with pytest.raises(PortalError) as caught: pi_service.capture(db,ctx.token,request_id)
                        assert caught.value.code == 'PI_REVISION_PENDING'
                        db.rollback()
            assert snapshot(ctx) == baseline
    asyncio.run(run())


@pytest.mark.parametrize('publish_a',[False,True])
def test_old_pi_accept_and_publish_receipts_never_confirm_b(trade,monkeypatch,publish_a):
    ctx = trade
    monkeypatch.setattr(pi_revision_source,'get_settings',auth.get_settings)
    request_id,accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,accepted); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice,order.invoice_id); invoice.remark = 'PI A'; db.commit()
        proposed_a = amendments.create(db,ctx.actor,request_id,order.row_version,PiProposalInput(
            invoice_document_version=invoice.portal_document_version,reason='Confirm PI A')); db.commit()
        receipt_a = proposed_a['original_receipt']; document_a = invoice.portal_document_version
    app,settings,headers,login_body = make_app(ctx,monkeypatch)
    path_a = '/api/portal/v1/orders/'+request_id+'/proposals/'+receipt_a['revision_id']+'/accept'
    publish_path = '/api/portal/admin/v1/orders/'+request_id+'/publish-pi'
    async def run():
        transport = LoseResponse(app,path_a)
        async with httpx.AsyncClient(transport=transport,base_url=settings.PORTAL_ORIGIN,headers=headers) as client:
            login = await client.post('/api/auth/login',json=login_body); assert login.status_code == 200
            client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
            match_a = {'If-Match':'"'+str(proposed_a['row_version'])+'"'}
            accept_a = {'proposal_hash':receipt_a['content_hash']}
            with pytest.raises(httpx.ReadError,match='Lost committed'):
                await client.post(path_a,json=accept_a,headers=match_a)
            original_a = transport.lost
            publish_a_body = {'accepted_revision_id':receipt_a['revision_id'],'invoice_document_version':document_a}
            publish_a_match = {'If-Match':'"'+str(original_a['row_version'])+'"'}
            original_publish = None
            if publish_a:
                published = await client.post(publish_path,json=publish_a_body,headers=publish_a_match)
                assert published.status_code == 200
                original_publish = published.json()['data']
                with Session(ctx.engine) as db:
                    _,_,current = pi_service.capture(db,ctx.token,request_id); assert current['remark'] == 'PI A'
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                invoice = db.get(Invoice,order.invoice_id); invoice.remark = 'PI B'; db.commit()
                proposed_b = amendments.create(db,ctx.actor,request_id,order.row_version,PiProposalInput(
                    invoice_document_version=invoice.portal_document_version,reason='Confirm PI B')); db.commit()
                receipt_b = proposed_b['original_receipt']; document_b = invoice.portal_document_version
            baseline = snapshot(ctx)
            replay = await client.post(path_a,json=accept_a,headers=match_a)
            assert replay.status_code == 200
            data = replay.json()['data']
            assert data['replayed'] and data['original_receipt'] == original_a['original_receipt']
            assert data['amendment_state'] == 'pending_customer' and data['row_version'] == proposed_b['row_version']
            old_publish = await client.post(publish_path,json=publish_a_body,headers=publish_a_match)
            if publish_a:
                assert old_publish.status_code == 200
                result = old_publish.json()['data']
                assert result['replayed'] and result['original_receipt'] == original_publish['original_receipt']
                assert result['amendment_state'] == 'pending_customer'
            else:
                assert old_publish.status_code == 409 and old_publish.json()['data']['error_code'] == 'VERSION_CONFLICT'
            assert snapshot(ctx) == baseline
            # A's accepted ID paired with B's current document cannot publish B;
            # even B's correct ID still requires B's own customer confirmation.
            for stale_or_unaccepted in (receipt_a['revision_id'],receipt_b['revision_id']):
                unconfirmed = await client.post(publish_path,json={'accepted_revision_id':stale_or_unaccepted,
                    'invoice_document_version':document_b},headers={'If-Match':'"'+str(proposed_b['row_version'])+'"'})
                assert unconfirmed.status_code == 409
                assert unconfirmed.json()['data']['error_code'] == 'CUSTOMER_ACCEPTANCE_REQUIRED'
                assert snapshot(ctx) == baseline
            with Session(ctx.engine) as db:
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                amendment = db.scalar(select(PiAmendment).where(PiAmendment.request_id == order.id))
                revision_b = db.scalar(select(Revision).where(Revision.public_id == receipt_b['revision_id']))
                assert amendment.active_revision_id == revision_b.id and amendment.accepted_revision_id is None
                assert revision_b.customer_accepted_by is None
                assert count(db,Publication,(Publication.request_id == order.id)&(Publication.status == 'published')) == 0
                with pytest.raises(PortalError) as caught: pi_service.capture(db,ctx.token,request_id)
                assert caught.value.code == 'PI_REVISION_PENDING'; db.rollback()
            assert snapshot(ctx) == baseline
            # Only a new B acceptance followed by B publication makes it available.
            accepted_b = await client.post('/api/portal/v1/orders/'+request_id+'/proposals/'+receipt_b['revision_id']+'/accept',
                json={'proposal_hash':receipt_b['content_hash']},headers={'If-Match':'"'+str(proposed_b['row_version'])+'"'})
            assert accepted_b.status_code == 200
            published_b = await client.post(publish_path,json={'accepted_revision_id':receipt_b['revision_id'],
                'invoice_document_version':document_b},headers={'If-Match':'"'+str(accepted_b.json()['data']['row_version'])+'"'})
            assert published_b.status_code == 200
            with Session(ctx.engine) as db:
                _,ticket,current = pi_service.capture(db,ctx.token,request_id)
                assert current['remark'] == 'PI B' and ticket['invoice_document_version'] == document_b
                order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
                assert count(db,Invoice,Invoice.source_order_id == request_id) == 1
                assert count(db,Publication,Publication.request_id == order.id) == 2+int(publish_a)
    asyncio.run(run())