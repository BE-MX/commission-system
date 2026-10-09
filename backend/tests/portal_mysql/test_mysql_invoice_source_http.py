"""Authenticated manual HTTP writes cannot forge portal invoice provenance."""
import asyncio
from copy import deepcopy
import secrets
from types import SimpleNamespace
from uuid import uuid4
import httpx
from fastapi import FastAPI
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session
from app.auth import router as auth_router, service as auth_service, utils
from app.auth.models import ArkUser
from app.core.database import get_db
from app.invoice import router, service as invoices
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask
from app.invoice.schemas import InvoiceUpdate, InvoiceItemPayload
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import approval_service
from app.portal.models import OrderRequest, Revision, CommandReceipt, Conversion, Publication, AuditEvent, OutboxEvent
from test_mysql_services import accepted_request


def test_manual_http_cannot_create_or_rewrite_portal_source(trade, monkeypatch):
    ctx = trade
    metadata = MetaData()
    for model in (Receipt, InvoiceAllocation, ShippingOperationEvent, OkkiOutboundTask):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=c.nullable, default=c.default, server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine)
    request_id, accepted = accepted_request(ctx)
    settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48), JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=1, COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30, LOGIN_MAX_FAIL=5)
    for module in (auth_router, auth_service, utils): monkeypatch.setattr(module, 'settings', settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        approval_service.approve(db, ctx.actor, request_id, 3, accepted); db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = invoices.get_invoice(db, order.invoice_id)
        invoice_id = invoice.id
        values = {key:getattr(invoice,key) for key in InvoiceUpdate.model_fields if hasattr(invoice,key) and key != 'items'}
        values['items'] = [{key:getattr(item,key) for key in InvoiceItemPayload.model_fields if hasattr(item,key)} for item in invoice.items]
        for item in values['items']: item['semifinished_plan'] = item.get('semifinished_plan') or []
        body = InvoiceUpdate.model_validate(values).model_dump(mode='json')
        assert body['source_type'] == 'portal' and body['source_order_id'] == request_id
        owner = db.get(ArkUser, ctx.actor); owner.password_hash = utils.hash_password(password)
        username = owner.username; db.commit()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (Invoice, InvoiceItem, ReceiptIntent, OrderRequest, Revision, CommandReceipt,
                    Conversion, Publication, AuditEvent, OutboxEvent))
    app = FastAPI(); app.include_router(auth_router.router, prefix='/api/auth')
    app.include_router(router.router, prefix='/api/invoice')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            login = await client.post('/api/auth/login', json={'username':username,'password':password})
            assert login.status_code == 200
            client.headers['Authorization'] = 'Bearer '+login.json()['access_token']
            baseline = snapshot()
            for endpoint in ('/invoices', '/import/screenshot/create'):
                forged = deepcopy(body); forged['invoice_no'] = 'FORGED-'+uuid4().hex
                # Extra client flags must not become trusted service arguments.
                forged['allow_portal_source'] = True
                response = await client.post('/api/invoice'+endpoint, json=forged)
                assert response.status_code == 400
                assert response.json()['detail'] == '门户来源发票只能通过客户订单审核入口创建'
            forged = deepcopy(body)
            forged.update(source_type='manual', source_order_no=None, source_order_name=None, invoice_no='FORGED-'+uuid4().hex)
            response = await client.post('/api/invoice/invoices', json=forged)
            assert response.status_code == 400 and response.json()['detail'] == '手工发票不能携带 OKKI 截图来源信息'
            for changes in ({'source_order_id':str(uuid4())}, {'source_type':'manual','source_order_id':None,'source_order_name':None}):
                forged = {**deepcopy(body), **changes}
                response = await client.put('/api/invoice/invoices/'+str(invoice_id), json=forged)
                assert response.status_code == 400 and response.json()['detail'] == '订单来源信息不可修改，请重新创建订单'
            assert snapshot() == baseline
    asyncio.run(run())