"""Actual employee freight reconciliation on owned JWT/main/MySQL."""
from copy import deepcopy
from uuid import uuid4
from datetime import timedelta
from app.core.time import beijing_now
import pytest
from sqlalchemy import select, text
from concurrent.futures import ThreadPoolExecutor
import queue
import threading
from test_mysql_concurrency import wait_for_lock
from sqlalchemy.orm import Session
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import Receivable, ShipmentSettlement, SettlementEvent
from app.receipt import remote
from app.receipt.models import Receipt
from app.semifinished.models import InvoiceAllocation
from app.invoice import freight_reconciliation_service
from app.invoice.settlement_schemas import SettlementRemoteReview
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
ACTUAL_ORDER_ACTIVE=remote.order_active
from test_mysql_shipment_retry import prepare as retry_prepare
from test_mysql_shipment_state import state_app  # noqa: F401
from test_mysql_shipment_create import shipment_app, snapshot, login, change_user  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app  # noqa: F401
from test_mysql_receipt_reads import read_app  # noqa: F401
from test_mysql_receipt_batch_create import batch_create_app  # noqa: F401

MODES=('bind','refresh')

def route(c):return f'/api/shipments/{c.settlement_id}/reconcile-freight'

def prepare(c,client,mode,monkeypatch):
    root,_,body=retry_prepare(c,client,'freight',monkeypatch)
    with Session(c.ctx.engine) as db:
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code=='shipment:admin'))
        if permission is None:
            permission=ArkPermission(code='shipment:admin',module='shipment',action='admin',label='shipment:admin',kind='action',is_legacy=False,sort=1)
            db.add(permission);db.flush()
        role=ArkRole(name='freight-admin-'+uuid4().hex,label='Freight admin');db.add(role);db.flush()
        db.add(ArkRolePermission(role_id=role.id,permission_id=permission.id));c.roles['shipment:admin']=role.id
        target=db.get(Receivable,c.target_id);target.remote_status='uncertain'
        target.attempt_token='original-'+str(target.id);target.lease_until=beijing_now()-timedelta(hours=1);target.last_error='Original unknown result'
        if mode=='refresh':target.remote_order_id='301'
        c.detail={'order_id':'301','name':target.remote_order_name,'company_id':target.customer_id,
            'currency':target.currency,'amount':str(target.amount),'product_total_amount':'0.00',
            'product_total_count':0,'product_list':[],'create_time':'2026-10-06 08:00:00'}
        db.commit()
    c.grants=c.shipment_roles+([c.roles['shipment:admin']] if mode=='bind' else [])
    change_user(client,c,root,{'role_ids':c.grants});owner=login(client,c,c.owner_name)
    if mode=='bind':body['remote_id']='301'
    c.reads=[]
    def read(db,path,params=None):
        c.reads.append((path,deepcopy(params)));return deepcopy(c.detail)
    monkeypatch.setattr(remote,'read',read);monkeypatch.setattr(remote,'order_active',lambda *_:True)
    c.io.clear();return root,owner,body

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('revoke',['disabled','roles','shipment:write'])
def test_freight_reconcile_current_revocation_before_read(state_app,mode,revoke,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,mode,monkeypatch)
        update={'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['shipment:admin']]}
        change_user(client,c,root,update);before=snapshot(c)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==403,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before and c.reads==[] and c.calls==[]

@pytest.mark.parametrize('mode',MODES)
def test_freight_reconcile_current_grant_to_old_empty_token(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,_,body=prepare(c,client,mode,monkeypatch)
        change_user(client,c,root,{'role_ids':[]});old=login(client,c,c.owner_name)
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write']]+([c.roles['shipment:admin']] if mode=='bind' else [])})
        before=snapshot(c)
        response=client.post(route(c),headers=old,json=body)
        assert response.status_code==200,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        with Session(c.ctx.engine) as db:
            target=db.get(Receivable,c.target_id)
            assert target.remote_status=='bound' and target.remote_order_id=='301'
            assert db.query(SettlementEvent).filter_by(settlement_id=c.settlement_id,action='reconcile_freight',actor_id=c.ctx.actor,reason=body['reason']).count()==1
        assert c.calls==[]
        freight_delta(c,before,body,valid=True)


def freight_delta(c,before,body,*,valid):
    after=snapshot(c)
    expected=[[deepcopy(dict(row._mapping)) for row in table] for table in before]
    actual=[[deepcopy(dict(row._mapping)) for row in table] for table in after]
    assert len(expected)==len(actual)==21
    targets=[table for table in expected if table and {'remote_order_name','remote_status','amount'}<=table[0].keys()]
    assert len(targets)==1
    target=next(row for row in targets[0] if row['id']==c.target_id)
    if body.get('remote_id'):target['remote_order_id']=body['remote_id']
    target.update(remote_status='bound' if valid else 'uncertain',
        last_error=None if valid else '小满运费订单身份或金额与冻结目标不一致，请核对原单',
        version=target['version']+(2 if body.get('remote_id') else 1))
    old_ids={row['id'] for row in expected[20]}
    added=[row for row in actual[20] if row['id'] not in old_ids]
    assert len(added)==1
    entry=added[0]
    assert (entry['settlement_id'],entry['action'],entry['actor_id'],entry['reason'])==(c.settlement_id,'reconcile_freight',c.ctx.actor,body['reason'])
    assert entry['created_at'] is not None
    expected[20].append(entry);expected[20].sort(key=lambda row:row['id'])
    assert expected==actual
    return after


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('change',['disabled','write','owner','invoice','item','receipt','target','settlement'])
def test_final_current_graph_after_unlocked_freight_read(state_app,mode,change,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,mode,monkeypatch);baselines=[];reads=[]
        def read(db,path,params=None):
            with Session(c.ctx.engine) as other:
                invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update(nowait=True))
                assert invoice.id==c.invoice_id
                if change=='owner':invoice.sales_user_id=c.other_id
                elif change=='invoice':invoice.customer_name='Concurrent change'
                elif change=='item':other.get(InvoiceItem,c.item_id).quantity+=1
                elif change=='receipt':other.get(Receipt,c.receipts['victim']).bank_charge+=1
                elif change=='target':other.get(Receivable,c.target_id).version+=1
                elif change=='settlement':other.get(ShipmentSettlement,c.settlement_id).version+=1
                other.commit()
            if change in {'disabled','write'}:
                change_user(client,c,root,{'is_active':False} if change=='disabled' else {'role_ids':[c.roles['shipment:admin']]})
            baselines.append(snapshot(c));reads.append(deepcopy(params));return deepcopy(c.detail)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(403 if change in {'disabled','write'} else 404 if change=='owner' else 409),response.text
        assert reads==[{'order_id':'301'}] and snapshot(c)==baselines[0] and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store'


def test_manual_bind_rechecks_current_admin_after_read(state_app,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,'bind',monkeypatch);baselines=[]
        def read(*args):
            change_user(client,c,root,{'role_ids':[c.roles['shipment:write']]});baselines.append(snapshot(c));return deepcopy(c.detail)
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==403 and snapshot(c)==baselines[0] and c.calls==[]


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('difference',['inactive','name','amount','customer','currency','goods','count','products','identity'])
def test_manual_reject_vs_known_target_quarantine_preserves_financial_algorithm(state_app,mode,difference,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);before=snapshot(c)
        if difference=='inactive':monkeypatch.setattr(remote,'order_active',lambda *_:False)
        else:
            field,value={'name':('name','Other original'), 'amount':('amount','19.00'),
                'customer':('company_id','Other customer'),'currency':('currency','EUR'),
                'goods':('product_total_amount','1.00'),'count':('product_total_count',1),
                'products':('product_list',[{'product_id':'7'}]),'identity':('order_id','302')}[difference]
            c.detail[field]=value
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(409 if mode=='bind' else 200),response.text
        if mode=='bind':assert snapshot(c)==before
        else:freight_delta(c,before,body,valid=False)
        assert c.calls==[] and response.headers.get('cache-control')=='private, no-store'


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('fault',['list','name','count','false_id','false_count','nan','time','activity_shape','activity_exception','provider'])
def test_freight_detail_technical_failure_never_binds_or_quarantines(state_app,mode,fault,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);before=snapshot(c)
        if fault=='list':monkeypatch.setattr(remote,'read',lambda *_:[])
        elif fault=='activity_shape':monkeypatch.setattr(remote,'order_active',lambda *_:None)
        elif fault in {'activity_exception','provider'}:
            def fail(*args):raise ValueError('PRIVATE_ACTIVE') if fault=='activity_exception' else freight_reconciliation_service.okki_client.OkkiApiError('PRIVATE_PROVIDER')
            monkeypatch.setattr(remote,'order_active' if fault=='activity_exception' else 'read',fail)
        else:
            field,value={'name':('name',None),'count':('product_total_count','bad'),
                'false_id':('order_id',True),'false_count':('product_total_count',False),
                'nan':('amount','NaN'),'time':('create_time','not-a-date')}[fault]
            c.detail[field]=value
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==503,response.text
        assert 'PRIVATE_' not in response.text and snapshot(c)==before and c.calls==[]
        assert response.headers.get('cache-control')=='private, no-store'


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_exact_third_freight_commit_ack_and_original_state_recovery(state_app,mode,timing,monkeypatch):
    c=state_app;sessions=[];hits=[];original=freight_reconciliation_service._capture
    def track(db,*args):
        if not any(db is item for item in sessions):sessions.append(db)
        return original(db,*args)
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);before=snapshot(c)
        monkeypatch.setattr(freight_reconciliation_service,'_capture',track)
        def fail(db):
            if any(db is item for item in sessions):
                count=db.info.get('freight_commit',0)+1;db.info['freight_commit']=count
                if count==3:hits.append(id(db));raise OperationalError('PRIVATE_DB',{},Exception('PRIVATE_ACK'))
        event.listen(Session,timing,fail)
        try:response=client.post(route(c),headers=owner,json=body)
        finally:event.remove(Session,timing,fail)
        assert len(sessions)==1 and hits==[id(sessions[0])]
        assert response.status_code==503 and 'PRIVATE_' not in response.text,response.text
        if timing=='before_commit':assert snapshot(c)==before
        else:
            retained=freight_delta(c,before,body,valid=True)
            current=client.get(f'/api/shipments/{c.settlement_id}',headers=owner)
            assert current.status_code==200 and current.json()['data']['version']==body['version']
            assert current.json()['data']['freight_target']['status']=='bound' and snapshot(c)==retained
            if mode=='bind':
                again=client.post(route(c),headers=owner,json=body)
                assert again.status_code==409 and snapshot(c)==retained
            # Known-ID refresh remains a repeatable observation, not a keyed command.
        assert c.calls==[]


@pytest.mark.parametrize('mode',MODES)
def test_freight_reconcile_dirty_caller_rejection_preserves_pending_changes(state_app,mode,monkeypatch):
    c=state_app
    with c.app.client() as client:_,_,body=prepare(c,client,mode,monkeypatch)
    with Session(c.ctx.engine) as db:
        invoice=db.get(Invoice,c.invoice_id);before=invoice.customer_name;invoice.customer_name='Pending caller edit'
        with pytest.raises(HTTPException) as raised:freight_reconciliation_service.reconcile(db,c.settlement_id,SettlementRemoteReview(**body),{'sub':str(c.ctx.actor)})
        assert raised.value.status_code==409 and invoice in db.dirty and invoice.customer_name=='Pending caller edit'
        with Session(c.ctx.engine) as other:assert other.get(Invoice,c.invoice_id).customer_name==before


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('scope',['invoice_all','receipt_all'])
def test_freight_scope_is_actual_financial_invoice_scope(state_app,mode,scope,monkeypatch):
    c=state_app
    with c.app.client() as client:
        root,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:db.get(Invoice,c.invoice_id).sales_user_id=c.other_id;db.commit()
        change_user(client,c,root,{'role_ids':[c.roles['shipment:write'],c.roles['invoice:read_all'] if scope=='invoice_all' else c.roles['all']]+([c.roles['shipment:admin']] if mode=='bind' else [])})
        before=snapshot(c);response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==(404 if scope=='invoice_all' else 200),response.text
        if scope=='invoice_all':assert snapshot(c)==before and c.reads==[]
        else:freight_delta(c,before,body,valid=True)


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('observation',['active','absent','bad_list','bad_count'])
def test_actual_active_order_scanner_shapes_and_presence(state_app,mode,observation,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch);before=snapshot(c);reads=[]
        monkeypatch.setattr(remote,'order_active',ACTUAL_ORDER_ACTIVE)
        def read(db,path,params=None):
            reads.append((path,deepcopy(params)))
            if path.endswith('/info'):return deepcopy(c.detail)
            assert path=='/v1/invoices/order/list'
            return [] if observation=='bad_list' else {'list':[],'count':'bad'} if observation=='bad_count' else {'list':[{'order_id':'301'}],'count':1} if observation=='active' else {'list':[],'count':0}
        monkeypatch.setattr(remote,'read',read)
        response=client.post(route(c),headers=owner,json=body)
        wanted=503 if observation.startswith('bad') else 409 if observation=='absent' and mode=='bind' else 200
        assert response.status_code==wanted,response.text
        if wanted!=200:assert snapshot(c)==before
        else:freight_delta(c,before,body,valid=observation=='active')
        assert len(reads)==(2 if observation.startswith('bad') else 3) and c.calls==[]


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('history',['uncertain','unsynced','allocation'])
def test_existing_freight_recovery_not_blocked_by_new_order_ready_rules(state_app,mode,history,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as db:
            invoice=db.get(Invoice,c.invoice_id)
            if history=='uncertain':invoice.sync_status='uncertain'
            elif history=='unsynced':invoice.status='draft';invoice.sync_status='pending'
            else:db.add(InvoiceAllocation(invoice_id=c.invoice_id,status='pending'))
            db.commit()
        before=snapshot(c)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==200,response.text
        assert c.reads==[('/v1/invoices/order/info',{'order_id':'301'})] and c.calls==[]
        freight_delta(c,before,body,valid=True)


@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('change',['owner','target'])
def test_current_owner_and_target_after_actual_invoice_lock_wait(state_app,mode,change,monkeypatch):
    c=state_app;started=queue.Queue();locked=threading.Event();resume=threading.Event();target={}
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            target['connection']=connection;started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    def hold(connection,cursor,statement,parameters,context,executemany):
        if connection is target.get('connection') and 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper() and not locked.is_set():
            locked.set();assert resume.wait(10)
    with c.app.client() as client:
        _,owner,body=prepare(c,client,mode,monkeypatch)
        with Session(c.ctx.engine) as other,ThreadPoolExecutor(max_workers=1) as pool:
            invoice=other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
            if change=='owner':invoice.sales_user_id=c.other_id
            else:other.get(Receivable,c.target_id).customer_id='Concurrent foreign customer'
            other.flush()
            event.listen(c.ctx.engine,'before_cursor_execute',observe);event.listen(c.ctx.engine,'after_cursor_execute',hold)
            action=pool.submit(client.post,route(c),headers=owner,json=body)
            try:
                wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not action.done()
                other.commit();assert locked.wait(5) and not action.done()
                before=snapshot(c);resume.set();response=action.result(timeout=5)
            finally:
                resume.set();other.rollback()
                event.remove(c.ctx.engine,'before_cursor_execute',observe);event.remove(c.ctx.engine,'after_cursor_execute',hold)
        assert response.status_code==(404 if change=='owner' else 409),response.text
        assert snapshot(c)==before and c.reads==[] and c.calls==[]


@pytest.mark.parametrize('remote_id',['0','0301','３０１','broken'])
def test_invalid_persisted_freight_remote_identity_is_private_conflict_before_io(state_app,remote_id,monkeypatch):
    c=state_app
    with c.app.client() as client:
        _,owner,body=prepare(c,client,'refresh',monkeypatch)
        with Session(c.ctx.engine) as db:db.get(Receivable,c.target_id).remote_order_id=remote_id;db.commit()
        before=snapshot(c)
        response=client.post(route(c),headers=owner,json=body)
        assert response.status_code==409,response.text
        assert response.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before and c.reads==[] and c.calls==[]
