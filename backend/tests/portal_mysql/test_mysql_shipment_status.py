"""Read-only original shipment commands; actual owned main/JWT/MySQL."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.orm import Session
from app.invoice import shipment_create_service, settlement_policy
from app.invoice.models import Invoice
from app.auth.models import ArkRole
from app.invoice.settlement_models import ShipmentSettlement, SettlementItem, Receivable, SettlementApplication, ReceiptBatch
from app.invoice.settlement_schemas import ShipmentCreate
from app.portal.errors import TransactionBusy
from app.portal.models import AuthorityBarrier
from app.receipt import attachments, remote
from app.receipt.models import Receipt, ReceiptAttachment
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, body_for, path, snapshot, created, login, authorize  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401


def status_path(c): return path(c) + '/submission-status'


def observe(c,client,owner,body,monkeypatch,code=200):
    before=snapshot(c); writes=[]; c.io.clear()
    def capture(connection,cursor,statement,parameters,context,many):
        if statement.lstrip().split(' ',1)[0].upper() in {'INSERT','UPDATE','DELETE','REPLACE'}: writes.append(statement)
    def no_io(*args,**kwargs): raise AssertionError('Original-command inspector must not obtain external evidence')
    with monkeypatch.context() as probe:
        probe.setattr(attachments,'verify_storage',no_io)
        event.listen(c.ctx.engine,'before_cursor_execute',capture)
        try: response=client.post(status_path(c),headers=owner,json=body)
        finally: event.remove(c.ctx.engine,'before_cursor_execute',capture)
    assert response.status_code==code,response.text
    assert response.headers.get('cache-control')=='private, no-store'
    assert response.headers.get('pragma')=='no-cache'
    assert writes==[] and snapshot(c)==before and c.io==[] and c.calls==[]
    return response


@pytest.mark.parametrize('payment',[False,True])
@pytest.mark.parametrize('existing',[False,True])
def test_original_command_status_found_or_absent_zero_write(state_app,payment,existing,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name); root=login(client,c,c.root_name); authorize(client,c,root)
        body=body_for(client,c,owner,payment=payment)
        identity=created(c,body,client.post(path(c),headers=owner,json=body)) if existing else None
        data=observe(c,client,owner,body,monkeypatch).json()['data']
        assert data['request_key']==body['request_key'] and data['invoice']['id']==c.invoice_id
        assert data['state']==('found' if existing else 'not_found')
        if existing:
            assert data['settlement']['id']==identity and data['settlement']['request_key']==body['request_key']
            assert data['settlement']['quote_hash']==body['quote_hash']
            assert data['settlement']['invoice_id']==c.invoice_id
        else: assert 'settlement' not in data


@pytest.mark.parametrize('change',['disabled','roles','invoice','shipment','receipt'])
def test_status_current_revocation_applies_to_old_jwt(state_app,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner)
        created(c,body,client.post(path(c),headers=owner,json=body))
        roles=[c.roles['invoice:write'],c.roles['shipment:write'],c.roles['write']]
        if change=='disabled': update={'is_active':False}
        elif change=='roles': update={'role_ids':[]}
        else:
            roles.remove(c.roles[{'invoice':'invoice:write','shipment':'shipment:write','receipt':'write'}[change]])
            update={'role_ids':roles}
        change_user(client,c,root,update)
        observe(c,client,owner,body,monkeypatch,403)


@pytest.mark.parametrize('payment',[False,True])
def test_status_current_grant_to_old_token_and_optional_receipt_action(state_app,payment,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner,payment=payment)
        change_user(client,c,root,{'role_ids':[]}); old=login(client,c,c.owner_name)
        roles=[c.roles['invoice:write'],c.roles['shipment:write']] + ([c.roles['write']] if payment else [])
        change_user(client,c,root,{'role_ids':roles})
        assert observe(c,client,old,body,monkeypatch).json()['data']['state']=='not_found'


@pytest.mark.parametrize('scope',['all','super_admin'])
def test_status_actual_current_invoice_scope_and_invoice_all_not_substitute(state_app,scope,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner,payment=False); created(c,body,client.post(path(c),headers=owner,json=body))
        with Session(c.ctx.engine) as db:
            db.get(Invoice,c.invoice_id).sales_user_id=c.other_id
            role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin')).id if scope=='super_admin' else c.roles['all']
            db.commit()
        base=[c.roles['invoice:write'],c.roles['shipment:write']]
        change_user(client,c,root,{'role_ids':base+[role]}); old=login(client,c,c.owner_name)
        assert observe(c,client,old,body,monkeypatch).json()['data']['state']=='found'
        change_user(client,c,root,{'role_ids':base+[c.roles['invoice:read_all']]})
        observe(c,client,old,body,monkeypatch,404)


@pytest.mark.parametrize('change',['body','actor','url','item','target'])
def test_status_original_actor_hash_url_and_actual_historical_target(state_app,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner);identity=created(c,body,client.post(path(c),headers=owner,json=body))
        if change=='body': body['payment']['remark']='DIFFERENT FROZEN PRIVATE NOTE'
        elif change=='url': c.invoice_id=c.second_invoice_id
        else:
            with Session(c.ctx.engine) as db:
                if change=='actor': db.get(ShipmentSettlement,identity).created_by=c.other_id
                elif change=='item': db.scalar(select(SettlementItem).where(SettlementItem.settlement_id==identity)).quantity+=1
                else:
                    child=db.scalar(select(SettlementApplication).where(SettlementApplication.settlement_id==identity,SettlementApplication.component=='goods'))
                    receipt=db.get(Receipt,child.receipt_id);db.get(Receivable,receipt.receivable_id).invoice_id=c.second_invoice_id
                db.commit()
        observe(c,client,owner,body,monkeypatch,409)


@pytest.mark.parametrize('change',['not_ready','feature_off','missing_file','paused','cancelled','shipped'])
def test_status_legal_historical_command_not_hidden_by_new_action_conditions(state_app,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner);identity=created(c,body,client.post(path(c),headers=owner,json=body))
        with Session(c.ctx.engine) as db:
            if change=='not_ready': db.get(Invoice,c.invoice_id).sync_status='failed'
            elif change in {'paused','cancelled','shipped'}: db.get(ShipmentSettlement,identity).state=change
            elif change=='missing_file':
                proof=db.get(ReceiptAttachment,body['payment']['attachment_ids'][0]);proof.path='missing-owned-original-file.png'
            db.commit()
        if change=='feature_off': c.app.settings.PRESALE_SETTLEMENT_ENABLED=False
        data=observe(c,client,owner,body,monkeypatch).json()['data']
        assert data['state']=='found' and data['settlement']['id']==identity


def test_status_does_not_cancel_or_write_an_original_inflight_create(state_app,monkeypatch):
    c=state_app; ready=threading.Event();resume=threading.Event();original=remote.receipt_types
    def hold(*args,**kwargs): ready.set();assert resume.wait(10);return original(*args,**kwargs)
    with c.app.client() as client,ThreadPoolExecutor(max_workers=1) as pool:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner);monkeypatch.setattr(remote,'receipt_types',hold)
        posted=pool.submit(client.post,path(c),headers=owner,json=deepcopy(body))
        try:
            assert ready.wait(5)
            data=observe(c,client,owner,body,monkeypatch).json()['data']
            assert data['state']=='not_found' and not posted.done()
        finally: resume.set()
        # The inspector's zero-I/O probe must not affect the original create's
        # own later file evidence: remove that temporary probe before it resumes.
        identity=created(c,body,posted.result(timeout=10))
        assert observe(c,client,owner,body,monkeypatch).json()['data']['settlement']['id']==identity


@pytest.mark.parametrize('case',['anonymous','invalid','missing','invalid_id'])
def test_status_dependency_and_validation_errors_private_no_input_echo(state_app,case,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner,payment=False)
        if case=='anonymous':owner={}
        elif case=='invalid':owner={'Authorization':'Bearer invalid.synthetic.token'}
        elif case=='missing':body={'request_key':'PRIVATE_INVALID_MARKER'}
        else:c.invoice_id='PRIVATE_INVALID_MARKER'
        response=observe(c,client,owner,body,monkeypatch,403 if case=='anonymous' else 401 if case=='invalid' else 422)
        assert 'PRIVATE_INVALID_MARKER' not in response.text


@pytest.mark.parametrize('fault',['sql','busy'])
def test_status_database_failure_never_becomes_absence(state_app,fault,monkeypatch):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=body_for(client,c,owner,payment=False);hits=[]
        def fail(connection,cursor,statement,parameters,context,many):
            if AuthorityBarrier.__tablename__ in statement:
                hits.append(fault);raise SQLAlchemyError('PRIVATE_STATUS_QUERY') if fault=='sql' else TransactionBusy()
        event.listen(c.ctx.engine,'before_cursor_execute',fail)
        try: response=observe(c,client,owner,body,monkeypatch,503)
        finally: event.remove(c.ctx.engine,'before_cursor_execute',fail)
        assert hits and 'not_found' not in response.text and 'PRIVATE_STATUS_QUERY' not in response.text


def test_status_dirty_caller_not_flushed_or_rolled_back(state_app):
    c=state_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name);authorize(client,c,root)
        body=ShipmentCreate(**body_for(client,c,owner,payment=False))
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);original=invoice.customer_name;invoice.customer_name='Pending caller data'
        with pytest.raises(HTTPException) as raised: shipment_create_service.submission_status(db,c.invoice_id,body,{'sub':str(c.ctx.actor)})
        assert raised.value.status_code==409 and invoice in db.dirty and invoice.customer_name=='Pending caller data'
        with Session(c.ctx.engine) as independent: assert independent.get(Invoice,c.invoice_id).customer_name==original


@pytest.mark.parametrize('payment',[False,True])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_status_after_exact_original_business_commit_failure(state_app,payment,timing,monkeypatch):
    c=state_app;sessions=[];hits=[];original=shipment_create_service._authorize
    def track(db,*args):
        if not any(db is known for known in sessions):sessions.append(db)
        return original(db,*args)
    with c.app.client() as client:
        root=login(client,c,c.root_name);authorize(client,c,root);owner=login(client,c,c.owner_name)
        body=body_for(client,c,owner,payment=payment);before=snapshot(c)
        monkeypatch.setattr(shipment_create_service,'_authorize',track)
        def fail(db):
            if any(db is known for known in sessions):
                count=db.info.get('owned_status_original_commit',0)+1;db.info['owned_status_original_commit']=count
                if count==3:hits.append(id(db));raise OperationalError('PRIVATE_STATUS_ACK',{},Exception('PRIVATE_DRIVER'))
        event.listen(Session,timing,fail)
        try:response=client.post(path(c),headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert len(sessions)==1 and hits==[id(sessions[0])]
        assert response.status_code==503 and response.headers['cache-control']=='private, no-store'
        assert 'PRIVATE' not in response.text
        if timing=='before_commit':assert snapshot(c)==before
        data=observe(c,client,owner,body,monkeypatch).json()['data']
        assert data['state']==('found' if timing=='after_commit' else 'not_found')
        original_id=data['settlement']['id'] if timing=='after_commit' else None
        replay=client.post(path(c),headers=owner,json=body)
        identity=created(c,body,replay)
        if original_id is not None:assert identity==original_id
        assert observe(c,client,owner,body,monkeypatch).json()['data']['settlement']['id']==identity
