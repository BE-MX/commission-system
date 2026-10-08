"""Read-only original-command observation; real ASGI/JWT/owned MySQL, synthetic upstream."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.auth.models import ArkUser
from app.portal.models import AuthorityBarrier
from app.portal.errors import TransactionBusy
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, Receivable
from app.invoice.settlement_schemas import BatchCreate
from app.receipt import attachments, batch_create_service, fees, remote
from app.receipt.models import Receipt, ReceiptAttachment
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app, payload, created, financial_snapshot  # noqa: F401

PATH='/api/receipts/batches/submission-status'

def observe(c, client, headers, body, monkeypatch, status=200):
    def forbidden(*args,**kwargs):raise AssertionError('Status must not perform provider or storage IO')
    monkeypatch.setattr(fees,'read_evidence',forbidden)
    monkeypatch.setattr(remote,'order_snapshot',forbidden)
    monkeypatch.setattr(attachments,'verify_storage',forbidden)
    before=financial_snapshot(c);c.io.clear();writes=[]
    def probe(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE','REPLACE'}:writes.append(statement)
    event.listen(c.ctx.engine,'before_cursor_execute',probe)
    try:response=client.post(PATH,headers=headers,json=body)
    finally:event.remove(c.ctx.engine,'before_cursor_execute',probe)
    assert response.status_code==status,response.text
    assert response.headers['cache-control']=='private, no-store'
    assert financial_snapshot(c)==before and writes==[] and c.io==[] and c.calls==[]
    return response


@pytest.mark.parametrize('state',['absent','active','not_ready','voided','missing_file'])
def test_original_status_is_authorized_read_only_not_new_business_validation(batch_create_app,state,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);body=payload(client,c,owner)
        identity=None
        if state!='absent':identity=created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        if state=='not_ready':
            with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sync_status='failed';db.commit()
        if state=='voided':
            result=client.post('/api/receipts/batches/'+str(identity)+'/void-entry',headers=root,json={'version':1,'reason':'Correct original entry'})
            assert result.status_code==200,result.text
        if state=='missing_file':
            with Session(c.ctx.engine) as db:attachments.path_for(db.get(ReceiptAttachment,body['attachment_ids'][0])).unlink()
        response=observe(c,client,owner,body,monkeypatch).json()['data']
        assert response['request_key']==body['request_key']
        if state=='absent':
            assert response['state']=='not_found' and set(response)=={'state','request_key','invoices'}
            assert {row['id'] for row in response['invoices']}=={row['invoice_id'] for row in body['allocations']}
            assert all(set(row)=={'id','invoice_no','customer_id','customer_name','currency'} for row in response['invoices'])
        else:assert response['state']=='found' and response['batch']['id']==identity and response['batch']['request_key']==body['request_key']


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('revoke',['disabled','write'])
def test_status_checks_current_authority_before_private_original_receipt(batch_create_app,existing,revoke,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);body=payload(client,c,owner)
        if existing:created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        change_user(client,c,root,{'is_active':False} if revoke=='disabled' else {'role_ids':[c.roles['read']]})
        response=observe(c,client,owner,body,monkeypatch,403)
        assert 'batch_no' not in response.text and 'customer_name' not in response.text


@pytest.mark.parametrize('change',['body','actor','target'])
def test_status_checks_original_actor_hash_and_actual_historical_target(batch_create_app,change,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        identity=created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        if change=='body':body['remark']='Different frozen command'
        else:
            with Session(c.ctx.engine) as db:
                if change=='actor':db.get(ReceiptBatch,identity).created_by=c.other_id
                else:
                    child=db.scalar(select(Receipt).where(Receipt.batch_id==identity,Receipt.invoice_id==c.invoice_id))
                    wrong_key='invoice:wrong-'+uuid4().hex+':goods'
                    db.get(Receivable,child.receivable_id).business_key=wrong_key
                db.commit()
                if change=='target':
                    with Session(c.ctx.engine) as independent:
                        assert independent.get(Receivable,child.receivable_id).business_key==wrong_key
        observe(c,client,owner,body,monkeypatch,409)


def test_status_absence_does_not_cancel_an_original_inflight_create(batch_create_app,monkeypatch):
    c=batch_create_app;ready=threading.Event();resume=threading.Event();original=fees.read_evidence;hits=[]
    def gate(*args,**kwargs):
        if not hits:hits.append(True);ready.set();assert resume.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(fees,'read_evidence',gate)
    with c.app.client() as client,ThreadPoolExecutor(max_workers=1) as executor:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        future=executor.submit(client.post,'/api/receipts/batches',headers=owner,json=deepcopy(body))
        try:
            assert ready.wait(10)
            before=financial_snapshot(c);io=list(c.io)
            absent=client.post(PATH,headers=owner,json=body)
            assert absent.status_code==200 and absent.json()['data']['state']=='not_found',absent.text
            assert not future.done() and financial_snapshot(c)==before and c.io==io and c.calls==[]
        finally:resume.set()
        identity=created(c,body,future.result(timeout=15))
        found=observe(c,client,owner,body,monkeypatch).json()['data']
        assert found['state']=='found' and found['batch']['id']==identity
        with Session(c.ctx.engine) as db:assert db.query(ReceiptBatch).filter_by(request_key=body['request_key']).count()==1


def test_status_refuses_a_dirty_caller_without_flushing_or_rolling_back_it(batch_create_app):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=BatchCreate(**payload(client,c,owner))
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);original=invoice.customer_name;invoice.customer_name='Pending caller data'
        with pytest.raises(HTTPException) as raised:batch_create_service.submission_status(db,body,{'sub':str(c.ctx.actor)})
        assert raised.value.status_code==409 and invoice in db.dirty and invoice.customer_name=='Pending caller data'
        with Session(c.ctx.engine) as independent:assert independent.get(Invoice,c.invoice_id).customer_name==original
        db.rollback()


@pytest.mark.parametrize('case',['anonymous','invalid_token','missing_fields','allocation_total'])
def test_status_no_store_includes_dependency_and_validation_failures(batch_create_app,case):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner);headers=owner
        if case=='anonymous':headers={}
        elif case=='invalid_token':headers={'Authorization':'Bearer invalid.synthetic.token'}
        elif case=='missing_fields':body={}
        else:body['remark']='Private frozen financial note';body['amount']='30'
        before=financial_snapshot(c);c.io.clear()
        response=client.post(PATH,headers=headers,json=body)
        assert response.status_code==({'anonymous':403,'invalid_token':401}.get(case,422)),response.text
        assert financial_snapshot(c)==before and c.io==[] and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store',response.headers
        assert response.headers.get('pragma')=='no-cache'
        assert 'Private frozen financial note' not in response.text


@pytest.mark.parametrize('existing',[False,True])
def test_status_another_real_actor_scope_and_current_grant_with_old_jwt(batch_create_app,existing,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);body=payload(client,c,owner)
        if existing:created(c,body,client.post('/api/receipts/batches',headers=owner,json=body))
        with Session(c.ctx.engine) as db:other_name=db.get(ArkUser,c.other_id).username
        role=client.put('/api/auth/users/'+str(c.other_id),headers=root,json={'role_ids':[c.roles['write']]})
        assert role.status_code==200,role.text
        other=login(client,c,other_name)
        denied=observe(c,client,other,body,monkeypatch,404)
        assert 'customer_name' not in denied.text and 'batch_no' not in denied.text
        role=client.put('/api/auth/users/'+str(c.other_id),headers=root,json={'role_ids':[c.roles['all']]})
        assert role.status_code==200,role.text
        # Current scope grants apply to an old token; an existing command still belongs to its original actor.
        response=observe(c,client,other,body,monkeypatch,409 if existing else 200)
        if not existing:assert response.json()['data']['state']=='not_found'
        response=observe(c,client,owner,body,monkeypatch)
        assert response.json()['data']['state']==('found' if existing else 'not_found')


@pytest.mark.parametrize('fault',['sql','busy'])
def test_status_unknown_database_read_never_becomes_absence(batch_create_app,fault,monkeypatch):
    c=batch_create_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);body=payload(client,c,owner)
        def fail(conn,cursor,statement,parameters,context,many):
            if AuthorityBarrier.__tablename__ in statement:
                raise SQLAlchemyError('private-status-database-details') if fault=='sql' else TransactionBusy()
        event.listen(c.ctx.engine,'before_cursor_execute',fail)
        try:response=observe(c,client,owner,body,monkeypatch,503)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',fail)
        assert 'not_found' not in response.text and 'private-status-database-details' not in response.text
