"""Actual employee receipt creation, current authority and original idempotency."""
from uuid import uuid4
from decimal import Decimal
import pytest
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import Column, Integer, MetaData, String, Table, event, text
from sqlalchemy.exc import OperationalError
from app.invoice import okki_client
from app.invoice.models import Invoice
from app.invoice.settlement_models import BatchAttachment
from app.receipt import attachments, create_service, edit_service, remote
from app.receipt.models import ReceiptAttachment, ReceiptIntent
from app.receipt.schemas import ReceiptCreate
from app.semifinished.models import InvoiceAllocation
from test_mysql_concurrency import wait_for_lock
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.models import ArkRole
from app.receipt.models import Receipt, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401


@pytest.fixture
def create_app(read_app):
    # The upstream fixture is thin; explicitly reproduce the real key constraint.
    with read_app.ctx.engine.begin() as connection:
        if not connection.execute(text("SHOW INDEX FROM ark_receipts WHERE Key_name='uq_owned_create_key'")).first():
            connection.execute(text('ALTER TABLE ark_receipts ADD UNIQUE KEY uq_owned_create_key(request_key)'))
    return read_app


def body(client,c,headers,foreign=False):
    invoice_id=c.foreign_invoice_id if foreign else c.invoice_id
    response=client.get('/api/receipts/order-balance/'+str(invoice_id),headers=headers)
    assert response.status_code==200,response.text
    return {'invoice_id':invoice_id,'request_key':uuid4().hex,'amount':'10','bank_charge':'2',
        'collection_date':'2026-10-06','payment_type':'T/T','remark':'Owned create test',
        'attachment_ids':[c.proofs['foreign_intent' if foreign else 'unbound']],
        'balance_version':response.json()['data']['version']}


def created(c,payload,response):
    assert response.status_code==200,response.text
    identity=response.json()['data']['id']
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,identity)
        assert row.invoice_id==payload['invoice_id'] and row.request_key==payload['request_key']
        assert row.source=='manual' and row.amount==Decimal('10') and row.bank_charge==Decimal('2')
        assert row.status=='active' and row.sync_status=='pending' and row.created_by==c.ctx.actor
        assert row.attachment_ids==payload['attachment_ids']
        assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==identity,ReceiptLog.action=='created')).all())==1
    return identity


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_create_actual_revocation_before_evidence(create_app,revoke):
    c=create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);payload=body(client,c,owner)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else
            {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==403,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.roles['write']]})
        identity=created(c,payload,client.post('/api/receipts',headers=owner,json=payload))
        before=read_snapshot(c);c.io.clear();replay=client.post('/api/receipts',headers=owner,json=payload)
        assert replay.status_code==200 and replay.json()['data']['id']==identity
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('role',['all','super_admin'])
def test_create_current_financial_scope_not_invoice_global(create_app,role):
    c=create_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:admin_role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin'))
        change_user(client,c,root,{'role_ids':[admin_role.id if role=='super_admin' else c.roles['all']]})
        owner=login(client,c,c.owner_name);payload=body(client,c,owner,foreign=True)
        change_user(client,c,root,{'role_ids':[c.roles['write'],c.roles['invoice:read_all']]})
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==404,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


def test_create_current_new_write_grant_accepts_old_read_token(create_app):
    c=create_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name);payload=body(client,c,owner)
        change_user(client,c,root,{'role_ids':[c.roles['write']]});c.io.clear()
        created(c,payload,client.post('/api/receipts',headers=owner,json=payload))
        assert c.calls==[]


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_create_existing_key_still_requires_current_write(create_app,revoke):
    c=create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);payload=body(client,c,owner)
        created(c,payload,client.post('/api/receipts',headers=owner,json=payload))
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else
            {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==403,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('conflict',['hidden_target','visible_target','forged_target_hash','actor','body'])
def test_create_key_conflicts_authorize_actual_target_then_validate(create_app,conflict):
    c=create_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        if conflict in ('visible_target','forged_target_hash'):change_user(client,c,root,{'role_ids':[c.roles['all']]})
        owner=login(client,c,c.owner_name);payload=body(client,c,owner)
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['foreign' if 'target' in conflict else 'victim'])
            row.request_key=payload['request_key'];row.created_by=c.ctx.actor
            row.request_hash=create_service.fingerprint(ReceiptCreate(**payload))
            if conflict=='actor':row.created_by=c.other_id
            if conflict=='body':payload['amount']='11'
            db.commit()
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==(404 if conflict=='hidden_target' else 409),response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('state',['void','synced','not_ready'])
def test_create_same_key_replay_precedes_financial_and_file_guards(create_app,state,monkeypatch):
    c=create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner)
        identity=created(c,payload,client.post('/api/receipts',headers=owner,json=payload))
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,identity)
            if state=='void':row.status='voided'
            elif state=='synced':row.sync_status='synced';row.xiaoman_receipt_id='owned-'+str(identity)
            else:db.get(Invoice,c.invoice_id).sync_status='draft'
            db.commit()
        # Excluded balance version can change; file evidence is not needed for replay.
        payload['balance_version']='f'*64
        def forbidden(*args):raise AssertionError('Replay must not revalidate file storage')
        monkeypatch.setattr(attachments,'verify_storage',forbidden)
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==200 and response.json()['data']['id']==identity,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('guard',['draft','armed','ready','foreign_unbound','batch'])
def test_create_original_proof_guards_before_external_io(create_app,guard):
    c=create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner)
        with Session(c.ctx.engine) as db:
            if guard in ('draft','armed','ready'):
                intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                intent.eligible=1;intent.status=guard;intent.amount=Decimal('10');payload['attachment_ids']=[c.proofs['intent']]
            else:payload['attachment_ids']=[c.proofs[guard]]
            db.commit()
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==409,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('guard',['not_synced','no_order','allocation','presale'])
def test_create_original_order_guards_before_external_io(create_app,guard):
    c=create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner)
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id)
            if guard=='not_synced':invoice.sync_status='draft'
            elif guard=='no_order':invoice.xiaoman_order_id=None
            elif guard=='presale':invoice.order_type='presale'
            else:db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
            db.commit()
        before=read_snapshot(c);c.io.clear();response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==409,response.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_create_unlocked_evidence_then_actual_revocation(create_app,revoke,monkeypatch):
    c=create_app;ready=threading.Event();release=threading.Event();original=remote.order_snapshot
    def gated(db,target):
        assert isinstance(target,edit_service.OrderTarget) and not db.in_transaction()
        ready.set();assert release.wait(10);return original(db,target)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);payload=body(client,c,owner)
        monkeypatch.setattr(remote,'order_snapshot',gated);before=read_snapshot(c)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(client.post,'/api/receipts',headers=owner,json=payload)
            try:
                assert ready.wait(5)
                pool.submit(change_user,client,c,root,{'is_active':False} if revoke=='disabled' else
                    {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]}).result(timeout=5)
            finally:release.set()
            response=action.result(timeout=5)
        assert response.status_code==403,response.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('change',['owner','amount','remote_id','intent_proof','ledger','proof_owner','proof_batch','proof_key'])
def test_create_final_current_binding_ledger_and_file_relationship(create_app,change,monkeypatch):
    c=create_app;ready=threading.Event();release=threading.Event();original=remote.order_snapshot
    def gated(*args):ready.set();assert release.wait(10);return original(*args)
    def mutate():
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id);proof=db.get(ReceiptAttachment,c.proofs['unbound'])
            if change=='owner':invoice.sales_user_id=c.other_id
            elif change=='amount':invoice.total_amount+=Decimal('1')
            elif change=='remote_id':invoice.xiaoman_order_id='changed'
            elif change=='intent_proof':
                intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                intent.eligible=1;intent.status='draft';intent.attachment_ids=[proof.id]
            elif change=='ledger':db.get(Receipt,c.receipts['positive']).amount+=Decimal('1')
            elif change=='proof_owner':proof.created_by=c.other_id
            elif change=='proof_batch':db.add(BatchAttachment(batch_id=c.batch_id,attachment_id=proof.id))
            else:proof.storage_key='other.png'
            db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner);monkeypatch.setattr(remote,'order_snapshot',gated)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(client.post,'/api/receipts',headers=owner,json=payload)
            try:assert ready.wait(5);pool.submit(mutate).result(timeout=5);before=read_snapshot(c)
            finally:release.set()
            response=action.result(timeout=5)
        assert response.status_code==(404 if change=='owner' else 409),response.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('change',['ledger','intent','allocation'])
def test_create_current_ledger_after_real_rr_invoice_lock_wait(create_app,change,monkeypatch):
    c=create_app;ready=threading.Event();release=threading.Event();started=queue.Queue();original=remote.order_snapshot
    def gated(*args):ready.set();assert release.wait(10);return original(*args)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner);monkeypatch.setattr(remote,'order_snapshot',gated)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,'/api/receipts',headers=owner,json=payload)
            with Session(c.ctx.engine) as other:
                try:
                    assert ready.wait(5);other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                    if change=='ledger':other.get(Receipt,c.receipts['positive']).amount=Decimal('120')
                    elif change=='intent':
                        intent=other.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                        intent.eligible=1;intent.status='ready';intent.amount=Decimal('125')
                    else:other.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                    other.flush();event.listen(c.ctx.engine,'before_cursor_execute',observe);release.set()
                    wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                    other.commit();before=read_snapshot(c);response=action.result(timeout=5)
                finally:
                    release.set();other.rollback()
                    if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert response.status_code==409,response.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('shape',['snapshot','binding','rows','row','types','provider'])
def test_create_invalid_external_evidence_controlled_before_commercial_write(create_app,shape,monkeypatch):
    c=create_app;original=remote.order_snapshot;hits=[]
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner);before=read_snapshot(c)
        def bad(db,target):
            hits.append(shape)
            if shape=='provider':raise okki_client.OkkiApiError('private-provider-body')
            if shape=='snapshot':return None
            value=original(db,target)
            if shape=='binding':value['invoice_binding']=[]
            elif shape=='rows':value['rows']=None
            elif shape=='row':value['rows']=[None]
            return value
        monkeypatch.setattr(remote,'order_snapshot',bad)
        if shape=='types':monkeypatch.setattr(remote,'receipt_types',lambda db:None)
        response=client.post('/api/receipts',headers=owner,json=payload)
        assert hits==[shape] and response.status_code==503,response.text
        assert response.headers['cache-control']=='private, no-store' and 'private-' not in response.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('failure',['missing','config','oserror'])
def test_create_file_evidence_failures_safe_and_unchanged(create_app,failure,monkeypatch):
    c=create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner);before=read_snapshot(c)
        if failure=='missing':(attachments.STORAGE_ROOT/(c.proofs['unbound']+'.png')).unlink()
        elif failure=='config':
            def bad():raise __import__('fastapi').HTTPException(503,'private-storage-config')
            monkeypatch.setattr(attachments,'origin',bad)
        else:
            def bad(row):raise OSError('private-file-details')
            monkeypatch.setattr(attachments,'path_for',bad)
        response=client.post('/api/receipts',headers=owner,json=payload)
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
        assert 'private-' not in response.text and read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('stage',[1,2,3])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_create_actual_commit_events_and_original_key_recovery(create_app,stage,timing,monkeypatch):
    c=create_app;hits=[];sessions=[];original_authorize=create_service._authorize;original_snapshot=remote.order_snapshot
    metadata=MetaData();token=Table('owned_create_metadata',metadata,Column('id',Integer,primary_key=True),Column('value',String(24)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        connection.execute(token.delete());connection.execute(token.insert().values(id=1,value='original'))
    def authorized(db,*args):
        if not any(db is value for value in sessions):sessions.append(db)
        return original_authorize(db,*args)
    def snapshot(db,target):
        db.execute(token.update().where(token.c.id==1).values(value='refreshed'));return original_snapshot(db,target)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner);before=read_snapshot(c)
        monkeypatch.setattr(create_service,'_authorize',authorized);monkeypatch.setattr(remote,'order_snapshot',snapshot)
        def fail(db):
            if any(db is value for value in sessions):
                count=db.info.get('owned_create_commit',0)+1;db.info['owned_create_commit']=count
                if count==stage:hits.append((id(db),stage));raise OperationalError('private-db-details',{},Exception('private-ack'))
        event.listen(Session,timing,fail)
        try:response=client.post('/api/receipts',headers=owner,json=payload)
        finally:event.remove(Session,timing,fail)
        assert hits==[(id(sessions[0]),stage)] and response.status_code==503,response.text
        assert response.headers['cache-control']=='private, no-store' and 'private-db' not in response.text
        with c.ctx.engine.connect() as connection:
            value=connection.scalar(select(token.c.value))
            assert value==('refreshed' if stage==3 or stage==2 and timing=='after_commit' else 'original')
        committed=stage==3 and timing=='after_commit'
        with Session(c.ctx.engine) as db:
            rows=db.scalars(select(Receipt).where(Receipt.request_key==payload['request_key'])).all()
            assert len(rows)==int(committed)
            if committed:
                row=rows[0];proof=db.get(ReceiptAttachment,payload['attachment_ids'][0])
                assert row.amount==Decimal('10') and row.bank_charge==Decimal('2') and row.sync_status=='pending'
                assert proof.receipt_id==row.id and proof.invoice_id==row.invoice_id
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='created')).all())==1
        if not committed:assert read_snapshot(c)==before
        c.io.clear();prior=read_snapshot(c)
        recovered=client.post('/api/receipts',headers=owner,json=payload);assert recovered.status_code==200,recovered.text
        if committed:assert read_snapshot(c)==prior and c.io==[]
        with Session(c.ctx.engine) as db:assert len(db.scalars(select(Receipt).where(Receipt.request_key==payload['request_key'])).all())==1
        assert c.calls==[]


@pytest.mark.parametrize('same_key',[True,False])
def test_create_both_capture_then_one_commit_replay_or_stale_balance(create_app,same_key,monkeypatch):
    c=create_app;gate=threading.Barrier(2);original=remote.order_snapshot
    def together(*args):gate.wait(timeout=10);return original(*args)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner);second=dict(payload)
        if not same_key:
            identity=uuid4().hex
            with Session(c.ctx.engine) as db:
                original_proof=db.get(ReceiptAttachment,c.proofs['unbound'])
                db.add(ReceiptAttachment(id=identity,filename='separate.png',storage_key=identity+'.png',
                    content_type='image/png',size=original_proof.size,sha256=original_proof.sha256,created_by=c.ctx.actor))
                db.commit()
            (attachments.STORAGE_ROOT/(identity+'.png')).write_bytes(c.image)
            second.update(request_key=uuid4().hex,attachment_ids=[identity])
        monkeypatch.setattr(remote,'order_snapshot',together)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(client.post,'/api/receipts',headers=owner,json=value) for value in (payload,second)]
            results=[job.result(timeout=15) for job in jobs]
        assert sorted(value.status_code for value in results)==([200,200] if same_key else [200,409]),[value.text for value in results]
        if same_key:assert results[0].json()['data']['id']==results[1].json()['data']['id']
        with Session(c.ctx.engine) as db:
            rows=db.scalars(select(Receipt).where(Receipt.request_key.in_([payload['request_key'],second['request_key']]))).all()
            assert len(rows)==1
            assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==rows[0].id,ReceiptLog.action=='created')).all())==1
    assert c.calls==[]

@pytest.mark.parametrize('amount',['7',7,7.0,'7.00','+7','007.0','7e0'])
def test_create_preserves_remote_amount_representation_in_balance_version(create_app,amount,monkeypatch):
    c=create_app;original=remote.order_snapshot
    def snapshot(db,target):
        value=original(db,target)
        value['rows']=[{'cash_collection_id':'external-history','currency':'USD','amount':amount,'collect_status':1}]
        return value
    monkeypatch.setattr(remote,'order_snapshot',snapshot)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);payload=body(client,c,owner)
        created(c,payload,client.post('/api/receipts',headers=owner,json=payload))
    assert c.calls==[]