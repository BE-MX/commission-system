"""Same-company requests cannot exchange proposal revisions or accept stale terms."""
import asyncio
from uuid import uuid4
import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.portal import (auth_service as auth, quote_service, order_service, proposal_service,
    proposal_decisions, router)
from app.portal.models import OrderRequest, Revision, RequestLine, Quote, CommandReceipt, AuditEvent, OutboxEvent
from app.portal.schemas import SubmitInput, ProposalInput, ReasonInput


def test_same_company_proposals_are_bound_current_and_unexpired(trade, monkeypatch):
    ctx = trade
    settings = auth.get_settings(); settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router,'get_settings',lambda:settings)
    def create_order():
        with Session(ctx.engine) as db:
            quoted = quote_service.create(db,ctx.token,ctx.csrf,ctx.quote_body); db.commit()
            submitted = order_service.submit(db,ctx.token,ctx.csrf,uuid4(),SubmitInput(
                quote_id=quoted['quote_id'],quote_content_hash=quoted['content_hash'],
                customer_po=ctx.quote_body.customer_po,remark='')); db.commit()
            body = ProposalInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
                'fees':{'shipping_amount':'45.00','packaging_amount':'0.00','surcharge_amount':'0.00'},
                'payment_terms':'prepaid','valid_for_hours':24,'reason':'Confirm current commercial terms'})
            proposed = proposal_service.create(db,ctx.actor,submitted['request_id'],1,body); db.commit()
            return submitted['request_id'],proposed['original_receipt'],body
    first_id, old, body = create_order()
    second_id, other, _ = create_order()
    with Session(ctx.engine) as db:
        proposal_decisions.decide(db,ctx.token,ctx.csrf,first_id,old['revision_id'],2,
            ReasonInput(reason='Request revised proposal'),accept=False); db.commit()
        replaced = proposal_service.create(db,ctx.actor,first_id,3,body); db.commit()
        current = replaced['original_receipt']
        expires = db.scalar(select(Revision.expires_at).where(Revision.public_id == other['revision_id']))
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest,Revision,RequestLine,Quote,CommandReceipt,AuditEvent,OutboxEvent))
    app = FastAPI(); app.include_router(router.router,prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',51000)),
            base_url=settings.PORTAL_ORIGIN,headers={'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,
                'Cookie':router.cookie_name('session')+'='+ctx.token,'X-Portal-CSRF':ctx.csrf}) as client:
            for request_id, revision, version in ((first_id,current,4),(second_id,other,2)):
                result = await client.get('/api/portal/v1/orders/'+request_id)
                assert result.status_code == 200 and result.json()['data']['revision_id'] == revision['revision_id']
                assert result.json()['data']['row_version'] == version
            baseline = snapshot()
            async def attempt(request_id, revision_id, proposal_hash, version, status, error_code):
                response = await client.post('/api/portal/v1/orders/'+request_id+'/proposals/'+revision_id+'/accept',
                    json={'proposal_hash':proposal_hash},headers={'If-Match':chr(34)+str(version)+chr(34)})
                assert response.status_code == status and response.json()['data']['error_code'] == error_code
                assert snapshot() == baseline
            await attempt(first_id,other['revision_id'],other['content_hash'],4,404,'RESOURCE_NOT_FOUND')
            await attempt(second_id,current['revision_id'],current['content_hash'],2,404,'RESOURCE_NOT_FOUND')
            await attempt(first_id,old['revision_id'],old['content_hash'],4,409,'PROPOSAL_SUPERSEDED')
            await attempt(first_id,current['revision_id'],'0'*64,4,409,'PROPOSAL_CHANGED')
            original_clock = proposal_decisions.beijing_now
            monkeypatch.setattr(proposal_decisions,'beijing_now',lambda:expires)
            await attempt(second_id,other['revision_id'],other['content_hash'],2,409,'PROPOSAL_EXPIRED')
            monkeypatch.setattr(proposal_decisions,'beijing_now',original_clock)
            positive = await client.post('/api/portal/v1/orders/'+first_id+'/proposals/'+current['revision_id']+'/accept',
                json={'proposal_hash':current['content_hash']},headers={'If-Match':chr(34)+'4'+chr(34)})
            assert positive.status_code == 200
            with Session(ctx.engine) as db:
                first = db.scalar(select(OrderRequest).where(OrderRequest.public_id == first_id))
                second = db.scalar(select(OrderRequest).where(OrderRequest.public_id == second_id))
                chosen = db.get(Revision,first.accepted_revision_id)
                assert first.status == 'ready_for_review' and chosen.public_id == current['revision_id']
                assert chosen.customer_accepted_by == ctx.account_id
                assert second.status == 'awaiting_customer' and second.accepted_revision_id is None
                for record in db.scalars(select(Revision).where(Revision.public_id.in_([old['revision_id'],other['revision_id']]))):
                    assert record.customer_accepted_by is None and record.customer_accepted_at is None
    asyncio.run(run())