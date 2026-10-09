"""Actual backend worker/owned MySQL; supplier HTTP and mirror evidence are synthetic."""
from copy import deepcopy
from uuid import uuid4
from datetime import timedelta
import json
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select,text,event,update
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.auth.models import ArkUser
from app.portal.authority import lock_authority
from app.invoice import outbound_worker as worker,outbound_create_facts as facts
from app.invoice.models import Invoice,InvoiceItem,OkkiOutboundTask,InvoiceSyncLog
from app.shipping_inspection.models import ShippingOperationEvent
from app.core.time import beijing_now
from test_mysql_outbound_prepare import setup,snapshot
from test_mysql_invoice_cancellation_refresh import demote_admin


def prepare(editor,monkeypatch,tmp_path):
    actual_find=worker.followup.legacy.linked_outbound_service.find_related
    c=setup(editor,monkeypatch,tmp_path)
    settings=worker.get_settings()
    monkeypatch.setattr(settings,'PORTAL_ENABLED',True)
    monkeypatch.setattr(settings,'PORTAL_OUTBOUND_WORKER_ENABLED',True)
    monkeypatch.setattr(settings,'PORTAL_OUTBOUND_WORKER_ACTOR_ID',editor.ctx.admin)
    monkeypatch.setattr(settings,'OKKI_OUTBOUND_AUTO_ENABLED',True)
    with Session(editor.ctx.engine) as db:
        lock_authority(db,force=True);invoice=worker.edit_authority.lock_document(db,editor.invoice_id,force=True)
        # This owned fixture supplies HTTP evidence for this invoice only. Other
        # fixture invoices must not become work for the same actual scheduler tick.
        db.execute(update(Invoice).where(Invoice.id!=editor.invoice_id).values(outbound_auto_requested=0))
        invoice.outbound_auto_requested=1
        db.add(InvoiceSyncLog(invoice_id=invoice.id,action='create',success=1,operator_id=editor.ctx.admin,
            response_body=json.dumps({'order_id':invoice.xiaoman_order_id})))
        task=OkkiOutboundTask(invoice_id=invoice.id,order_id=invoice.xiaoman_order_id,status='pending')
        db.add(task);db.flush();c.task_id=task.id;c.invoice_no=invoice.invoice_no;db.commit()
    c.created=None;c.gate=None;c.reads=[];c.order['handler']=[str(editor.ctx.actor)]
    c.stock=100;c.posts=[];c.occupant=None;c.original_id=800001+editor.invoice_id*10
    def read(db,path,params):
        c.reads.append(path)
        if c.gate:c.gate(path)
        if path.endswith('/order/info'):return deepcopy(c.order)
        if path.endswith('/outbound/list'):
            return {'count':1 if c.created else 0,'list':[{'outbound_invoice_id':c.created['outbound_invoice_id']}] if c.created else []}
        if path.endswith('/outbound/info'):return deepcopy(c.created)
        if path.endswith('/inventory-list'):
            return {'count':1,'list':[{'sku_id':params['sku_id'],'warehouse_id':'8193514242746',
                'disable_flag':0,'enable_count':c.stock}]}
        raise AssertionError('Unexpected synthetic worker read')
    def serial(db,number):
        c.reads.append('serial')
        if c.gate:c.gate('serial')
        return deepcopy(c.created) if c.created and c.created['serial_id']==number else (deepcopy(c.occupant) if number==c.invoice_no else None)
    def post(url,*,headers,json,timeout):
        assert url.endswith('/v1/invoices/outbound/push')
        if c.gate:c.gate('post')
        c.posts.append(deepcopy(json))
        c.created={'outbound_invoice_id':c.original_id-1+len(c.posts),'serial_id':json['serial_id'],'status':1,'currency':json['currency'],
            'company_info':{'id':json['company_id']},'remark':json['remark'],
            'invoice_warehouse_info':{'id':json['invoice_warehouse_id']},
            'handler_info':[{'user_id':value} for value in json['handler']],
            'exchange_rate':json['exchange_rate'],'exchange_rate_usd':json['exchange_rate_usd'],
            'record_list':[{**row,'outbound_record_id':801+i+100*(len(c.posts)-1)} for i,row in enumerate(json['record_list'])]}
        return httpx.Response(200,json={'code':200,'data':{'outbound_invoice_id':c.created['outbound_invoice_id'],'serial_id':json['serial_id']}})
    monkeypatch.setattr(worker.followup.legacy.remote,'read',read)
    monkeypatch.setattr(worker.followup.legacy.linked_outbound_service,'find_related',actual_find)
    monkeypatch.setattr(worker.okki_client,'find_outbound_by_serial',serial)
    from urllib.parse import urlparse
    def get(url,*,headers,params,timeout):
        return httpx.Response(200,json={'code':200,'data':read(None,urlparse(url).path,params)})
    monkeypatch.setattr(worker.okki_client.httpx,'get',get)
    monkeypatch.setattr(worker.okki_client.httpx,'post',post)
    c.post=post;c.read=read
    return c


def run(c):
    with Session(c.e.ctx.engine) as db:return worker.process(db,c.e.invoice_id)


def records(c,scope):
    with Session(c.e.ctx.engine) as db:
        return [(row.request_id,deepcopy(row.payload),deepcopy(row.result)) for row in db.scalars(
            select(ShippingOperationEvent).where(ShippingOperationEvent.scope==scope,
                ShippingOperationEvent.outbound_record_id=='create:'+str(c.e.invoice_id)).order_by(ShippingOperationEvent.id))]


def task(c):
    with Session(c.e.ctx.engine) as db:return worker.row_state(db.get(OkkiOutboundTask,c.task_id))


def test_worker_creates_original_outbound_once_and_finishes_atomic_task(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path)
    result=run(c);assert result['status']=='done' and result['posted'] is True
    assert len(c.posts)==1 and len(records(c,facts.START))==len(records(c,facts.SEND))==len(records(c,facts.FACT))==len(records(c,facts.FINISH))==1
    assert records(c,facts.FACT)[0][2]['result_class']=='accepted'
    before=snapshot(c);repeat=run(c)
    assert repeat['status']=='done' and len(c.posts)==1 and snapshot(c)==before


@pytest.mark.parametrize('stage',['/order/info','/outbound/list','/inventory-list','serial','post'])
@pytest.mark.parametrize('change',['inactive','permission','scope'])
def test_worker_rechecks_current_actor_after_supplier_windows(editor,monkeypatch,tmp_path,stage,change):
    c=prepare(editor,monkeypatch,tmp_path);before=[]
    def gate(path):
        if not path.endswith(stage):return
        c.gate=None
        with Session(editor.ctx.engine) as db:
            db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
            lock_authority(db,force=True)
            db.scalar(select(Invoice).where(Invoice.id==editor.invoice_id).with_for_update())
            if change=='inactive':db.get(ArkUser,editor.ctx.admin).is_active=False
            db.commit()
        if change!='inactive':demote_admin(editor,[] if change=='permission' else ['invoice:sync'])
        before.append(snapshot(c))
    c.gate=gate
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==(404 if change=='scope' else 403)
    assert len(before)==1
    if stage=='post':
        assert len(c.posts)==1 and len(records(c,facts.FACT))==1 and records(c,facts.FINISH)==[]
        # Only the immutable original FACT may be appended after revocation.
        after=snapshot(c)
        assert after[0]==before[0][0]
        original_events=before[0][1][0];after_events=after[1][0]
        columns=list(ShippingOperationEvent.__table__.columns.keys())
        additions=[row for row in after_events if row not in original_events]
        assert [row for row in after_events if row in original_events]==list(original_events)
        assert len(additions)==1 and additions[0][columns.index('scope')]==facts.FACT
        assert after[1][1:]==before[0][1][1:]
    else:assert c.posts==[] and snapshot(c)==before[0]


def test_worker_waits_for_destination_stock_without_claim_or_post(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path);c.stock=0
    assert run(c)['status']=='waiting_stock' and c.posts==[] and records(c,facts.START)==[]


def test_worker_unknown_result_is_read_only_recovered_without_second_post(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path)
    def timeout(*args,**kwargs):
        c.post(*args,**kwargs);raise httpx.ReadTimeout('Owned synthetic timeout')
    monkeypatch.setattr(worker.okki_client.httpx,'post',timeout)
    assert run(c)['status']=='done' and records(c,facts.FACT)[0][2]['result_class']=='unknown'
    assert len(c.posts)==1


def test_worker_rejects_regeneration_without_permanent_deletion(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        row=db.get(OkkiOutboundTask,c.task_id)
        latest=db.scalar(select(InvoiceSyncLog.id).where(InvoiceSyncLog.invoice_id==editor.invoice_id,InvoiceSyncLog.action=='create'))
        row.reason='regenerate:'+str(latest);db.commit()
    before=snapshot(c)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==409 and c.posts==[] and c.reads==[] and snapshot(c)==before


@pytest.mark.parametrize('field,value',[('invoice_warehouse_info',{'id':'999'}),
    ('invoice_warehouse_info',None),('handler_info',[{'user_id':'999'}]),
    ('handler_info',None),('exchange_rate','999'),('exchange_rate_usd',None)])
def test_worker_does_not_finish_wrong_or_missing_command_headers(editor,monkeypatch,tmp_path,field,value):
    c=prepare(editor,monkeypatch,tmp_path)
    def post(*args,**kwargs):
        response=c.post(*args,**kwargs);c.created[field]=value;return response
    monkeypatch.setattr(worker.okki_client.httpx,'post',post)
    assert run(c)['status']=='uncertain'
    assert len(c.posts)==1 and len(records(c,facts.FACT))==1 and records(c,facts.FINISH)==[]
    with Session(editor.ctx.engine) as db:
        assert db.get(OkkiOutboundTask,c.task_id).status=='uncertain'


@pytest.mark.parametrize('rows',[None,[],[{'order_id':'0007','order_record_id':'1','outbound_record_id':'8'}],
    'missing',{},[{}],[{'order_id':True,'order_record_id':'1','outbound_record_id':'8'}]])
def test_worker_unknown_serial_detail_cannot_select_fallback(editor,monkeypatch,tmp_path,rows):
    c=prepare(editor,monkeypatch,tmp_path)
    c.occupant={'outbound_invoice_id':'999','serial_id':c.invoice_no,'record_list':rows}
    if rows=='missing':c.occupant.pop('record_list')
    before=snapshot(c)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==503 and c.posts==[] and records(c,facts.START)==[] and snapshot(c)==before


def test_worker_confirmed_other_order_serial_allows_vacant_fallback(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path)
    c.occupant={'outbound_invoice_id':'999','serial_id':c.invoice_no,'record_list':[
        {'order_id':'999','order_record_id':'1','outbound_record_id':'8','product_id':'9','sku_id':'10'}]}
    assert run(c)['status']=='done' and len(c.posts)==1
    assert c.posts[0]['serial_id']==c.invoice_no+' ['+str(c.order['order_id'])+']'


@pytest.mark.parametrize('unavailable',[False,True])
def test_worker_scheduler_processes_valid_item_after_twenty_blocked_items(editor,monkeypatch,tmp_path,unavailable):
    c=prepare(editor,monkeypatch,tmp_path);blocked=[];queue_prefix='QUEUE-'+uuid4().hex[:16]
    with Session(editor.ctx.engine) as db:
        original=db.get(Invoice,editor.invoice_id)
        values={column.key:getattr(original,column.key) for column in Invoice.__table__.columns if column.key!='id'}
        items=db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id==original.id)).all()
        old_task=db.get(OkkiOutboundTask,c.task_id);old_task.status='pending' if unavailable else 'running';blocked.append(old_task.id)
        if unavailable:
            original.xiaoman_order_id=old_task.order_id='99999999'
            db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==original.id,InvoiceSyncLog.action=='create')).response_body=json.dumps({'order_id':'99999999'})
        for index in range(20):
            cloned=Invoice(**{**values,'invoice_no':queue_prefix+'-'+str(index)})
            db.add(cloned);db.flush()
            for item in items:
                data={column.key:getattr(item,column.key) for column in InvoiceItem.__table__.columns if column.key not in ('id','invoice_id')}
                db.add(InvoiceItem(**data,invoice_id=cloned.id))
            db.add(InvoiceSyncLog(invoice_id=cloned.id,action='create',success=1,operator_id=editor.ctx.admin,
                response_body=json.dumps({'order_id':cloned.xiaoman_order_id})))
            entry=OkkiOutboundTask(invoice_id=cloned.id,order_id=cloned.xiaoman_order_id,
                status='pending' if index==19 else 'running')
            db.add(entry);db.flush()
            if index==19:editor.invoice_id=cloned.id;c.task_id=entry.id;c.invoice_no=cloned.invoice_no
            else:blocked.append(entry.id)
        db.commit()
        blocked_before=[worker.row_state(db.get(OkkiOutboundTask,identity)) for identity in blocked]
        assert len(blocked)==20 and all(db.get(OkkiOutboundTask,identity).invoice_id<editor.invoice_id for identity in blocked)
    failures=[]
    if unavailable:
        def supplier(db,path,params):
            if str(params.get('order_id'))=='99999999':
                failures.append(True);raise worker.okki_client.OkkiApiError('Owned unavailable evidence')
            return c.read(db,path,params)
        monkeypatch.setattr(worker.followup.legacy.remote,'read',supplier)
    pages=[]
    def observe(conn,cursor,statement,parameters,context,executemany):
        if 'ORDER BY ark_invoices.id' in statement and 'LIMIT' in statement:pages.append(parameters)
    event.listen(editor.ctx.engine,'before_cursor_execute',observe)
    try:result=worker.run_once(lambda:Session(editor.ctx.engine))
    finally:event.remove(editor.ctx.engine,'before_cursor_execute',observe)
    assert result['status']=='processed' and len(c.posts)==1 and len(pages)>=2
    assert failures==([True] if unavailable else [])
    with Session(editor.ctx.engine) as db:
        assert db.get(OkkiOutboundTask,c.task_id).status=='done'
        assert db.get(worker.AuthorityBarrier,worker.MODE) is not None
        assert [worker.row_state(db.get(OkkiOutboundTask,identity)) for identity in blocked]==blocked_before


@pytest.mark.parametrize('phase',[facts.START,facts.SEND,facts.FACT,facts.FINISH])
@pytest.mark.parametrize('lost_ack',[False,True])
def test_worker_commit_failures_and_lost_ack_preserve_single_send(editor,monkeypatch,tmp_path,phase,lost_ack):
    c=prepare(editor,monkeypatch,tmp_path);hit=[];original_commit=Session.commit
    def gate(db):
        found=db.in_transaction() and db.connection().scalar(select(ShippingOperationEvent.id).where(
            ShippingOperationEvent.scope==phase,ShippingOperationEvent.outbound_record_id=='create:'+str(editor.invoice_id))) is not None
        if found and not hit:
            hit.append(phase)
            if lost_ack:original_commit(db)
            raise OperationalError('Owned synthetic commit boundary',None,RuntimeError('ACK unavailable'))
        return original_commit(db)
    monkeypatch.setattr(Session,'commit',gate)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==503 and hit==[phase]
    assert len(c.posts)==(1 if phase in (facts.FACT,facts.FINISH) else 0)
    assert len(records(c,phase))==(1 if lost_ack else 0)
    monkeypatch.setattr(Session,'commit',original_commit)
    monkeypatch.setattr(worker,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
    result=run(c)
    if phase==facts.SEND and lost_ack:
        assert result['status']=='uncertain' and c.posts==[] and records(c,facts.FINISH)==[]
        assert run(c)['status']=='uncertain' and c.posts==[]
    else:
        assert result['status']=='done' and len(c.posts)==1
        before=snapshot(c);assert run(c)['status']=='done' and len(c.posts)==1 and snapshot(c)==before


def test_worker_regeneration_preserves_deleted_identity_after_stock_wait(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path);c.stock=0
    with Session(editor.ctx.engine) as db:
        latest=db.scalar(select(InvoiceSyncLog.id).where(InvoiceSyncLog.invoice_id==editor.invoice_id,InvoiceSyncLog.action=='create'))
        row=db.get(OkkiOutboundTask,c.task_id);row.reason='regenerate:'+str(latest)
        db.add(ShippingOperationEvent(scope='outbound-delete',request_id=str(c.original_id),action='outbound_deleted',
            source='pc',operator_user_id=editor.ctx.admin,login_user_id=editor.ctx.admin,
            operator_name='Isolated',login_name='Isolated',outbound_record_id=str(c.original_id),
            created_at=beijing_now()-timedelta(minutes=10),payload={'outbound_invoice_id':str(c.original_id),
                'order_ids':[str(c.order['order_id'])],'tasks':[{'id':c.task_id,'status':'done','reason':None}]}))
        db.commit()
    c.occupant={**deepcopy(c.outbound),'outbound_invoice_id':c.original_id,'serial_id':c.invoice_no}
    assert run(c)['status']=='waiting_stock' and c.posts==[]
    with Session(editor.ctx.engine) as db:
        row=db.get(OkkiOutboundTask,c.task_id);assert row.reason=='regenerate:'+str(latest)
        row.updated_at=beijing_now()-timedelta(minutes=16);db.commit()
    c.stock=100
    assert run(c)['status']=='done' and len(c.posts)==1
    assert c.posts[0]['serial_id']==c.invoice_no+' ['+str(c.order['order_id'])+']'


def test_worker_scheduler_shared_fence_blocks_without_business_reads(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path);before=snapshot(c)
    with editor.ctx.engine.connect() as owner:
        assert owner.scalar(text('SELECT GET_LOCK(:name,0)'),{'name':worker.LOCK_NAME})==1;owner.rollback()
        try:assert worker.run_once(lambda:Session(editor.ctx.engine))=={'status':'busy','processed':0}
        finally:owner.execute(text('SELECT RELEASE_LOCK(:name)'),{'name':worker.LOCK_NAME});owner.rollback()
    assert c.posts==[] and c.reads==[] and snapshot(c)==before


def test_worker_scheduler_disabled_worker_installs_permanent_mode(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path)
    monkeypatch.setattr(worker.get_settings(),'PORTAL_OUTBOUND_WORKER_ENABLED',False)
    assert worker.run_once(lambda:Session(editor.ctx.engine))=={'status':'disabled','processed':0}
    with Session(editor.ctx.engine) as db:assert db.get(worker.AuthorityBarrier,worker.MODE) is not None
    assert c.posts==[] and c.reads==[]


def test_worker_late_original_fact_during_second_generation_blocks_new_finish(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path);hit=[];original_commit=Session.commit
    def lose_fact(db):
        if not hit and db.in_transaction() and db.connection().scalar(select(ShippingOperationEvent.id).where(
                ShippingOperationEvent.scope==facts.FACT,ShippingOperationEvent.outbound_record_id=='create:'+str(editor.invoice_id))):
            hit.append(True);raise OperationalError('Owned original observation delayed',None,RuntimeError('ACK unavailable'))
        return original_commit(db)
    monkeypatch.setattr(Session,'commit',lose_fact)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==503 and len(c.posts)==1 and records(c,facts.FACT)==[]
    monkeypatch.setattr(Session,'commit',original_commit)
    nonce,data,_=records(c,facts.START)[0];attempt=facts.Attempt(nonce,data)
    monkeypatch.setattr(worker,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
    assert run(c)['status']=='done' and len(records(c,facts.FINISH))==1
    c.occupant=deepcopy(c.created);c.created=None
    with Session(editor.ctx.engine) as db:
        lock_authority(db,force=True);worker.edit_authority.lock_document(db,editor.invoice_id,force=True)
        db.add(ShippingOperationEvent(scope='outbound-delete',request_id=str(c.original_id),action='outbound_deleted',
            source='pc',operator_user_id=editor.ctx.admin,login_user_id=editor.ctx.admin,
            operator_name='Isolated',login_name='Isolated',outbound_record_id=str(c.original_id),
            created_at=beijing_now()+timedelta(minutes=7),payload={'outbound_invoice_id':str(c.original_id),
                'order_ids':[str(c.order['order_id'])],'tasks':[{'id':c.task_id,'status':'done','reason':None}]}))
        latest=InvoiceSyncLog(invoice_id=editor.invoice_id,action='update',success=1,operator_id=editor.ctx.admin,
            created_at=beijing_now()+timedelta(minutes=8),response_body=json.dumps({'order_id':c.order['order_id']}))
        db.add(latest);db.flush();row=db.get(OkkiOutboundTask,c.task_id)
        row.status='pending';row.reason='regenerate:'+str(latest.id);db.commit()
    def post(*args,**kwargs):
        response=c.post(*args,**kwargs)
        with Session(editor.ctx.engine) as db:
            facts.observe(db,attempt,'accepted',{'outbound_invoice_id':str(c.original_id),'serial_id':attempt.data['payload']['serial_id']});db.commit()
        return response
    monkeypatch.setattr(worker.okki_client.httpx,'post',post)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==409 and len(c.posts)==2 and len(records(c,facts.FINISH))==1
    assert len(records(c,facts.START))==len(records(c,facts.SEND))==len(records(c,facts.FACT))==2
    with Session(editor.ctx.engine) as db:
        assert {row.nonce for row in facts.unresolved(db,editor.invoice_id)}=={row[0] for row in records(c,facts.START)}
    assert worker.run_once(lambda:Session(editor.ctx.engine))['status']=='processed'
    assert len(c.posts)==2 and len(records(c,facts.FINISH))==1


@pytest.mark.parametrize('started',['2026-10-04T15:54:00+00:00','2026-10-04T08:54:00-07:00','2026-10-04T23:54:00+08:00'])
def test_worker_lease_uses_beijing_midnight_for_original_offsets(monkeypatch,started):
    from datetime import datetime
    monkeypatch.setattr(worker,'beijing_now',lambda:datetime(2026,10,5,0,0))
    assert worker.expired(facts.Attempt('owned',{'started_at':started}))
    monkeypatch.setattr(worker,'beijing_now',lambda:datetime(2026,10,4,23,58))
    assert not worker.expired(facts.Attempt('owned',{'started_at':started}))


def test_worker_supplier_unavailable_is_private_503_without_claim(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path);before=snapshot(c)
    def unavailable(*args,**kwargs):raise worker.okki_client.OkkiApiError('Owned private supplier detail')
    monkeypatch.setattr(worker.followup.legacy.remote,'read',unavailable)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==503 and error.value.headers['Cache-Control']=='private, no-store'
    assert 'Owned private' not in error.value.detail and c.posts==[] and snapshot(c)==before


def test_worker_actual_token_overflow_is_private_503_without_send(editor,monkeypatch,tmp_path):
    actual_fetch=worker.okki_client.fetch_token
    c=prepare(editor,monkeypatch,tmp_path);before=snapshot(c);calls=[]
    monkeypatch.setattr(worker.okki_client,'fetch_token',actual_fetch)
    settings=worker.get_settings()
    monkeypatch.setattr(settings,'OKKI_CLIENT_ID','owned-synthetic-client')
    monkeypatch.setattr(settings,'OKKI_CLIENT_SECRET','owned-synthetic-secret')
    def oauth(url,**kwargs):
        assert url.endswith('/v1/oauth2/access_token');calls.append(True)
        return httpx.Response(200,json={'access_token':'owned-synthetic-token','expires_in':10**100})
    monkeypatch.setattr(worker.okki_client.httpx,'post',oauth)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==503 and calls==[True]
    assert c.posts==[] and records(c,facts.START)==[] and snapshot(c)==before


def test_worker_done_only_late_fact_is_scheduled_and_get_verified(editor,monkeypatch,tmp_path):
    c=prepare(editor,monkeypatch,tmp_path);original_commit=Session.commit;hit=[]
    def lose_fact(db):
        if not hit and db.in_transaction() and db.connection().scalar(select(ShippingOperationEvent.id).where(
                ShippingOperationEvent.scope==facts.FACT,ShippingOperationEvent.outbound_record_id=='create:'+str(editor.invoice_id))):
            hit.append(True);raise OperationalError('Owned delayed original FACT',None,RuntimeError('ACK unavailable'))
        return original_commit(db)
    monkeypatch.setattr(Session,'commit',lose_fact)
    with pytest.raises(HTTPException) as error:run(c)
    assert error.value.status_code==503 and len(c.posts)==1
    monkeypatch.setattr(Session,'commit',original_commit)
    monkeypatch.setattr(worker,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
    assert run(c)['status']=='done'
    nonce,data,_=records(c,facts.START)[0];attempt=facts.Attempt(nonce,data)
    with Session(editor.ctx.engine) as db:
        assert db.get(OkkiOutboundTask,c.task_id).status=='done'
        facts.observe(db,attempt,'accepted',{'outbound_invoice_id':str(c.original_id),'serial_id':data['payload']['serial_id']});db.commit()
    before=snapshot(c);calls=[];actual_process=worker.process
    def observed(db,invoice_id):
        calls.append(invoice_id);return actual_process(db,invoice_id)
    monkeypatch.setattr(worker,'process',observed)
    assert worker.run_once(lambda:Session(editor.ctx.engine))['status']=='processed'
    assert editor.invoice_id in calls and len(c.posts)==1 and len(records(c,facts.FINISH))==2
    assert snapshot(c)[0]==before[0]
    with Session(editor.ctx.engine) as db:assert facts.unresolved(db,editor.invoice_id)==[]



def test_worker_failed_business_rollback_invalidates_session_before_fence_release(editor,monkeypatch,tmp_path):
    from sqlalchemy.engine import Connection
    c=prepare(editor,monkeypatch,tmp_path);before=snapshot(c)
    state={'armed':False,'physical':None,'invalidated':False,'release_seen':False}
    class FaultSession(Session):
        def rollback(self):
            if state['armed']:
                state['armed']=False
                raise RuntimeError('Owned business rollback failure')
            return super().rollback()
        def invalidate(self):
            state['invalidated']=True
            return super().invalidate()
    def action(db,invoice_id):
        task=db.get(OkkiOutboundTask,c.task_id)
        task.status='running';db.flush()
        state['physical']=db.connection().connection.driver_connection
        state['armed']=True
        raise RuntimeError('Owned unexpected business error')
    original=Connection.scalar
    def scalar(connection,statement,*args,**kwargs):
        if 'SELECT RELEASE_LOCK' in str(statement):
            assert state['invalidated'] and state['physical']._sock is None
            state['release_seen']=True
        return original(connection,statement,*args,**kwargs)
    monkeypatch.setattr(worker,'process',action);monkeypatch.setattr(Connection,'scalar',scalar)
    with pytest.raises(RuntimeError,match='business rollback failure'):
        worker.run_once(lambda:FaultSession(editor.ctx.engine))
    assert state['release_seen']
    assert snapshot(c)==before and c.posts==[] and c.reads==[]
    with editor.ctx.engine.connect() as observer:
        assert original(observer,text('SELECT IS_USED_LOCK(:name)'),{'name':worker.LOCK_NAME}) is None
