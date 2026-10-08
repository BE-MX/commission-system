"""Actual main/JWT/MySQL batch reads and local voids; upstream schema synthetic."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import queue
import threading
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import Column, MetaData, Table, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.auth.models import ArkRole
from app.invoice.settlement_models import ReceiptBatch, SettlementApplication, ShipmentSettlement
from app.receipt.models import Receipt, ReceiptLog
from app.receipt import authority as receipt_authority, batch_service, service
from app.invoice.models import Invoice
from app.core.time import beijing_now
from app.portal import authority as portal_authority
from test_mysql_concurrency import wait_for_lock
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401


@pytest.fixture
def batch_app(read_app):
    c=read_app
    metadata=MetaData()
    for model in (SettlementApplication,ShipmentSettlement):
        Table(model.__tablename__,metadata,*(Column(column.name,column.type,
            primary_key=column.primary_key,nullable=False if column.primary_key else True)
            for column in model.__table__.columns))
    metadata.create_all(c.ctx.engine)
    with Session(c.ctx.engine) as db:
        batch=db.get(ReceiptBatch,c.batch_id);batch.gross_amount=20;batch.bank_charge_total=4
        for label in ('positive','victim'):
            row=db.get(Receipt,c.receipts[label]);row.batch_id=c.batch_id;row.bank_charge=2
            row.attachment_ids=[c.proofs['batch']]
        settlement=ShipmentSettlement(invoice_id=c.invoice_id,sequence=1,
            settlement_no='BATCH-'+uuid4().hex,state='awaiting_payment',is_final=0,
            quote={},quote_hash='d'*64,request_key=uuid4().hex,request_hash='d'*64,created_by=c.ctx.actor)
        db.add(settlement);db.flush();c.settlement_id=settlement.id
        app=SettlementApplication(settlement_id=settlement.id,receipt_id=c.receipts['positive'],
            component='goods',amount=10,bank_charge=2,status='reserved')
        db.add(app);db.flush();c.application_id=app.id;db.commit()
    return c


def path(c):return '/api/receipts/batches/'+str(c.batch_id)
def call(client,c,kind,headers,version=1):
    return client.get(path(c),headers=headers) if kind=='read' else client.post(path(c)+'/void-entry',
        headers=headers,json={'version':version,'reason':'Correct mistaken batch entry'})
def grant(client,c,root,roles=None):
    change_user(client,c,root,{'role_ids':roles or [c.roles['receipt:admin']]})
def financial_snapshot(c):
    with Session(c.ctx.engine) as db:
        extra=tuple(tuple(db.execute(select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)).all())
            for model in (SettlementApplication,ShipmentSettlement))
    return read_snapshot(c)+extra


@pytest.mark.parametrize('kind',['read','void'])
@pytest.mark.parametrize('revocation',['disabled','roles','action'])
def test_stale_jwt_batch_rejected(batch_app,kind,revocation):
    c=batch_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        assert client.get(path(c),headers=owner).status_code==200
        change_user(client,c,root,{'is_active':False} if revocation=='disabled' else
            {'role_ids':[]} if revocation=='roles' else {'role_ids':[c.roles['invoice:read_all']]})
        before=financial_snapshot(c);response=call(client,c,kind,owner)
        assert response.status_code==403,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('kind',['read','void'])
@pytest.mark.parametrize('global_role',['all','super_admin'])
def test_batch_scope_rebuilt_for_whole_membership(batch_app,kind,global_role):
    c=batch_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:
            global_id=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin')).id if global_role=='super_admin' else c.roles['all']
            db.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id;db.commit()
        grant(client,c,root,[c.roles['receipt:admin'],global_id]);owner=login(client,c,c.owner_name)
        assert client.get(path(c),headers=owner).status_code==200
        grant(client,c,root,[c.roles['receipt:admin'],c.roles['invoice:read_all']])
        before=financial_snapshot(c);response=call(client,c,kind,owner)
        assert response.status_code==404,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('kind',['read','void'])
def test_batch_current_new_grant_works_with_old_token(batch_app,kind):
    c=batch_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root,[c.roles['invoice:read_all']]);owner=login(client,c,c.owner_name)
        assert call(client,c,kind,owner).status_code==403
        grant(client,c,root);response=call(client,c,kind,owner)
        assert response.status_code==200,response.text
        data=response.json()['data'];assert data['id']==c.batch_id and len(data['items'])==2
        with Session(c.ctx.engine) as db:
            batch=db.get(ReceiptBatch,c.batch_id)
            assert batch.gross_amount==Decimal('20.00') and batch.bank_charge_total==Decimal('4.00')
            assert batch.status==('active' if kind=='read' else 'voided') and batch.version==(1 if kind=='read' else 2)
            rows=db.scalars(select(Receipt).where(Receipt.batch_id==c.batch_id)).all()
            assert len(rows)==2 and all(row.amount==10 and row.bank_charge==2 for row in rows)
            assert all(row.status==('active' if kind=='read' else 'voided') for row in rows)
            assert all(row.attachment_ids==[c.proofs['batch']] for row in rows)
            app=db.get(SettlementApplication,c.application_id);settlement=db.get(ShipmentSettlement,c.settlement_id)
            assert app.status==('reserved' if kind=='read' else 'released')
            assert settlement.state=='awaiting_payment' and settlement.version==(1 if kind=='read' else 2)
            logs=db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id.in_([row.id for row in rows]))).all()
            assert len(logs)==(0 if kind=='read' else 2)
        assert c.io==[] and c.calls==[]


@pytest.mark.parametrize('guard',['remote','lease','uncertain','syncing','unverified','version','batch_status',
    'applied','settlement_state','missing_settlement','foreign_settlement','late_result','released_bad_state'])
def test_financial_guards_leave_entire_batch_unchanged(batch_app,guard):
    c=batch_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['positive']);batch=db.get(ReceiptBatch,c.batch_id)
            app=db.get(SettlementApplication,c.application_id);settlement=db.get(ShipmentSettlement,c.settlement_id)
            if guard=='remote':row.xiaoman_receipt_id='12345'
            elif guard=='lease':row.lease_until=beijing_now()-timedelta(hours=1)
            elif guard in ('uncertain','syncing','unverified'):row.sync_status=guard
            elif guard=='version':batch.version=2
            elif guard=='batch_status':batch.status='voided'
            elif guard=='applied':app.status='applied'
            elif guard=='settlement_state':settlement.state='ready'
            elif guard=='missing_settlement':db.delete(settlement)
            elif guard=='foreign_settlement':settlement.invoice_id=c.foreign_invoice_id
            elif guard=='late_result':service.log(db,row,'late_result','Persisted remote create result without receipt change')
            else:app.status='released';settlement.state='ready'
            db.commit()
        before=financial_snapshot(c);response=call(client,c,'void',owner)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('variant',['paused','verification','failed','waiting_target','not_ready','released'])
def test_original_financial_positive_states_are_preserved(batch_app,variant):
    c=batch_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        with Session(c.ctx.engine) as db:
            settlement=db.get(ShipmentSettlement,c.settlement_id)
            if variant=='paused':settlement.state='paused'
            elif variant=='verification':settlement.state='awaiting_verification'
            elif variant in ('failed','waiting_target'):db.get(Receipt,c.receipts['positive']).sync_status=variant
            elif variant=='not_ready':db.get(Invoice,c.invoice_id).status='draft'
            else:db.get(SettlementApplication,c.application_id).status='released'
            db.commit()
        response=call(client,c,'void',owner);assert response.status_code==200,response.text
        with Session(c.ctx.engine) as db:
            assert db.get(ReceiptBatch,c.batch_id).status=='voided'
            assert db.get(ShipmentSettlement,c.settlement_id).state==('paused' if variant=='paused' else 'awaiting_payment')
            assert db.get(ShipmentSettlement,c.settlement_id).version==2
            assert db.get(SettlementApplication,c.application_id).status=='released'
        assert c.io==[] and c.calls==[]


@pytest.mark.parametrize('kind',['read','void'])
@pytest.mark.parametrize('role',['read','write','receipt:admin'])
def test_batch_action_and_range_are_separate(batch_app,kind,role):
    c=batch_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root,[c.roles[role]]);owner=login(client,c,c.owner_name)
        before=financial_snapshot(c);response=call(client,c,kind,owner)
        allowed=kind=='read' or role=='receipt:admin'
        assert response.status_code==(200 if allowed else 403),response.text
        if kind=='read' or not allowed:assert financial_snapshot(c)==before
        assert c.io==[] and c.calls==[]


@pytest.mark.parametrize('mutation',['application','settlement','late_result','member_invoice','new_member'])
def test_current_financial_graph_after_actual_invoice_wait(batch_app,mutation):
    c=batch_app;started=queue.Queue();locked=threading.Event();resume=threading.Event();target={}
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            target['connection']=connection
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold_current_invoice(connection,cursor,statement,parameters,context,executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            locked.set();assert resume.wait(10)
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        with Session(c.ctx.engine) as other,ThreadPoolExecutor(max_workers=1) as pool:
            other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
            event.listen(c.ctx.engine,'before_cursor_execute',observe)
            event.listen(c.ctx.engine,'after_cursor_execute',hold_current_invoice)
            try:
                action=pool.submit(call,client,c,'void',owner)
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                if mutation=='application':other.get(SettlementApplication,c.application_id).status='applied'
                elif mutation=='settlement':other.get(ShipmentSettlement,c.settlement_id).state='ready'
                elif mutation=='late_result':service.log(other,other.get(Receipt,c.receipts['positive']),'late_result','Late result after RR snapshot')
                elif mutation=='member_invoice':other.get(Receipt,c.receipts['positive']).invoice_id=c.foreign_invoice_id
                else:other.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id
                other.commit();assert locked.wait(5)
                before=financial_snapshot(c);assert not action.done()
                resume.set();response=action.result(timeout=5)
            finally:
                resume.set();other.rollback();event.remove(c.ctx.engine,'before_cursor_execute',observe)
                event.remove(c.ctx.engine,'after_cursor_execute',hold_current_invoice)
        assert response.status_code==409,response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('enabled',[False,True])
def test_batch_revocation_first_commit_denies_before_local_mutation(batch_app,enabled,monkeypatch):
    c=batch_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is enabled
    ready=threading.Event();release=threading.Event();original=receipt_authority.local_batch
    def gate(*args,**kwargs):
        ready.set();assert release.wait(10);return original(*args,**kwargs)
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        monkeypatch.setattr(receipt_authority,'local_batch',gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            action=pool.submit(call,client,c,'void',owner)
            try:
                assert ready.wait(5);change_user(client,c,root,{'is_active':False})
                before=financial_snapshot(c);release.set();response=action.result(timeout=5)
            finally:release.set()
        assert response.status_code==403 and financial_snapshot(c)==before,response.text
        assert c.io==[] and c.calls==[]


@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_commit_uncertainty_requires_original_batch_read(batch_app,timing,monkeypatch):
    c=batch_app;sessions=[];hits=[];original=receipt_authority.local_batch
    def capture(db,*args,**kwargs):
        sessions.append(db);return original(db,*args,**kwargs)
    def failure(db):
        if any(db is item for item in sessions):
            hits.append(id(db));raise OperationalError('private-commit',{},Exception('private-ack'))
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        before=financial_snapshot(c);monkeypatch.setattr(receipt_authority,'local_batch',capture)
        event.listen(Session,timing,failure)
        try:response=call(client,c,'void',owner)
        finally:event.remove(Session,timing,failure)
        assert len(sessions)==1 and hits==[id(sessions[0])]
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store',response.text
        assert 'private-commit' not in response.text and 'private-ack' not in response.text
        if timing=='before_commit':assert financial_snapshot(c)==before
        with Session(c.ctx.engine) as db:
            batch=db.get(ReceiptBatch,c.batch_id);committed=timing=='after_commit'
            assert batch.status==('voided' if committed else 'active') and batch.version==(2 if committed else 1)
            assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([c.receipts['positive'],c.receipts['victim']]),ReceiptLog.action=='voided').count()==(2 if committed else 0)
        after=financial_snapshot(c);read=call(client,c,'read',owner)
        assert read.status_code==200 and financial_snapshot(c)==after
        restored=call(client,c,'void',owner)
        assert restored.status_code==(409 if timing=='after_commit' else 200),restored.text
        if timing=='after_commit':assert financial_snapshot(c)==after
        assert c.io==[] and c.calls==[]


def test_same_version_two_voids_only_one_commits(batch_app,monkeypatch):
    c=batch_app;barrier=threading.Barrier(2);original=receipt_authority.local_batch
    def gate(*args,**kwargs):barrier.wait(timeout=10);return original(*args,**kwargs)
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        monkeypatch.setattr(receipt_authority,'local_batch',gate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _:call(client,c,'void',owner),range(2)))
        assert sorted(response.status_code for response in responses)==[200,409]
        with Session(c.ctx.engine) as db:
            assert db.get(ReceiptBatch,c.batch_id).version==2
            assert all(row.version==2 for row in db.scalars(select(Receipt).where(Receipt.batch_id==c.batch_id)))
            assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([c.receipts['positive'],c.receipts['victim']]),ReceiptLog.action=='voided').count()==2
        assert c.io==[] and c.calls==[]


@pytest.mark.parametrize('kind,table',[('read','ark_users'),('void','ark_users'),
    ('void','ark_receipt_batches'),('void','ark_settlement_applications'),
    ('void','ark_shipment_settlements'),('void','ark_receipt_logs')])
def test_query_failure_has_controlled_result_and_legal_recovery(batch_app,kind,table):
    c=batch_app;hits=[]
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        before=financial_snapshot(c)
        def failure(connection,cursor,statement,parameters,context,executemany):
            if not hits and ('FROM '+table) in statement and (table=='ark_users' or 'FOR UPDATE' in statement.upper()):
                hits.append(table);raise OperationalError('private-sql-details',{},Exception('private-driver'))
        event.listen(c.ctx.engine,'before_cursor_execute',failure)
        try:response=call(client,c,kind,owner)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',failure)
        assert hits==[table] and response.status_code==503,response.text
        assert response.headers['cache-control']=='private, no-store' and 'private-' not in response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]
        assert call(client,c,kind,owner).status_code==200


@pytest.mark.parametrize('enabled',[False,True])
@pytest.mark.parametrize('commit',[False,True])
def test_local_batch_holds_revocation_barrier_until_commit_or_rollback(batch_app,enabled,commit,monkeypatch):
    c=batch_app;c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    assert portal_authority.get_settings().PORTAL_ENABLED is enabled
    ready=threading.Event();release=threading.Event();started=queue.Queue();sessions=[];hits=[]
    original=batch_service._void_financial
    def hold(db,*args):
        result=original(db,*args);sessions.append(db);ready.set();assert release.wait(10);return result
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def fail(db):
        if not commit and any(db is item for item in sessions):
            hits.append(id(db));raise OperationalError('private-rollback',{},Exception('private-cause'))
    with c.app.client() as client:
        root=login(client,c,c.root_name);grant(client,c,root);owner=login(client,c,c.owner_name)
        monkeypatch.setattr(batch_service,'_void_financial',hold)
        event.listen(Session,'before_commit',fail)
        with ThreadPoolExecutor(max_workers=2) as pool:
            action=pool.submit(call,client,c,'void',owner)
            try:
                assert ready.wait(5);event.listen(c.ctx.engine,'before_cursor_execute',observe)
                admin=pool.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,json={'is_active':False})
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not admin.done()
                release.set();response=action.result(timeout=5)
                assert admin.result(timeout=5).status_code==200
            finally:
                release.set();event.remove(Session,'before_commit',fail)
                if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert response.status_code==(200 if commit else 503),response.text
        assert hits==([] if commit else [id(sessions[0])])
        with Session(c.ctx.engine) as db:
            assert db.get(ReceiptBatch,c.batch_id).status==('voided' if commit else 'active')
            assert db.query(ReceiptLog).filter(ReceiptLog.receipt_id.in_([c.receipts['positive'],c.receipts['victim']]),ReceiptLog.action=='voided').count()==(2 if commit else 0)
            assert db.get(SettlementApplication,c.application_id).status==('released' if commit else 'reserved')
        before=financial_snapshot(c);assert call(client,c,'void',owner).status_code==403
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]
