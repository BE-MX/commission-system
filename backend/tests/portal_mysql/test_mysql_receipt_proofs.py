"""Actual automatic-receipt proof bindings: current JWT principal, owned MySQL."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import queue
import threading

import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkRole
from app.invoice.models import Invoice
from app.invoice.settlement_models import BatchAttachment
from app.receipt import attachments, storage_proxy
from app.receipt.models import Receipt, ReceiptIntent, ReceiptAttachment, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot  # noqa: F401
from test_mysql_concurrency import wait_for_lock


@pytest.fixture
def proof_app(read_app):
    c=read_app
    with Session(c.ctx.engine) as db:
        for label,invoice_id in [('victim',c.invoice_id),('foreign',c.foreign_invoice_id)]:
            row=db.get(Receipt,c.receipts[label]);row.source='auto'
            intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice_id))
            intent.status='converted';intent.receipt_id=row.id;intent.attachment_ids=list(row.attachment_ids)
        db.commit()
    return c


def path(c,label='victim'):return '/api/receipts/'+str(c.receipts[label])+'/attachments'
def body(c,label='victim'):return {'version':1,'attachment_ids':[c.proofs['foreign_intent' if label=='foreign' else 'unbound']]}


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_proofs_actual_revocation_rejects_old_jwt(proof_app,revoke):
    c=proof_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]})
        before=read_snapshot(c);result=client.put(path(c),headers=owner,json=body(c))
        assert result.status_code==403,result.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.roles['write']]})
        result=client.put(path(c),headers=owner,json=body(c));assert result.status_code==200,result.text
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['victim']);intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
            assert row.version==2 and row.attachment_ids==intent.attachment_ids==[c.proofs['unbound']]
            assert row.amount==Decimal('10') and row.bank_charge==0 and row.sync_status=='pending'
            assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='proofs_updated')).all())==1
        before=read_snapshot(c);assert client.put(path(c),headers=owner,json=body(c)).status_code==409
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('role_name',['all','super_admin'])
def test_proofs_revoke_global_scope_keeps_original_financial_scope(proof_app,role_name):
    c=proof_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin'))
        change_user(client,c,root,{'role_ids':[role.id if role_name=='super_admin' else c.roles['all']]})
        owner=login(client,c,c.owner_name);change_user(client,c,root,{'role_ids':[c.roles['write'],c.roles['invoice:read_all']]})
        before=read_snapshot(c);result=client.put(path(c,'foreign'),headers=owner,json=body(c,'foreign'))
        assert result.status_code==404,result.text
        assert read_snapshot(c)==before and c.io==[]
        assert client.put(path(c),headers=owner,json=body(c)).status_code==200


def test_proofs_current_new_grant_accepts_old_token_without_write(proof_app):
    c=proof_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name);change_user(client,c,root,{'role_ids':[c.roles['write']]})
        result=client.put(path(c),headers=owner,json=body(c));assert result.status_code==200,result.text
        assert c.calls==[]


def money_state(db,row):
    return tuple(getattr(row,name) for name in ('amount','bank_charge','sync_status','xiaoman_order_id',
        'xiaoman_receipt_id','xiaoman_receipt_no','collect_status','lease_until','attempts','attempt_token','last_error'))


@pytest.mark.parametrize('state',['synced','uncertain','not_ready'])
def test_proofs_preserve_original_legal_states_and_financial_fields(proof_app,state):
    c=proof_app
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);row.sync_status='synced' if state=='synced' else 'uncertain'
        row.xiaoman_receipt_id=str(998000000+row.id);row.xiaoman_receipt_no='old';row.attempt_token='original-token';row.attempts=4
        if state=='not_ready':db.get(Invoice,c.invoice_id).sync_status='draft';db.get(Invoice,c.invoice_id).xiaoman_order_id=None
        db.commit();expected=money_state(db,row)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);result=client.put(path(c),headers=owner,json=body(c))
        assert result.status_code==200,result.text
    with Session(c.ctx.engine) as db:assert money_state(db,db.get(Receipt,c.receipts['victim']))==expected
    assert c.io==[] and c.calls==[]


@pytest.mark.parametrize('guard',['manual','void','syncing','version','intent_state','intent_binding','batch','mixed_batch'])
def test_proofs_original_guards_and_full_batch_scope_before_io(proof_app,guard,monkeypatch):
    c=proof_app;files=[];original=attachments.path_for
    def observe(row):files.append(row.id);return original(row)
    monkeypatch.setattr(attachments,'path_for',observe)
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
        if guard=='manual':row.source='manual'
        elif guard=='void':row.status='voided'
        elif guard=='syncing':row.sync_status='syncing'
        elif guard=='version':row.version=2
        elif guard=='intent_state':intent.status='ready'
        elif guard=='intent_binding':intent.receipt_id=c.receipts['positive']
        else:
            row.batch_id=c.batch_id
            if guard=='mixed_batch':db.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id
        db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);result=client.put(path(c),headers=owner,json=body(c))
        assert result.status_code==(404 if guard=='mixed_batch' else 409),result.text
        assert read_snapshot(c)==before and files==[] and c.io==[] and c.calls==[]


@pytest.mark.parametrize('revoke',['disabled','write'])
def test_proofs_actual_admin_revokes_while_file_io_is_unlocked(proof_app,revoke,monkeypatch):
    c=proof_app;ready=threading.Event();release=threading.Event();original=attachments.path_for;hits=[]
    def gated(row):
        assert isinstance(row,attachments.AttachmentBinding)
        hits.append(row.id);ready.set();assert release.wait(10);return original(row)
    monkeypatch.setattr(attachments,'path_for',gated)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(client.put,path(c),headers=owner,json=body(c))
            try:
                assert ready.wait(5);pool.submit(change_user,client,c,root,{'is_active':False} if revoke=='disabled' else
                    {'role_ids':[c.roles['read']]}).result(timeout=5);before=read_snapshot(c)
            finally:release.set()
            result=future.result(timeout=5)
        assert hits==[c.proofs['unbound']] and result.status_code==403,result.text
        assert read_snapshot(c)==before and c.io==[] and c.calls==[]


@pytest.mark.parametrize('change',['owner','intent_state','intent_binding','intent_metadata','worker_claim',
    'worker_done','target_amount','attachment_other','attachment_batch','storage_key'])
def test_proofs_full_binding_and_current_file_relationships_after_io(proof_app,change,monkeypatch):
    c=proof_app;ready=threading.Event();release=threading.Event();original=attachments.path_for
    def gated(row):ready.set();assert release.wait(10);return original(row)
    monkeypatch.setattr(attachments,'path_for',gated)
    def mutate():
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['victim']);intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
            proof=db.get(ReceiptAttachment,c.proofs['unbound'])
            if change=='owner':db.get(Invoice,c.invoice_id).sales_user_id=c.other_id
            elif change=='intent_state':intent.status='ready'
            elif change=='intent_binding':intent.receipt_id=c.receipts['positive']
            elif change=='intent_metadata':intent.remark='independently changed'
            elif change=='worker_claim':row.sync_status='syncing';row.attempt_token='current-worker'
            elif change=='worker_done':row.sync_status='synced';row.xiaoman_receipt_id=str(999000000+row.id);row.attempts=2
            elif change=='target_amount':row.amount=Decimal('11')
            elif change=='attachment_other':proof.invoice_id=c.foreign_invoice_id;proof.receipt_id=c.receipts['foreign']
            elif change=='attachment_batch':db.add(BatchAttachment(batch_id=c.batch_id,attachment_id=proof.id))
            else:proof.storage_key='other-key.png'
            db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(client.put,path(c),headers=owner,json=body(c))
            try:assert ready.wait(5);pool.submit(mutate).result(timeout=5);before=read_snapshot(c)
            finally:release.set()
            result=future.result(timeout=5)
        assert result.status_code==(404 if change=='owner' else 409),result.text
        assert read_snapshot(c)==before and c.calls==[]


def test_proofs_intent_current_read_after_real_rr_invoice_wait(proof_app,monkeypatch):
    c=proof_app;ready=threading.Event();release=threading.Event();started=queue.Queue();original=attachments.path_for
    def gated(row):ready.set();assert release.wait(10);return original(row)
    monkeypatch.setattr(attachments,'path_for',gated)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(client.put,path(c),headers=owner,json=body(c))
            with Session(c.ctx.engine) as other:
                try:
                    assert ready.wait(5);other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                    intent=other.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id));intent.status='ready';other.flush()
                    event.listen(c.ctx.engine,'before_cursor_execute',observe);release.set()
                    wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not future.done()
                    other.commit();before=read_snapshot(c);result=future.result(timeout=5)
                finally:
                    release.set();other.rollback()
                    if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        assert result.status_code==409,result.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('failure',['missing','configuration','oserror'])
def test_proofs_storage_failures_are_safe_even_same_set(proof_app,failure,monkeypatch):
    c=proof_app;payload={'version':1,'attachment_ids':[c.proofs['own']]};hits=[]
    if failure=='missing':
        with Session(c.ctx.engine) as db:attachments.path_for(db.get(ReceiptAttachment,c.proofs['own'])).unlink()
    elif failure=='configuration':
        c.app.settings.RECEIPT_STORAGE_PROXY_URL='http://invalid.example.test';monkeypatch.setattr(storage_proxy,'get_settings',lambda:c.app.settings)
    else:
        def broken(row):hits.append(row.id);raise OSError('private-file-error')
        monkeypatch.setattr(attachments,'path_for',broken)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c);result=client.put(path(c),headers=owner,json=payload)
        assert result.status_code==503 and result.headers['cache-control']=='private, no-store',result.text
        assert 'private-' not in result.text and read_snapshot(c)==before and c.calls==[]
    if failure=='oserror':assert hits==[c.proofs['own']]


def test_proofs_same_set_permutation_is_no_op_after_validation(proof_app):
    c=proof_app
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);proof=db.get(ReceiptAttachment,c.proofs['unbound'])
        proof.invoice_id=row.invoice_id;proof.receipt_id=row.id;row.attachment_ids=[c.proofs['own'],proof.id]
        db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id)).attachment_ids=list(row.attachment_ids);db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.put(path(c),headers=owner,json={'version':1,'attachment_ids':[c.proofs['unbound'],c.proofs['own']]})
        assert result.status_code==200,result.text
        assert read_snapshot(c)==before and c.calls==[]


def test_proofs_two_original_versions_change_once(proof_app,monkeypatch):
    c=proof_app;ready=queue.Queue();release=threading.Event();original=attachments.path_for
    def gated(row):ready.put(True);assert release.wait(10);return original(row)
    monkeypatch.setattr(attachments,'path_for',gated)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(client.put,path(c),headers=owner,json=body(c));second=pool.submit(client.put,path(c),headers=owner,json=body(c))
            try:assert ready.get(timeout=5) and ready.get(timeout=5)
            finally:release.set()
            results=[first.result(timeout=5),second.result(timeout=5)]
        assert sorted(x.status_code for x in results)==[200,409],[x.text for x in results]
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);assert row.version==2 and row.sync_status=='pending'
        assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='proofs_updated')).all())==1
    assert c.calls==[]


@pytest.mark.parametrize('stage',[1,2])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_proofs_real_commit_events_and_unknown_final_result(proof_app,stage,timing):
    c=proof_app;hits=[]
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        def fail(db):
            if any(isinstance(row,Receipt) and inspect(row).identity==(c.receipts['victim'],) for row in db.identity_map.values()):db.info['owned_proof_session']=True
            if db.info.get('owned_proof_session'):
                count=db.info.get('owned_proof_commit',0)+1;db.info['owned_proof_commit']=count
                if count==stage and not hits:hits.append((stage,timing));raise OperationalError('private-proof-query',{},Exception('private-proof-ack'))
        event.listen(Session,timing,fail)
        try:result=client.put(path(c),headers=owner,json=body(c))
        finally:event.remove(Session,timing,fail)
        assert hits==[(stage,timing)] and result.status_code==503,result.text
        assert 'private-' not in result.text and result.headers['cache-control']=='private, no-store'
        committed=stage==2 and timing=='after_commit'
        if not committed:assert read_snapshot(c)==before
        else:
            with Session(c.ctx.engine) as db:
                row=db.get(Receipt,c.receipts['victim']);intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==c.invoice_id))
                assert row.version==2 and row.attachment_ids==intent.attachment_ids==[c.proofs['unbound']]
                assert row.amount==10 and row.bank_charge==0 and row.sync_status=='pending'
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='proofs_updated')).all())==1
        result=client.put(path(c),headers=owner,json=body(c));assert result.status_code==(409 if committed else 200),result.text
        if committed:
            payload=body(c);payload['version']=2;before=read_snapshot(c)
            result=client.put(path(c),headers=owner,json=payload);assert result.status_code==200,result.text
            assert read_snapshot(c)==before
        assert c.calls==[]
