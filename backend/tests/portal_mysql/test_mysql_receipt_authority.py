"""Actual employee HTTP and local ledger authorization on owned MySQL.

Portal lineage is real; upstream receipt columns are synthetic, not migrations.
"""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import secrets

import httpx
import pytest
from concurrent.futures import ThreadPoolExecutor
import queue
import threading

from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.auth import router as employee_router, service as employee_auth, utils
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkRolePermission, ArkUserRole
from app.core.time import beijing_now, beijing_today
from app.invoice.models import Invoice, InvoiceItem
from app.portal import approval_service, authority as portal_authority
from app.portal.models import Conversion, Publication, OrderRequest, CommandReceipt, OutboxEvent
from app.receipt import service as receipts
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptLog, ReceiptIntent
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_services import accepted_request
from test_mysql_concurrency import wait_for_lock
from test_mysql_application_trade import AuthHeaders


class ReceiptApplication:
    def __repr__(self):return '<Owned receipt application>'


def _has_unique_remote_mapping(indexes):
    groups={}
    for row in indexes:
        groups.setdefault(row['Key_name'],[]).append(row)
    return any(len(rows)==1 and rows[0]['Seq_in_index']==1
        and rows[0]['Column_name']=='xiaoman_receipt_id'
        and rows[0]['Non_unique']==0 and rows[0]['Sub_part'] is None
        for rows in groups.values())


@pytest.fixture
def receipt_app(assembled, service_schema, monkeypatch):
    a=assembled;c=ReceiptApplication();c.app=a;c.ctx=a.ctx
    a.settings.JWT_SECRET_KEY=secrets.token_urlsafe(48)
    for module in (employee_router,employee_auth,utils):
        monkeypatch.setattr(module,'settings',a.settings)
    # This is upstream schema scaffolding. Full receipt migration/FK evidence is
    # outside these authorization tests, just as in service_schema.
    metadata=MetaData()
    for model in (Receipt,ReceiptAttachment,ReceiptLog):
        Table(model.__tablename__,metadata,*(Column(column.name,column.type,
            primary_key=column.primary_key,nullable=False if column.primary_key else True)
            for column in model.__table__.columns))
    metadata.create_all(a.ctx.engine)
    # Mirror migration156's global remote mapping constraint before any receipt
    # fixture rows are seeded; historical rows remain across cases.
    with a.ctx.engine.begin() as connection:
        indexes=connection.execute(text('SHOW INDEX FROM ark_receipts')).mappings().all()
        if not _has_unique_remote_mapping(indexes):
            connection.execute(text('ALTER TABLE ark_receipts ADD UNIQUE INDEX uq_owned_receipt_remote (xiaoman_receipt_id)'))
    password=secrets.token_urlsafe(24);c.password=password
    with Session(a.ctx.engine) as db:
        permission_ids={}
        for code in ('receipt:read','receipt:write','receipt:read_all'):
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                module,action=code.split(':')
                permission=ArkPermission(code=code,module=module,action=action,label=code,
                    kind='data' if action=='read_all' else 'action',is_legacy=False,sort=1)
                db.add(permission);db.flush()
            permission_ids[code]=permission.id
        c.roles={}
        for name,codes in {'both':('receipt:read','receipt:write'),
            'read':('receipt:read',),'write':('receipt:write',),
            'all':('receipt:read','receipt:write','receipt:read_all')}.items():
            role=ArkRole(name='receipt-'+name+'-'+uuid4().hex[:12],label='Owned receipt '+name)
            db.add(role);db.flush();c.roles[name]=role.id
            for code in codes:db.add(ArkRolePermission(role_id=role.id,permission_id=permission_ids[code]))
        db.add(ArkUserRole(user_id=a.ctx.actor,role_id=c.roles['both']))
        owner=db.get(ArkUser,a.ctx.actor);root=db.get(ArkUser,a.ctx.admin)
        owner.password_hash=root.password_hash=utils.hash_password(password)
        c.owner_name,c.root_name=owner.username,root.username
        c.sales_role=service_schema.sales_role
        other=ArkUser(username='receipt-other-'+uuid4().hex[:12],real_name='Other salesperson',
            password_hash=utils.hash_password(password),is_active=True)
        db.add(other);db.flush();c.other_id=other.id
        db.commit()
    request_id,body=accepted_request(a.ctx)
    with Session(a.ctx.engine) as db:
        approval_service.approve(db,a.ctx.actor,request_id,3,body);db.commit()
        order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
        c.invoice_id=order.invoice_id
        foreign=Invoice(invoice_no='PI-OTHER-'+uuid4().hex,order_type='stock',
            invoice_date=beijing_today(),customer_name='Other buyer',customer_id=str(c.other_id),
            sales_user_id=c.other_id,currency='USD',total_amount=Decimal('128.00'),
            shipping_fee=Decimal('45.00'),internal_accessory=Decimal('2.00'),
            surcharge_amount=Decimal('0.00'),product_amount=Decimal('81.00'),source_type='manual')
        db.add(foreign);db.flush();c.foreign_invoice_id=foreign.id
        c.receipts={}
        for label,invoice_id,actor in (('victim',c.invoice_id,a.ctx.actor),
            ('positive',c.invoice_id,a.ctx.actor),('foreign',foreign.id,c.other_id)):
            row=Receipt(receipt_no='HK-'+uuid4().hex,invoice_id=invoice_id,source='manual',
                request_key=uuid4().hex,request_hash='a'*64,amount=Decimal('10.00'),currency='USD',
                collection_date=beijing_today(),payment_type='bank',bank_charge=Decimal('0.00'),
                customer_id=str(actor),attachment_ids=[],created_by=actor,status='active',sync_status='pending')
            db.add(row);db.flush();c.receipts[label]=row.id
        db.commit()
    c.calls=[]
    def forbidden(*args,**kwargs):
        c.calls.append('HTTP');raise AssertionError('Unexpected external receipt HTTP')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden)
    return c


def login(client,c,name):
    response=client.post('/api/auth/login',json={'username':name,'password':c.password})
    assert response.status_code==200
    return AuthHeaders(Authorization='Bearer '+response.json()['access_token'])


def change_user(client,c,root,body):
    response=client.put('/api/auth/users/'+str(c.ctx.actor),headers=root,json=body)
    assert response.status_code==200,response.text


def receipt_path(c,label='victim'):
    return '/api/receipts/'+str(c.receipts[label])


def snapshot(c):
    with Session(c.ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (Receipt,ReceiptLog,ReceiptAttachment,ReceiptIntent,Invoice,InvoiceItem,
                Conversion,Publication,OrderRequest,CommandReceipt,OutboxEvent))


def read_all(client,c,owner,expected):
    for path in ('/api/receipts',receipt_path(c),'/api/receipts/order-options'):
        response=client.get(path,headers=owner)
        assert response.status_code==expected,(path,response.status_code,response.text)


@pytest.mark.parametrize('revocation',['disabled','all_roles','write'])
def test_receipt_old_jwt_is_rejected_after_actual_admin_revocation(receipt_app,revocation):
    c=receipt_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        read_all(client,c,owner,200)
        positive=client.post(receipt_path(c,'positive')+'/void',headers=owner,json={'reason':'Valid local cancellation'})
        assert positive.status_code==200,positive.text
        body=({'is_active':False} if revocation=='disabled' else
            {'role_ids':[]} if revocation=='all_roles' else {'role_ids':[c.sales_role,c.roles['read']]})
        change_user(client,c,root,body);before=snapshot(c)
        read_all(client,c,owner,200 if revocation=='write' else 403)
        denied=client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'Old JWT must not authorize cancellation'})
        assert denied.status_code==403,denied.text
        assert snapshot(c)==before and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.sales_role,c.roles['both']]})
        read_all(client,c,owner,200)
        restored=client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'Restored current permission'})
        assert restored.status_code==200,restored.text
        with Session(c.ctx.engine) as db:
            assert db.get(Receipt,c.receipts['victim']).status=='voided'
            assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==c.receipts['victim'],ReceiptLog.action=='voided')).all())==1
            assert db.get(Invoice,c.invoice_id).portal_document_version==1
            assert db.scalar(select(Publication).join(Conversion,Conversion.request_id==Publication.request_id)
                .where(Conversion.invoice_id==c.invoice_id)).status=='published'


def test_receipt_removed_read_retains_write_or_and_own_scope(receipt_app):
    c=receipt_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['write']]})
        read_all(client,c,owner,200)
        before=snapshot(c)
        for method,path in (('GET',receipt_path(c,'foreign')),('POST',receipt_path(c,'foreign')+'/void')):
            response=client.request(method,path,headers=owner,json={'reason':'Foreign valid command'} if method=='POST' else None)
            assert response.status_code==404,response.text
        assert snapshot(c)==before
        options=client.get('/api/receipts/order-options',headers=owner).json()['data']
        assert c.foreign_invoice_id not in [item['id'] for item in options['items']]
        response=client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'Current write permission'})
        assert response.status_code==200,response.text


@pytest.mark.parametrize('global_role',['all','super_admin'])
def test_receipt_old_global_scope_is_removed_live(receipt_app,global_role):
    c=receipt_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:
            role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin'))
            global_id=role.id if global_role=='super_admin' else c.roles['all']
        change_user(client,c,root,{'role_ids':[c.sales_role,global_id]})
        owner=login(client,c,c.owner_name)
        assert client.get(receipt_path(c,'foreign'),headers=owner).status_code==200
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both']]})
        before=snapshot(c)
        assert client.get(receipt_path(c,'foreign'),headers=owner).status_code==404
        assert client.post(receipt_path(c,'foreign')+'/void',headers=owner,json={'reason':'Old global scope'}).status_code==404
        listed=client.get('/api/receipts',headers=owner).json()['data']
        assert c.receipts['foreign'] not in [item['id'] for item in listed['items']]
        assert snapshot(c)==before
        assert client.get(receipt_path(c),headers=owner).status_code==200
        assert client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'Current own scope'}).status_code==200



def test_old_identity_token_can_use_newly_granted_current_receipt_permissions(receipt_app):
    c=receipt_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role]})
        owner=login(client,c,c.owner_name)  # Token has no receipt action claim.
        read_all(client,c,owner,403)
        before=snapshot(c)
        assert client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'No current action'}).status_code==403
        assert snapshot(c)==before
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both']]})
        read_all(client,c,owner,200)
        assert client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'New current grant'}).status_code==200


@pytest.mark.parametrize('state',[
    {'sync_status':'pending'}, {'sync_status':'failed'},
    {'sync_status':'uncertain'}, {'sync_status':'syncing'}, {'sync_status':'synced'},
    {'xiaoman_receipt_id':'123456'}, {'purpose':'presale_deposit'}, {'batch_id':999},
    {'status':'voided'},
])
def test_actual_local_void_preserves_original_financial_state_guards(receipt_app,state):
    c=receipt_app
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim'])
        for name,value in state.items():setattr(row,name,value)
        db.commit()
    allowed=state in ({'sync_status':'pending'},{'sync_status':'failed'})
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=snapshot(c)
        response=client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'Preserve financial safety'})
        assert response.status_code==(200 if allowed else 409),response.text
        if not allowed:assert snapshot(c)==before
        with Session(c.ctx.engine) as db:
            assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==c.receipts['victim'],ReceiptLog.action=='voided')).all())==(1 if allowed else 0)
            assert db.get(Invoice,c.invoice_id).portal_document_version==1
        assert c.calls==[]


@pytest.mark.parametrize('caller',['read','dirty','new','flushed'])
def test_public_void_rejects_caller_transaction_without_committing_or_expiring_it(receipt_app,caller):
    c=receipt_app;before=snapshot(c)
    with Session(c.ctx.engine) as db:
        if caller=='new':
            pending=Receipt(receipt_no='Caller uncommitted');db.add(pending)
        else:
            invoice=db.get(Invoice,c.invoice_id)
            if caller in {'dirty','flushed'}:
                invoice.remark='Caller pending commercial edit'
                if caller=='flushed':db.flush()
        try:
            with pytest.raises(HTTPException) as caught:
                receipts.void(db,c.receipts['victim'],{'sub':str(c.ctx.actor)},'Must preserve caller work')
            assert caught.value.status_code==409 and db.in_transaction()
            if caller=='dirty':assert invoice in db.dirty and invoice.remark=='Caller pending commercial edit'
            if caller=='new':assert pending in db.new
            assert snapshot(c)==before
        finally:db.rollback()
    assert snapshot(c)==before


def test_storefront_off_keeps_current_permissions_and_ordinary_local_void(receipt_app,monkeypatch):
    c=receipt_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        # Both main Settings and the exact upstream mutation settings are OFF.
        c.app.settings.PORTAL_ENABLED=False
        monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
        assert portal_authority.get_settings().PORTAL_ENABLED is False
        read_all(client,c,owner,200)
        response=client.post(receipt_path(c,'positive')+'/void',headers=owner,json={'reason':'OFF legitimate local cancellation'})
        assert response.status_code==200,response.text
        change_user(client,c,root,{'is_active':False})
        before=snapshot(c);read_all(client,c,owner,403)
        assert client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'OFF committed revocation'}).status_code==403
        assert snapshot(c)==before
        change_user(client,c,root,{'is_active':True})
        assert client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'OFF current actor restored'}).status_code==200
        with Session(c.ctx.engine) as db:
            assert db.get(Invoice,c.invoice_id).portal_document_version==1
    # This is committed revocation in the new schema, not OFF revocation fencing
    # or proof that a current artifact can run with historical pre-172 schema.


@pytest.mark.parametrize('enabled',[True,False])
@pytest.mark.parametrize('commit',[True,False])
def test_local_void_holds_actual_barrier_until_commit_or_rollback(receipt_app,commit,enabled,monkeypatch):
    c=receipt_app;started=queue.Queue()
    c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as first:
            row,_=receipts.void(first,c.receipts['victim'],{'sub':str(c.ctx.actor)},'Owned first transaction')
            first.flush()
            def observe(connection,cursor,statement,parameters,context,executemany):
                if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
                    started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
            event.listen(c.ctx.engine,'before_cursor_execute',observe)
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,json={'is_active':False})
                try:
                    wait_for_lock(c.ctx.engine,started.get(timeout=5))
                    assert not future.done()
                    if commit:first.commit()
                    else:first.rollback()
                    response=future.result(timeout=5)
                    assert response.status_code==200,response.text
                finally:
                    first.rollback();event.remove(c.ctx.engine,'before_cursor_execute',observe)
            with Session(c.ctx.engine) as db:
                assert db.get(Receipt,c.receipts['victim']).status==('voided' if commit else 'active')
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==c.receipts['victim'],ReceiptLog.action=='voided')).all())==int(commit)
                assert not db.get(ArkUser,c.ctx.actor).is_active


@pytest.mark.parametrize('enabled',[True,False])
def test_actual_admin_revocation_commits_before_waiting_http_void(receipt_app,enabled,monkeypatch):
    c=receipt_app;ready=threading.Event();release=threading.Event();started=queue.Queue()
    c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    with c.app.client() as client:
        root=login(client,c,c.root_name);owner=login(client,c,c.owner_name);before=snapshot(c)
        def hold_commit(db):
            if any(isinstance(row,ArkUser) and row.id==c.ctx.actor and not row.is_active for row in db.dirty):
                ready.set()
                assert release.wait(10),'Owned admin commit was not released'
        def observe(connection,cursor,statement,parameters,context,executemany):
            if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
                started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
        event.listen(Session,'before_commit',hold_commit)
        with ThreadPoolExecutor(max_workers=2) as executor:
            admin=executor.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,json={'is_active':False})
            try:
                assert ready.wait(5)
                event.listen(c.ctx.engine,'before_cursor_execute',observe)
                action=executor.submit(client.post,receipt_path(c)+'/void',headers=owner,json={'reason':'Waiting after real revocation'})
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                release.set()
                assert admin.result(timeout=5).status_code==200
                denied=action.result(timeout=5);assert denied.status_code==403,denied.text
            finally:
                release.set();event.remove(Session,'before_commit',hold_commit)
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):
                    event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert snapshot(c)==before



@pytest.mark.parametrize('method,stage,diagnostic',[
    ('GET','employee',None), ('POST','barrier',None), ('POST','employee',None),
    ('POST','lineage',None), ('POST','receipt',None),
    ('POST','employee','logger'), ('POST','employee','stdout'),
])
def test_authorization_database_failure_is_safe_503_and_recoverable(receipt_app,method,stage,diagnostic,monkeypatch):
    c=receipt_app;marker='owned-driver-detail-must-not-leak';fired=[]
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        assert client.get(receipt_path(c),headers=owner).status_code==200
        before=snapshot(c)
        from app.receipt import authority
        diagnostic_hits=[]
        def broken_diagnostic(*args,**kwargs):
            diagnostic_hits.append(diagnostic)
            if diagnostic=='stdout':raise BrokenPipeError('Owned diagnostic failure')
            raise RuntimeError('Owned diagnostic failure')
        if diagnostic=='logger':monkeypatch.setattr(authority.logger,'warning',broken_diagnostic)
        elif diagnostic=='stdout':monkeypatch.setattr(authority,'print',broken_diagnostic,raising=False)
        def fail(connection,cursor,statement,parameters,context,executemany):
            targets={'employee':'FROM ark_users','barrier':'ark_order_portal_auth_barriers',
                'lineage':'ark_order_portal_conversions','receipt':'SELECT ark_receipts.invoice_id'}
            if not fired and targets[stage] in statement:
                fired.append(stage)
                # Actual SQLAlchemy query event; no physical MySQL outage is
                # claimed. This checks response classification/rollback only.
                raise OperationalError('owned-auth-query',{},Exception(marker))
        event.listen(c.ctx.engine,'before_cursor_execute',fail)
        try:
            path=receipt_path(c)+('/void' if method=='POST' else '')
            response=client.request(method,path,headers=owner,json={'reason':'Safe authorization failure'} if method=='POST' else None)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',fail)
        assert fired==[stage]
        assert diagnostic_hits==([diagnostic] if diagnostic else [])
        assert response.status_code==503,response.text
        assert marker not in response.text and 'owned-auth-query' not in response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before
        assert client.get(receipt_path(c),headers=owner).status_code==200
        assert client.post(receipt_path(c)+'/void',headers=owner,json={'reason':'Recovered current authorization'}).status_code==200
