"""Current employee read rights with actual JWT/main/MySQL; provider IO synthetic."""
from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import uuid4
import hashlib
import io

import pytest
from PIL import Image
from sqlalchemy import Column, MetaData, Table, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.invoice.settlement_models import BatchAttachment, ReceiptBatch
from app.receipt import attachments, remote, storage_proxy
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user, snapshot  # noqa: F401


@pytest.fixture
def read_app(receipt_app, monkeypatch, tmp_path):
    c=receipt_app
    metadata=MetaData()
    for model in (BatchAttachment, ReceiptBatch, InvoiceAllocation):
        Table(model.__tablename__,metadata,*(Column(column.name,column.type,
            primary_key=column.primary_key,nullable=False if column.primary_key else True)
            for column in model.__table__.columns))
    metadata.create_all(c.ctx.engine)
    image=io.BytesIO();Image.new('RGB',(2,2),'white').save(image,format='PNG')
    c.image=image.getvalue();c.proofs={};c.io=[]
    storage=tmp_path/'proofs';storage.mkdir()
    monkeypatch.setattr(attachments,'STORAGE_ROOT',storage)
    # Actual local path validation/file streaming; cloud and proxy are controlled.
    monkeypatch.setattr(attachments.cloud_files,'managed',lambda domain:False)
    def proxy(*args,**kwargs):c.io.append('proxy');return None
    monkeypatch.setattr(storage_proxy,'forward',proxy)
    def payment_types(db):c.io.append('types');return ['T/T']
    def order_snapshot(db,invoice):
        c.io.append(('balance',invoice.id))
        return {'rows':[],'exchange_rate':725,'invoice_binding':remote.invoice_binding(invoice)}
    monkeypatch.setattr(remote,'receipt_types',payment_types)
    monkeypatch.setattr(remote,'order_snapshot',order_snapshot)
    with Session(c.ctx.engine) as db:
        for code in ('invoice:read','invoice:write','invoice:sync','invoice:read_all','receipt:admin'):
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                module,action=code.split(':')
                permission=ArkPermission(code=code,module=module,action=action,label=code,
                    kind='data' if action=='read_all' else 'action',is_legacy=False,sort=1)
                db.add(permission);db.flush()
            role=ArkRole(name='receipt-read-'+uuid4().hex,label=code)
            db.add(role);db.flush();c.roles[code]=role.id
            db.add(ArkRolePermission(role_id=role.id,permission_id=permission.id))
        for identity in (c.invoice_id,c.foreign_invoice_id):
            invoice=db.get(Invoice,identity)
            invoice.sync_status='synced';invoice.status='synced'
            invoice.xiaoman_order_id=str(identity+1000000)
            for receipt in db.scalars(select(Receipt).where(Receipt.invoice_id==identity)):
                receipt.customer_id=invoice.customer_id
        batch=ReceiptBatch(batch_no='OWNED-'+uuid4().hex,customer_id='test',currency='USD',
            gross_amount=10,bank_charge_total=0,status='active',request_key=uuid4().hex,
            request_hash='b'*64,created_by=c.ctx.actor)
        db.add(batch);db.flush();c.batch_id=batch.id
        db.get(Receipt,c.receipts['positive']).batch_id=batch.id
        resources=(('unbound',None,None,c.ctx.actor),
            ('foreign_unbound',None,None,c.other_id),
            ('own',c.invoice_id,c.receipts['victim'],c.other_id),
            ('foreign',c.foreign_invoice_id,c.receipts['foreign'],c.other_id),
            ('intent',c.invoice_id,None,c.ctx.actor),
            ('foreign_intent',c.foreign_invoice_id,None,c.other_id),
            ('batch',None,None,c.other_id))
        for label,invoice_id,receipt_id,actor in resources:
            identity=uuid4().hex;c.proofs[label]=identity
            row=ReceiptAttachment(id=identity,filename='proof.png',storage_key=identity+'.png',
                content_type='image/png',size=len(c.image),sha256=hashlib.sha256(c.image).hexdigest(),
                created_by=actor,invoice_id=invoice_id,receipt_id=receipt_id)
            db.add(row);(storage/row.storage_key).write_bytes(c.image)
            if receipt_id:db.get(Receipt,receipt_id).attachment_ids=[identity]
        # Portal approval no longer creates this intent; seed it the way the
        # existing Ark invoice-edit entry would.
        db.add(ReceiptIntent(invoice_id=c.invoice_id,eligible=1,status='draft',
            created_by=c.ctx.actor,attachment_ids=[c.proofs['intent']]))
        db.add(ReceiptIntent(invoice_id=c.foreign_invoice_id,eligible=0,status='draft',
            created_by=c.other_id,attachment_ids=[c.proofs['foreign_intent']]))
        db.add(BatchAttachment(batch_id=batch.id,attachment_id=c.proofs['batch']))
        db.commit()
    return c


def read_snapshot(c):
    # Explicit finite financial/association snapshot, not all database tables.
    base=snapshot(c)
    with Session(c.ctx.engine) as db:
        extra=tuple(tuple(db.execute(select(*model.__table__.columns)
            .order_by(*model.__table__.primary_key.columns)).all())
            for model in (BatchAttachment,ReceiptBatch,InvoiceAllocation,InvoiceDelegateGrant))
    return base+extra


def proof_path(c,label):return '/api/receipts/attachments/'+c.proofs[label]
def balance_path(c,foreign=False):return '/api/receipts/order-balance/'+str(c.foreign_invoice_id if foreign else c.invoice_id)


def assert_image(response,c):
    assert response.status_code==200,response.text
    assert response.content==c.image
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['x-content-type-options']=='nosniff'


@pytest.mark.parametrize('revocation',['disabled','roles'])
def test_actual_revocation_denies_auxiliary_reads_before_io(read_app,revocation):
    c=read_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        assert client.get('/api/receipts/types',headers=owner).status_code==200
        balance=client.get(balance_path(c),headers=owner)
        assert balance.status_code==200,balance.text
        assert balance.json()['data']['remaining_amount']=='108.00'
        for label in ('unbound','own','intent','batch'):assert_image(client.get(proof_path(c,label),headers=owner),c)
        assert c.io.count('types')==1 and c.io.count(('balance',c.invoice_id))==1 and c.io.count('proxy')==4
        change_user(client,c,root,{'is_active':False} if revocation=='disabled' else {'role_ids':[]})
        before=read_snapshot(c);c.io.clear()
        paths=('/api/receipts/types',balance_path(c),*(proof_path(c,label) for label in ('unbound','own','intent','batch')))
        denied={path:client.get(path,headers=owner).status_code for path in paths}
        assert denied=={path:403 for path in paths},denied
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.roles['both']]})
        assert_image(client.get(proof_path(c,'own'),headers=owner),c)
        assert client.get(balance_path(c),headers=owner).status_code==200


@pytest.mark.parametrize('global_role',['all','super_admin'])
def test_current_receipt_scope_denies_foreign_balance_and_proof(read_app,global_role):
    c=read_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:
            role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin'))
            global_id=role.id if global_role=='super_admin' else c.roles['all']
        change_user(client,c,root,{'role_ids':[global_id]})
        owner=login(client,c,c.owner_name)
        assert client.get(balance_path(c,True),headers=owner).status_code==200
        assert_image(client.get(proof_path(c,'foreign'),headers=owner),c)
        change_user(client,c,root,{'role_ids':[c.roles['both'],c.roles['invoice:read_all']]})
        before=read_snapshot(c);c.io.clear()
        for path in (balance_path(c,True),proof_path(c,'foreign')):
            response=client.get(path,headers=owner);assert response.status_code==404,response.text
        assert c.io==[] and read_snapshot(c)==before
        assert_image(client.get(proof_path(c,'own'),headers=owner),c)


@pytest.mark.parametrize('role',['read','write','receipt:admin','invoice:read','invoice:write','invoice:sync'])
def test_new_current_action_grant_preserves_original_or_policies(read_app,role):
    c=read_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.roles['invoice:read_all']]})
        owner=login(client,c,c.owner_name)  # Token has only data scope, no action.
        for path in ('/api/receipts/types',balance_path(c),proof_path(c,'own')):
            assert client.get(path,headers=owner).status_code==403
        change_user(client,c,root,{'role_ids':[c.roles[role]]})
        assert client.get('/api/receipts/types',headers=owner).status_code==200
        assert_image(client.get(proof_path(c,'unbound'),headers=owner),c)
        assert client.get(proof_path(c,'foreign_unbound'),headers=owner).status_code==404
        assert_image(client.get(proof_path(c,'intent'),headers=owner),c)
        receipt_action=not role.startswith('invoice:')
        response=client.get(balance_path(c),headers=owner)
        assert response.status_code==(200 if receipt_action else 403),response.text
        response=client.get(proof_path(c,'own'),headers=owner)
        if receipt_action:assert_image(response,c)
        else:assert response.status_code==404,response.text
        response=client.get(proof_path(c,'batch'),headers=owner)
        if receipt_action:assert_image(response,c)
        else:assert response.status_code==404,response.text
        if not receipt_action:
            with Session(c.ctx.engine) as db:
                row=db.get(ReceiptAttachment,c.proofs['intent']);row.receipt_id=c.receipts['victim']
                db.get(Receipt,c.receipts['victim']).attachment_ids=[c.proofs['own'],row.id]
                db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id)).status='converted'
                db.commit()
            before=read_snapshot(c);c.io.clear()
            assert client.get(proof_path(c,'intent'),headers=owner).status_code==404
            assert c.io==[] and read_snapshot(c)==before
        assert c.calls==[]


def test_current_invoice_delegate_loss_and_batch_scope(read_app):
    c=read_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.roles['invoice:read']]})
        owner=login(client,c,c.owner_name)
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.foreign_invoice_id);invoice.created_by=c.ctx.actor
            grant=InvoiceDelegateGrant(sales_user_id=c.other_id,delegate_user_id=c.ctx.actor,created_by=c.ctx.actor)
            db.add(grant);db.flush();grant_id=grant.id;db.commit()
        assert_image(client.get(proof_path(c,'foreign_intent'),headers=owner),c)
        with Session(c.ctx.engine) as db:db.delete(db.get(InvoiceDelegateGrant,grant_id));db.commit()
        c.io.clear();before=read_snapshot(c)
        assert client.get(proof_path(c,'foreign_intent'),headers=owner).status_code==404
        assert c.io==[] and read_snapshot(c)==before
        change_user(client,c,root,{'role_ids':[c.roles['both']]})
        assert_image(client.get(proof_path(c,'batch'),headers=owner),c)
        with Session(c.ctx.engine) as db:
            db.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id;db.commit()
        c.io.clear();before=read_snapshot(c)
        assert client.get(proof_path(c,'batch'),headers=owner).status_code==404
        assert c.io==[] and read_snapshot(c)==before
        assert_image(client.get(proof_path(c,'own'),headers=owner),c)


@pytest.mark.parametrize('target',['types','balance','proof'])
def test_auxiliary_read_auth_query_failure_is_safe_and_precedes_io(read_app,target):
    c=read_app;fired=[];marker='private-driver-details'
    path='/api/receipts/types' if target=='types' else balance_path(c) if target=='balance' else proof_path(c,'own')
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);c.io.clear()
        def failure(connection,cursor,statement,parameters,context,executemany):
            if 'FROM ark_users' in statement and not fired:
                fired.append(target);raise OperationalError('private-auth-query',{},Exception(marker))
        event.listen(c.ctx.engine,'before_cursor_execute',failure)
        try:response=client.get(path,headers=owner)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',failure)
        assert fired==[target]
        assert response.status_code==503,response.text
        assert marker not in response.text and 'private-auth-query' not in response.text
        assert response.headers['cache-control']=='private, no-store'
        assert c.io==[] and c.calls==[] and read_snapshot(c)==before
        assert client.get(path,headers=owner).status_code==200


@pytest.mark.parametrize('target',['types','balance','proof'])
def test_slow_read_io_does_not_hold_authority_lock(read_app,target,monkeypatch):
    c=read_app;started=threading.Event();release=threading.Event()
    module,name=(remote,'receipt_types') if target=='types' else (remote,'order_snapshot') if target=='balance' else (storage_proxy,'forward')
    original=getattr(module,name)
    def slow(*args,**kwargs):
        started.set();assert release.wait(timeout=10),'Read IO was never released'
        return original(*args,**kwargs)
    path='/api/receipts/types' if target=='types' else balance_path(c) if target=='balance' else proof_path(c,'own')
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        before=read_snapshot(c);monkeypatch.setattr(module,name,slow)
        with ThreadPoolExecutor(max_workers=2) as pool:
            response=pool.submit(client.get,path,headers=owner)
            try:
                assert started.wait(timeout=5)
                revoked=pool.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,json={'is_active':False})
                result=revoked.result(timeout=5)
                assert result.status_code==200,result.text
                assert not response.done()  # Actual admin commits while IO still gated.
            finally:release.set()
            # These ordinary reads authorize at first DB read. No response-time
            # reauthorization, token refresh, physical proxy or cancellation proof.
            assert response.result(timeout=5).status_code==200
        monkeypatch.setattr(module,name,original)
        assert client.get(path,headers=owner).status_code==403
        assert read_snapshot(c)==before and c.calls==[]
