"""HTTP and database constraints prevent publishing a different request's PI."""
import asyncio
from types import SimpleNamespace
import secrets
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import router as auth_router, service as auth_service, utils
from app.auth.models import ArkUser
from app.core.database import get_db
from app.core.time import beijing_now
from app.invoice.models import Invoice
from app.portal import (auth_service as customer_auth, quote_service, approval_service,
    pi_amendment_service as amendments, pi_revision_source, pi_service, admin_router)
from app.portal.models import (OrderRequest, Revision, RequestLine, CommandReceipt, Conversion,
    Publication, PiAmendment, AuditEvent, OutboxEvent)
from app.portal.schemas import SubmitInput, PiProposalInput, AcceptInput
from test_mysql_services import accepted_request


def test_same_company_pi_publication_cannot_select_another_invoice(trade, monkeypatch):
    ctx = trade
    monkeypatch.setattr(pi_revision_source,'get_settings',customer_auth.get_settings)
    contexts = [ctx,SimpleNamespace(**vars(ctx))]
    with Session(ctx.engine) as db:
        quote = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body); db.commit()
        contexts[1].key = uuid4()
        contexts[1].body = SubmitInput(quote_id=quote['quote_id'],quote_content_hash=quote['content_hash'],
            customer_po=ctx.quote_body.customer_po,remark='')
    orders = []
    for current in contexts:
        request_id, accepted = accepted_request(current)
        with Session(ctx.engine) as db:
            approval_service.approve(db,current.actor,request_id,3,accepted); db.commit()
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            invoice = db.get(Invoice,order.invoice_id)
            invoice.remark = 'Updated terms for '+request_id; db.commit()
            proposed = amendments.create(db,current.actor,request_id,order.row_version,
                PiProposalInput(invoice_document_version=invoice.portal_document_version,reason='Confirm updated PI'))
            db.commit()
            revision = proposed['original_receipt']
            amendments.decide(db,current.token,current.csrf,request_id,revision['revision_id'],proposed['row_version'],
                AcceptInput(proposal_hash=revision['content_hash']),accept=True); db.commit()
            db.refresh(order)
            orders.append({'request_id':request_id,'request_pk':order.id,'invoice_id':invoice.id,
                'document_version':invoice.portal_document_version,'version':order.row_version,
                'revision_id':revision['revision_id']})
    settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48),JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15,REFRESH_TOKEN_EXPIRE_DAYS=1,COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30,LOGIN_MAX_FAIL=5)
    for module in (auth_router,auth_service,utils): monkeypatch.setattr(module,'settings',settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        owner = db.get(ArkUser,ctx.actor); owner.password_hash = utils.hash_password(password)
        username = owner.username; db.commit()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (Invoice,OrderRequest,Revision,RequestLine,CommandReceipt,Conversion,
                    Publication,PiAmendment,AuditEvent,OutboxEvent))
    baseline = snapshot()
    first,second = orders
    with Session(ctx.engine) as db:
        revision_pk = db.scalar(select(Revision.id).where(Revision.public_id == first['revision_id']))
        db.add(Publication(request_id=first['request_pk'],invoice_id=second['invoice_id'],
            invoice_document_version=second['document_version'],revision_id=revision_pk,
            content_hash='0'*64,customer_snapshot_json={},render_template_version='portal-pi-v1',
            status='published',published_by=ctx.actor,published_at=beijing_now()))
        with pytest.raises(IntegrityError) as caught: db.flush()
        assert caught.value.orig.args[0] == 1452  # Real FK, not a duplicate version.
        db.rollback()
    assert snapshot() == baseline
    app = FastAPI(); app.include_router(auth_router.router,prefix='/api/auth')
    app.include_router(admin_router.router,prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            login = await client.post('/api/auth/login',json={'username':username,'password':password})
            assert login.status_code == 200
            client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
            for own,foreign in ((first,second),(second,first)):
                path = '/api/portal/admin/v1/orders/'+own['request_id']+'/publish-pi'
                body = {'accepted_revision_id':own['revision_id'],'invoice_document_version':own['document_version']}
                headers = {'If-Match':chr(34)+str(own['version'])+chr(34)}
                response = await client.post(path,json={**body,'invoice_id':foreign['invoice_id']},headers=headers)
                assert response.status_code == 422 and response.json()['data']['error_code'] == 'INVALID_INPUT'
                response = await client.post(path,json={**body,'accepted_revision_id':foreign['revision_id']},headers=headers)
                assert response.status_code == 404 and response.json()['data']['error_code'] == 'RESOURCE_NOT_FOUND'
                assert snapshot() == baseline
            positive = await client.post('/api/portal/admin/v1/orders/'+first['request_id']+'/publish-pi',
                json={'accepted_revision_id':first['revision_id'],'invoice_document_version':first['document_version']},
                headers={'If-Match':chr(34)+str(first['version'])+chr(34)})
            assert positive.status_code == 200
            with Session(ctx.engine) as db:
                _,ticket,published = pi_service.capture(db,ctx.token,first['request_id'])
                assert ticket['request_id'] == published['request_id'] == first['request_id']
                assert published['remark'] == 'Updated terms for '+first['request_id']
                conversion = db.scalar(select(Conversion).where(Conversion.request_id == first['request_pk']))
                assert conversion.invoice_id == first['invoice_id']
                other = db.scalar(select(PiAmendment).where(PiAmendment.request_id == second['request_pk']))
                assert other.status == 'accepted' and other.invoice_id == second['invoice_id']
    asyncio.run(run())