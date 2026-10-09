"""Receipt PATCH current principal and unlocked order/file evidence, actual JWT/MySQL."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import queue
import threading
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkRole
from app.core.time import beijing_today
from app.invoice.models import Invoice
from app.invoice.settlement_models import BatchAttachment
from app.semifinished.models import InvoiceAllocation
from app.invoice import okki_client
from app.receipt import attachments, remote
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401
from test_mysql_concurrency import wait_for_lock
from app.receipt.remote import order_snapshot as actual_order_snapshot


def path(c,label='victim'):return '/api/receipts/'+str(c.receipts[label])


def body(c,label='victim'):
    return {'version':1,'amount':'12.00','bank_charge':'1.00',
        'collection_date':beijing_today().isoformat(),'payment_type':'T/T',
        'remark':'Corrected payment','attachment_ids':[c.proofs['foreign' if label=='foreign' else 'own']]}


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_patch_actual_revocation_rejects_old_jwt(read_app,revoke):
    c=read_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else
            {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);response=client.patch(path(c),headers=owner,json=body(c))
        assert response.status_code==403,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.roles['write']]})
        response=client.patch(path(c),headers=owner,json=body(c));assert response.status_code==200,response.text
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['victim'])
            assert row.amount==Decimal('12.00') and row.bank_charge==Decimal('1.00')
            assert row.sync_status=='failed' and row.version==2 and row.remark=='Corrected payment'
            assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='edited')).all())==1
        before=read_snapshot(c);assert client.patch(path(c),headers=owner,json=body(c)).status_code==409
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('global_role',['all','super_admin'])
def test_patch_current_scope_removes_old_global_flags(read_app,global_role):
    c=read_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin'))
        change_user(client,c,root,{'role_ids':[role.id if global_role=='super_admin' else c.roles['all']]})
        owner=login(client,c,c.owner_name)
        change_user(client,c,root,{'role_ids':[c.roles['write'],c.roles['invoice:read_all']]})
        before=read_snapshot(c);response=client.patch(path(c,'foreign'),headers=owner,json=body(c,'foreign'))
        assert response.status_code==404,response.text
        assert read_snapshot(c)==before and c.io==[]
        assert client.patch(path(c),headers=owner,json=body(c)).status_code==200


def test_patch_old_no_action_token_uses_new_current_write(read_app):
    c=read_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name);change_user(client,c,root,{'role_ids':[c.roles['write']]})
        response=client.patch(path(c),headers=owner,json=body(c));assert response.status_code==200,response.text
        assert c.calls==[]


@pytest.mark.parametrize('state',['batch','deposit','uncertain','syncing','synced','remote_id','void','version'])
def test_patch_original_state_guards_before_io(read_app,state):
    c=read_app
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim'])
        if state=='batch':row.batch_id=c.batch_id
        elif state=='deposit':row.purpose='presale_deposit'
        elif state=='remote_id':row.xiaoman_receipt_id=str(999000000+row.id)
        elif state=='void':row.status='voided'
        elif state=='version':row.version=2
        else:row.sync_status=state
        db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.patch(path(c),headers=owner,json=body(c));assert result.status_code==409,result.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('phase',['order','types','storage'])
@pytest.mark.parametrize('revoke',['disabled','write'])
def test_patch_admin_can_revoke_during_each_unlocked_io(read_app,phase,revoke,monkeypatch):
    c=read_app;ready=threading.Event();release=threading.Event();hits=[]
    module,name=(remote,'order_snapshot') if phase=='order' else (remote,'receipt_types') if phase=='types' else (attachments,'path_for')
    original=getattr(module,name)
    def gated(*args,**kwargs):
        hits.append(phase);ready.set();assert release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(module,name,gated)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(client.patch,path(c),headers=owner,json=body(c))
            try:
                assert ready.wait(5)
                pool.submit(change_user,client,c,root,{'is_active':False} if revoke=='disabled' else
                    {'role_ids':[c.roles['read']]}).result(timeout=5)
                before=read_snapshot(c)
            finally:release.set()
            result=future.result(timeout=5)
        assert hits==[phase] and result.status_code==403,result.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('change',['owner','remote_id','invoice_amount','target_amount','cancelled','linked',
    'ledger','intent','allocation','attachment_other','attachment_batch','storage_key'])
def test_patch_rechecks_current_binding_balance_and_file_use(read_app,change,monkeypatch):
    c=read_app;ready=threading.Event();release=threading.Event();original=remote.order_snapshot
    def gated(*args,**kwargs):ready.set();assert release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(remote,'order_snapshot',gated)
    def mutate():
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id);row=db.get(Receipt,c.receipts['victim'])
            if change=='owner':invoice.sales_user_id=c.other_id
            elif change=='remote_id':invoice.xiaoman_order_id='999999'
            elif change=='invoice_amount':invoice.total_amount+=Decimal('1')
            elif change=='target_amount':row.amount+=Decimal('1')
            elif change=='cancelled':invoice.status='cancelled'
            elif change=='linked':invoice.linked_sync_id=999
            elif change=='ledger':db.get(Receipt,c.receipts['positive']).amount=Decimal('120')
            elif change=='intent':
                intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                intent.eligible=1;intent.status='ready';intent.amount=Decimal('125')
            elif change=='allocation':db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
            elif change=='attachment_other':
                proof=db.get(ReceiptAttachment,c.proofs['own']);proof.invoice_id=c.foreign_invoice_id;proof.receipt_id=c.receipts['foreign']
            elif change=='attachment_batch':db.add(BatchAttachment(batch_id=c.batch_id,attachment_id=c.proofs['own']))
            else:db.get(ReceiptAttachment,c.proofs['own']).storage_key=uuid4().hex+'.png'
            db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(client.patch,path(c),headers=owner,json=body(c))
            try:
                assert ready.wait(5);pool.submit(mutate).result(timeout=5);before=read_snapshot(c)
            finally:release.set()
            result=future.result(timeout=5)
        assert result.status_code==(404 if change=='owner' else 409),result.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('change',['ledger','intent','allocation'])
def test_patch_balance_related_reads_are_current_after_rr_invoice_wait(read_app,change,monkeypatch):
    c=read_app;ready=threading.Event();release=threading.Event();started=queue.Queue();original=remote.order_snapshot
    def gated(*args,**kwargs):ready.set();assert release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(remote,'order_snapshot',gated)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(client.patch,path(c),headers=owner,json=body(c))
            with Session(c.ctx.engine) as other:
                try:
                    assert ready.wait(5)
                    other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                    if change=='ledger':other.get(Receipt,c.receipts['positive']).amount=Decimal('120')
                    elif change=='intent':
                        intent=other.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                        intent.eligible=1;intent.status='ready';intent.amount=Decimal('125')
                    else:other.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                    other.flush();event.listen(c.ctx.engine,'before_cursor_execute',observe);release.set()
                    wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not future.done()
                    other.commit();before=read_snapshot(c);result=future.result(timeout=5)
                finally:
                    release.set();other.rollback()
                    if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert result.status_code==409,result.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('guard',['draft','armed','ready','removed','foreign_unbound','batch'])
def test_patch_preserves_existing_attachment_restrictions(read_app,guard):
    c=read_app;payload=body(c)
    with Session(c.ctx.engine) as db:
        if guard in ('draft','armed','ready'):
            intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
            intent.eligible=1;intent.status=guard;intent.amount=Decimal('10');payload['attachment_ids']=[c.proofs['intent']]
        elif guard=='removed':db.get(Receipt,c.receipts['victim']).attachment_ids=[]
        elif guard=='foreign_unbound':payload['attachment_ids']=[c.proofs['foreign_unbound']]
        else:payload['attachment_ids']=[c.proofs['batch']]
        db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.patch(path(c),headers=owner,json=payload);assert result.status_code==409,result.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


def test_patch_new_attachment_replaces_old_without_sending(read_app):
    c=read_app;payload=body(c);payload['attachment_ids']=[c.proofs['unbound']]
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);result=client.patch(path(c),headers=owner,json=payload)
        assert result.status_code==200,result.text
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);proof=db.get(ReceiptAttachment,c.proofs['unbound'])
        assert row.attachment_ids==[proof.id] and proof.invoice_id==row.invoice_id and proof.receipt_id==row.id
        assert row.sync_status=='failed' and row.version==2
        assert db.get(ReceiptAttachment,c.proofs['own']).receipt_id==row.id
        assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='edited')).all())==1
    assert c.calls==[]


@pytest.mark.parametrize('shape',['snapshot','binding','rows','row','types','provider'])
def test_patch_invalid_remote_evidence_is_safe(read_app,shape,monkeypatch):
    c=read_app;original=remote.order_snapshot;hits=[]
    def bad(db,target):
        hits.append(shape)
        if shape=='provider':raise okki_client.OkkiApiError('private-provider-body')
        if shape=='snapshot':return None
        data=original(db,target)
        if shape=='binding':data['invoice_binding']=[]
        elif shape=='rows':data['rows']=None
        elif shape=='row':data['rows']=[None]
        return data
    monkeypatch.setattr(remote,'order_snapshot',bad)
    if shape=='types':monkeypatch.setattr(remote,'receipt_types',lambda *args:None)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);result=client.patch(path(c),headers=owner,json=body(c))
        assert hits==[shape] and result.status_code==503,result.text
        assert 'private-' not in result.text and result.headers['cache-control']=='private, no-store'
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('payload',[None,[],"invalid"])
def test_patch_real_order_detail_parser_rejects_bad_shape(read_app,payload,monkeypatch):
    c=read_app;hits=[];monkeypatch.setattr(remote,'order_snapshot',actual_order_snapshot)
    def read(db,path,params):hits.append((path,params));return payload
    monkeypatch.setattr(remote,'read',read)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        with Session(c.ctx.engine) as db:order_id=db.get(Invoice,c.invoice_id).xiaoman_order_id
        result=client.patch(path(c),headers=owner,json=body(c))
        assert hits==[('/v1/invoices/order/info',{'order_id':order_id})]
        assert result.status_code==503 and result.headers['cache-control']=='private, no-store',result.text
        assert read_snapshot(c)==before and c.calls==[]


def test_patch_parallel_commands_apply_version_once(read_app,monkeypatch):
    c=read_app;ready=queue.Queue();release=threading.Event();original=remote.order_snapshot
    def gated(*args,**kwargs):ready.put(True);assert release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(remote,'order_snapshot',gated)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(client.patch,path(c),headers=owner,json=body(c));second=pool.submit(client.patch,path(c),headers=owner,json=body(c))
            try:assert ready.get(timeout=5) and ready.get(timeout=5)
            finally:release.set()
            responses=[first.result(timeout=5),second.result(timeout=5)]
        assert sorted(x.status_code for x in responses)==[200,409],[x.text for x in responses]
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);assert row.version==2 and row.amount==Decimal('12') and row.sync_status=='failed'
        assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='edited')).all())==1
    assert c.calls==[]


@pytest.mark.parametrize('stage',[1,2,3])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_patch_phase_commit_faults_preserve_original_facts(read_app,stage,timing,monkeypatch):
    c=read_app;hits=[];metadata=MetaData()
    token=Table('owned_edit_metadata',metadata,Column('id',Integer,primary_key=True),Column('value',String(32)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        connection.execute(token.delete());connection.execute(token.insert().values(id=1,value='original'))
    original=remote.order_snapshot
    def snapshot(db,target):
        db.execute(token.update().where(token.c.id==1).values(value='refreshed'));return original(db,target)
    monkeypatch.setattr(remote,'order_snapshot',snapshot)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        def fail(db):
            if any(isinstance(row,Receipt) and inspect(row).identity==(c.receipts['victim'],) for row in db.identity_map.values()):db.info['owned_edit_session']=True
            if db.info.get('owned_edit_session'):
                count=db.info.get('owned_edit_commit',0)+1;db.info['owned_edit_commit']=count
                if count==stage and not hits:
                    hits.append((stage,timing));raise OperationalError('private-edit-query',{},Exception('private-edit-ack'))
        event.listen(Session,timing,fail)
        try:result=client.patch(path(c),headers=owner,json=body(c))
        finally:event.remove(Session,timing,fail)
        assert hits==[(stage,timing)] and result.status_code==503,result.text
        assert 'private-' not in result.text and result.headers['cache-control']=='private, no-store'
        with c.ctx.engine.connect() as connection:value=connection.scalar(select(token.c.value).where(token.c.id==1))
        assert value==('original' if stage==1 or (stage==2 and timing=='before_commit') else 'refreshed')
        committed=stage==3 and timing=='after_commit'
        if not committed:assert read_snapshot(c)==before
        else:
            with Session(c.ctx.engine) as db:
                row=db.get(Receipt,c.receipts['victim']);assert row.sync_status=='failed' and row.amount==Decimal('12') and row.version==2
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='edited')).all())==1
        result=client.patch(path(c),headers=owner,json=body(c));assert result.status_code==(409 if committed else 200),result.text
        assert c.calls==[]


def test_patch_mixed_batch_preserves_full_financial_scope_404(read_app):
    c=read_app
    with Session(c.ctx.engine) as db:
        db.get(Receipt,c.receipts['victim']).batch_id=c.batch_id
        db.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id;db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.patch(path(c),headers=owner,json=body(c));assert result.status_code==404,result.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


def test_patch_rechecks_intent_screenshot_occupation_after_io(read_app,monkeypatch):
    c=read_app;ready=threading.Event();release=threading.Event();original=remote.order_snapshot
    def gated(*args,**kwargs):ready.set();assert release.wait(10);return original(*args,**kwargs)
    monkeypatch.setattr(remote,'order_snapshot',gated)
    def occupy():
        with Session(c.ctx.engine) as db:
            intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
            intent.eligible=1;intent.status='armed';intent.amount=Decimal('10');intent.attachment_ids=[c.proofs['own']];db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(client.patch,path(c),headers=owner,json=body(c))
            try:assert ready.wait(5);pool.submit(occupy).result(timeout=5);before=read_snapshot(c)
            finally:release.set()
            result=future.result(timeout=5)
        assert result.status_code==409,result.text
        assert read_snapshot(c)==before and c.calls==[]


def test_patch_bad_storage_configuration_is_safe_no_store(read_app,monkeypatch):
    from app.receipt import storage_proxy
    c=read_app;c.app.settings.RECEIPT_STORAGE_PROXY_URL='http://invalid.example.test'
    monkeypatch.setattr(storage_proxy,'get_settings',lambda:c.app.settings)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.patch(path(c),headers=owner,json=body(c))
        assert result.status_code==503,result.text
        assert result.headers.get('cache-control')=='private, no-store'
        assert read_snapshot(c)==before and c.calls==[]
