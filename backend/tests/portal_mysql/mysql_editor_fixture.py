"""Shared actual JWT/HTTP fixture for employee invoice mutation tests."""
import asyncio
from copy import deepcopy
import queue
import secrets
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Column, MetaData, Table, select, text, delete, event
from sqlalchemy.orm import Session

from app.auth import router as auth_router, service as auth_service, utils
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission, ArkAccountUnlockAudit
from app.core.database import get_db
from app.invoice import router, service as invoices, linked_sync_service as linked
from app.invoice.models import Invoice, InvoiceItem, OkkiOutboundTask, InvoiceLinkedSync, InvoiceSyncLog, CustomerProfile
from app.invoice.schemas import InvoiceUpdate, InvoiceItemPayload
from app.receipt import remote
from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttachment
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import approval_service
from app.portal.errors import register_portal_error_handler
from app.portal.models import OrderRequest, Revision, CommandReceipt, Conversion, Publication, PiAmendment, AuditEvent, OutboxEvent
from test_mysql_services import accepted_request


@pytest.fixture
def editor(trade, monkeypatch):
    ctx=trade; metadata=MetaData()
    for model in (ArkAccountUnlockAudit,Receipt,InvoiceAllocation,ShippingOperationEvent,OkkiOutboundTask,InvoiceLinkedSync,InvoiceSyncLog,ReceiptAttachment,CustomerProfile):
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine)
    request_id,accepted=accepted_request(ctx)
    settings=SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48),JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15,REFRESH_TOKEN_EXPIRE_DAYS=1,COOKIE_SECURE=False,LOGIN_LOCK_MINUTES=30,LOGIN_MAX_FAIL=5)
    for module in (auth_router,auth_service,utils):monkeypatch.setattr(module,'settings',settings)
    monkeypatch.setattr(remote,'order_receipts',lambda *args:[])
    password=secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        approval_service.approve(db,ctx.actor,request_id,3,accepted);db.commit()
        order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
        invoice=invoices.get_invoice(db,order.invoice_id);invoice_id=invoice.id;version=invoice.portal_document_version
        values={key:getattr(invoice,key) for key in InvoiceUpdate.model_fields if hasattr(invoice,key) and key!='items'}
        values['items']=[{key:getattr(item,key) for key in InvoiceItemPayload.model_fields if hasattr(item,key)} for item in invoice.items]
        for item in values['items']:item['semifinished_plan']=item.get('semifinished_plan') or []
        values['remark']='Edited only after current employee authorization'
        body=InvoiceUpdate.model_validate(values).model_dump(mode='json')
        owner=db.get(ArkUser,ctx.actor);owner.password_hash=utils.hash_password(password);username=owner.username
        admin=db.get(ArkUser,ctx.admin);admin.is_active=True;admin.password_hash=utils.hash_password(password);admin_name=admin.username
        super_role=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==ctx.admin,ArkUserRole.role_id!=super_role))
        if db.scalar(select(ArkUserRole.user_id).where(ArkUserRole.user_id==ctx.admin,ArkUserRole.role_id==super_role)) is None:
            db.add(ArkUserRole(user_id=ctx.admin,role_id=super_role))
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code=='invoice:sync'))
        if permission is None:
            permission=ArkPermission(code='invoice:sync',module='invoice',action='sync',label='Test sync',kind='action',is_legacy=False,sort=1);db.add(permission);db.flush()
        role=ArkRole(name='edit-'+uuid4().hex[:12],label='Isolated sync role');db.add(role);db.flush()
        db.add_all([ArkRolePermission(role_id=role.id,permission_id=permission.id),ArkUserRole(user_id=owner.id,role_id=role.id)])
        db.commit()
    started=queue.Queue();pause=SimpleNamespace(ready=Event(),release=Event(),enabled=False)
    class HttpSession(Session):
        def commit(self):
            if pause.enabled:
                self.flush()
            edited=any(isinstance(row,Invoice) and (row.remark==body['remark'] or row.status==getattr(pause,'invoice_status','cancel_pending')) and row.portal_document_version>version for row in self.identity_map.values())
            if pause.enabled and edited and not self.info.get('test_commit_paused'):
                self.info['test_commit_paused']=True
                pause.ready.set();assert pause.release.wait(8)
            super().commit()
    app=FastAPI();app.include_router(auth_router.router,prefix='/api/auth');app.include_router(router.router,prefix='/api/invoice');register_portal_error_handler(app)
    @event.listens_for(HttpSession, 'after_begin')
    def observe_connection(db, transaction, connection):
        started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def database():
        with HttpSession(ctx.engine,expire_on_commit=False) as db:
            yield db
    app.dependency_overrides[get_db]=database
    async def login(name):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://ark.example.test') as client:
            response=await client.post('/api/auth/login',json={'username':name,'password':password});assert response.status_code==200
            return response.json()['access_token']
    token=asyncio.run(login(username));admin_token=asyncio.run(login(admin_name))
    while not started.empty():started.get_nowait()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (Invoice,InvoiceItem,InvoiceSyncLog,Receipt,ReceiptIntent,InvoiceLinkedSync,OrderRequest,Revision,CommandReceipt,Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent))
    def prepare(entry):
        if entry=='normal':return '/api/invoice/invoices/'+str(invoice_id),deepcopy(body),'PUT'
        with Session(ctx.engine) as db:
            invoice=invoices.get_invoice(db,invoice_id);invoice.xiaoman_order_id='isolated-'+uuid4().hex;invoice.sync_status='synced';db.commit()
            expected=linked.edit_version(invoice)
        return '/api/invoice/invoices/'+str(invoice_id)+'/linked-sync',{'invoice':deepcopy(body),'request_key':uuid4().hex,'expected_version':expected},'POST'
    async def write(route,body,method,actor_token=token,*,drop_success=False):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='https://ark.example.test') as client:
            response=await client.request(method,route,json=body,headers={'Authorization':'Bearer '+actor_token})
            if drop_success and response.status_code==200:
                raise httpx.ReadError('Client discarded response after actual server commit')
            return response
    return SimpleNamespace(app=app,ctx=ctx,invoice_id=invoice_id,version=version,request_id=request_id,body=body,token=token,admin_token=admin_token,started=started,pause=pause,snapshot=snapshot,prepare=prepare,write=write)


