"""Actual batch creation competitions, current lock reads and exact commit-stage recovery."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import queue
import threading
from uuid import uuid4
import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.portal import authority as portal_authority
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, BatchAttachment
from app.receipt import attachments, batch_create_service, fees, remote
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent, ReceiptLog
from app.semifinished.models import InvoiceAllocation
from test_mysql_concurrency import wait_for_lock
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app, payload, created, financial_snapshot  # noqa: F401


@pytest.mark.parametrize('stage',[1,2,3])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_batch_exact_commit_stage_unknown_result_and_original_key_recovery(batch_create_app,stage,timing,monkeypatch):
    c=batch_create_app;hits=[];sessions=[];original_authorize=batch_create_service._authorize;original_snapshot=remote.order_snapshot
    metadata=MetaData();token=Table('owned_batch_metadata',metadata,
        Column('id',Integer,primary_key=True),Column('value',String(24)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        connection.execute(token.delete());connection.execute(token.insert().values(id=1,value='original'))
    def authorized(db,*args):
        if not any(db is value for value in sessions):sessions.append(db)
        return original_authorize(db,*args)
    def snapshot(db,target):
        db.execute(token.update().where(token.c.id==1).values(value='refreshed'))
        return original_snapshot(db,target)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner);before=financial_snapshot(c)
        monkeypatch.setattr(batch_create_service,'_authorize',authorized);monkeypatch.setattr(remote,'order_snapshot',snapshot)
        def fail(db):
            if any(db is value for value in sessions):
                count=db.info.get('owned_batch_commit',0)+1;db.info['owned_batch_commit']=count
                if count==stage:
                    hits.append((id(db),stage));raise OperationalError('private-db-details',{},Exception('private-ack'))
        event.listen(Session,timing,fail)
        try:response=client.post('/api/receipts/batches',headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert len(sessions)==1 and hits==[(id(sessions[0]),stage)] and response.status_code==503,response.text
        assert response.headers['cache-control']=='private, no-store' and 'private-' not in response.text
        with c.ctx.engine.connect() as connection:
            assert connection.scalar(select(token.c.value))==(
                'refreshed' if stage==3 or stage==2 and timing=='after_commit' else 'original')
        committed=stage==3 and timing=='after_commit'
        with Session(c.ctx.engine) as db:
            batches=db.scalars(select(ReceiptBatch).where(ReceiptBatch.request_key==body['request_key'])).all()
            assert len(batches)==int(committed)
            if committed:
                batch=batches[0]
                rows=db.scalars(select(Receipt).where(Receipt.batch_id==batch.id)).all()
                assert batch.gross_amount==20 and batch.bank_charge_total==2 and len(rows)==2
                assert all(row.amount==10 and row.bank_charge==1 and row.sync_status=='pending' for row in rows)
                assert db.query(BatchAttachment).filter_by(batch_id=batch.id).count()==1
                assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([r.id for r in rows]),ReceiptLog.action=='created').count()==2
        if not committed:assert financial_snapshot(c)==before
        c.io.clear();prior=financial_snapshot(c)
        recovered=client.post('/api/receipts/batches',headers=owner,json=body)
        created(c,body,recovered)
        if committed:assert financial_snapshot(c)==prior and c.io==[]
        with Session(c.ctx.engine) as db:assert db.query(ReceiptBatch).filter_by(request_key=body['request_key']).count()==1
        assert c.calls==[]


@pytest.mark.parametrize('same_key',[True,False])
def test_both_batches_capture_then_replay_or_reject_competing_funds(batch_create_app,same_key,monkeypatch):
    c=batch_create_app;gate=threading.Barrier(2);original=fees.read_evidence
    with Session(c.ctx.engine) as db:order_id=db.get(Invoice,c.invoice_id).xiaoman_order_id
    def together(db,binding):
        if binding[0]==order_id:gate.wait(timeout=10)
        return original(db,binding)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);first=payload(client,c,owner)
        first['amount']='160'
        for allocation in first['allocations']:allocation['amount']='80'
        second=deepcopy(first)
        if not same_key:
            identity=uuid4().hex
            with Session(c.ctx.engine) as db:
                proof=db.get(ReceiptAttachment,c.proofs['unbound'])
                db.add(ReceiptAttachment(id=identity,filename='different-payment.png',storage_key=identity+'.png',
                    content_type='image/png',size=proof.size,sha256=proof.sha256,created_by=c.ctx.actor));db.commit()
            (attachments.STORAGE_ROOT/(identity+'.png')).write_bytes(c.image)
            second.update(request_key=uuid4().hex,attachment_ids=[identity])
        monkeypatch.setattr(fees,'read_evidence',together)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(client.post,'/api/receipts/batches',headers=owner,json=value) for value in (first,second)]
            responses=[job.result(timeout=15) for job in jobs]
        assert sorted(r.status_code for r in responses)==([200,200] if same_key else [200,409]),[r.text for r in responses]
        if same_key:assert responses[0].json()['data']['id']==responses[1].json()['data']['id']
        with Session(c.ctx.engine) as db:
            batches=db.scalars(select(ReceiptBatch).where(ReceiptBatch.request_key.in_([first['request_key'],second['request_key']]))).all()
            assert len(batches)==1 and batches[0].gross_amount==160 and batches[0].bank_charge_total==16
            rows=db.scalars(select(Receipt).where(Receipt.batch_id==batches[0].id)).all()
            assert len(rows)==2 and all(row.amount==80 and row.bank_charge==8 and row.sync_status=='pending' for row in rows)
            assert {r.invoice_id for r in rows}=={c.invoice_id,c.second_invoice_id}
            assert db.query(BatchAttachment).filter_by(batch_id=batches[0].id).count()==1
            assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([r.id for r in rows]),ReceiptLog.action=='created').count()==2
        assert c.calls==[]


@pytest.mark.parametrize('mutation',['receipt','intent','allocation'])
def test_final_current_graph_after_real_invoice_wait(batch_create_app,mutation,monkeypatch):
    c=batch_create_app;ready=threading.Event();release=threading.Event();started=queue.Queue()
    locked=threading.Event();resume=threading.Event();target={};original=fees.read_evidence;hits=[]
    def gate(*args):
        if not hits:hits.append(True);ready.set();assert release.wait(10)
        return original(*args)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            target['connection']=connection;started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold(connection,cursor,statement,parameters,context,executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            locked.set();assert resume.wait(10)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner);monkeypatch.setattr(fees,'read_evidence',gate)
        with Session(c.ctx.engine) as other,ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(client.post,'/api/receipts/batches',headers=owner,json=body)
            try:
                assert ready.wait(5);other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                if mutation=='receipt':other.get(Receipt,c.receipts['positive']).amount=120
                elif mutation=='intent':
                    intent=other.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                    intent.eligible=1;intent.status='ready';intent.amount=125
                else:other.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
                other.flush();event.listen(c.ctx.engine,'before_cursor_execute',observe)
                event.listen(c.ctx.engine,'after_cursor_execute',hold);release.set()
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                other.commit();assert locked.wait(5)
                before=financial_snapshot(c);assert not action.done();resume.set();response=action.result(timeout=5)
            finally:
                release.set();resume.set();other.rollback()
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
                if event.contains(c.ctx.engine,'after_cursor_execute',hold):event.remove(c.ctx.engine,'after_cursor_execute',hold)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('amount',['7',7,7.0,'7.00','+7','007.0','7e0'])
def test_batch_balance_digest_retains_amount_representation(batch_create_app,amount,monkeypatch):
    c=batch_create_app;original=remote.order_snapshot
    def snapshot(db,target):
        value=original(db,target)
        value['rows']=[{'cash_collection_id':'history','currency':'USD','amount':amount,'collect_status':1}]
        return value
    def evidence(db,binding):return fees.FeeEvidence(tuple(binding),(('history',Decimal('7'),Decimal('0')),))
    monkeypatch.setattr(remote,'order_snapshot',snapshot);monkeypatch.setattr(fees,'read_evidence',evidence)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
    assert c.calls==[]


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('commit',[False,True])
def test_batch_final_business_transaction_fences_admin_until_commit_or_rollback(batch_create_app,enabled,commit,monkeypatch):
    c=batch_create_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is enabled
    ready=threading.Event();resume=threading.Event();started=queue.Queue();sessions=[]
    original=batch_create_service._authorize
    def authorize(db,*args):
        if not any(db is value for value in sessions):sessions.append(db)
        return original(db,*args)
    def gate(db):
        if any(db is value for value in sessions):
            count=db.info.get('owned_final_fence',0)+1;db.info['owned_final_fence']=count
            if count==3:
                ready.set();assert resume.wait(10)
                if not commit:raise OperationalError('private-business-commit',{},Exception('rollback'))
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        body=payload(client,c,owner);before=financial_snapshot(c)
        monkeypatch.setattr(batch_create_service,'_authorize',authorize)
        event.listen(Session,'before_commit',gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(client.post,'/api/receipts/batches',headers=owner,json=body)
            try:
                assert ready.wait(5);event.listen(c.ctx.engine,'before_cursor_execute',observe)
                revoke=pool.submit(change_user,client,c,root,{'is_active':False})
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not revoke.done() and not action.done()
                resume.set();response=action.result(timeout=5);revoke.result(timeout=5)
            finally:
                resume.set();event.remove(Session,'before_commit',gate)
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        if commit:created(c,body,response)
        else:
            assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
            assert financial_snapshot(c)==before
        after=financial_snapshot(c);c.io.clear()
        denied=client.post('/api/receipts/batches',headers=owner,json=body)
        assert denied.status_code==403,denied.text
        assert financial_snapshot(c)==after and c.io==[] and c.calls==[]
