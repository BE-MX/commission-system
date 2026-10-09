"""Actual push/followup local queue phases; supplier reads only are synthetic."""
from copy import deepcopy
import pytest
from sqlalchemy import update, select, text
from sqlalchemy.orm import Session
from app.auth.models import ArkUser
from app.invoice import edit_authority, outbound_followup_service as followup
from app.invoice.models import OkkiOutboundTask, Invoice, InvoiceItem, InvoiceSyncLog
from app.portal.authority import lock_authority
from test_mysql_order_push_execution import setup_push, execute, business
from test_mysql_invoice_cancellation_refresh import demote_admin


def setup_followup(e,monkeypatch,tmp_path):
    actual_read=followup.remote.read
    original=followup.safely_run
    c=setup_push(e,monkeypatch,tmp_path)
    monkeypatch.setattr(followup,'safely_run',original)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        db.add(OkkiOutboundTask(invoice_id=invoice.id,order_id=c.target,status='waiting_stock'))
        db.commit()
    c.reads=[];c.gate=None;c.before=None;c.order=None;c.available=100;c.mutate_order=None
    def read(db,path,params):
        c.reads.append(path)
        if c.gate:c.gate(path)
        if path.endswith('/order/info'):
            if c.order is None:
                with Session(e.ctx.engine) as observed:
                    invoice=observed.get(Invoice,e.invoice_id)
                    c.order={**c.accepted(c.posts[0]),'company_id':str(invoice.customer_id),'currency':invoice.currency,
                        'amount':str(invoice.total_amount-(invoice.surcharge_amount or 0)), 'create_time':'2026-10-05 09:00:00'}
            data=deepcopy(c.order)
            if c.mutate_order:c.mutate_order(data)
            return data
        if path.endswith('/outbound/list'):return {'count':0,'list':[]}
        if path.endswith('/inventory-list'):
            return {'count':1,'list':[{'sku_id':params['sku_id'],'warehouse_id':followup.DESTINATION_WAREHOUSE_ID,
                'enable_count':c.available,'disable_flag':0}]}
        raise AssertionError('Unexpected isolated supplier endpoint')
    c.supplier_read=read;c.actual_read=actual_read
    monkeypatch.setattr(followup.remote,'read',read)
    return c


@pytest.mark.parametrize("path", ["/order/info", "/outbound/list", "/inventory-list"])
@pytest.mark.parametrize("change", ["inactive", "permission", "scope"])
def test_actual_followup_cannot_requeue_after_employee_revocation(editor,monkeypatch,tmp_path,path,change):
    c=setup_followup(editor,monkeypatch,tmp_path)
    def gate(endpoint):
        if not endpoint.endswith(path):return
        c.gate=None
        if change == 'inactive':
            with Session(editor.ctx.engine) as db:
                lock_authority(db);db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
        else:
            demote_admin(editor, ['invoice:read'] if change == 'permission' else ['invoice:sync'])
        c.before=business(editor)
    c.gate=gate
    response=execute(c)
    assert response.status_code==(404 if change=="scope" else 403),response.text
    assert c.before is not None and len(c.posts)==1
    assert business(editor)==c.before


@pytest.mark.parametrize('available,expected', [(100,'pending'),(0,'waiting_stock')])
def test_actual_followup_ready_and_shortage_success_controls(editor,monkeypatch,tmp_path,available,expected):
    c=setup_followup(editor,monkeypatch,tmp_path);c.available=available
    response=execute(c)
    assert response.status_code==200,response.text
    assert response.json()['data']['ok'] is True
    assert response.json()['data']['outbound_sync']['status']==expected
    assert len(c.posts)==1
    with Session(editor.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        assert task.status==expected
        assert bool(task.last_error)==(available==0)
        assert len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==editor.invoice_id,
            InvoiceSyncLog.action=='outbound_queue')).all())==1


@pytest.mark.parametrize('mutation', ['currency','amount','uid','task','intent'])
def test_followup_rejects_full_binding_change_after_inventory_read(editor,monkeypatch,tmp_path,mutation):
    c=setup_followup(editor,monkeypatch,tmp_path)
    def gate(path):
        if not path.endswith('/inventory-list'):return
        c.gate=None
        with Session(editor.ctx.engine) as db:
            lock_authority(db);invoice=edit_authority.lock_document(db,editor.invoice_id)
            if mutation=='currency':invoice.currency='EUR'
            if mutation=='amount':invoice.total_amount+=1
            if mutation=='uid':invoice.items[0].xiaoman_unique_id='7001'
            if mutation=='task':
                task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==invoice.id))
                task.reason='A new authoritative queue reason'
            if mutation=='intent':
                from app.receipt.models import ReceiptIntent
                intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id));intent.amount+=1
            db.commit()
        c.before=business(editor)
    c.gate=gate
    response=execute(c)
    assert response.status_code==409,response.text
    assert c.before is not None and business(editor)==c.before and len(c.posts)==1


@pytest.mark.parametrize('mutation,code', [('identity',503),('company',409),('amount',409),('uid',503)])
def test_followup_bad_supplier_evidence_never_requeues(editor,monkeypatch,tmp_path,mutation,code):
    c=setup_followup(editor,monkeypatch,tmp_path)
    def alter(data):
        if mutation=='identity':data['order_id']='999'
        if mutation=='company':data['company_id']='unrelated-company'
        if mutation=='amount':data['amount']='1'
        if mutation=='uid':data['product_list'][0]['unique_id']='0501'
    c.mutate_order=alter
    def gate(path):
        if path.endswith('/order/info') and c.before is None:c.before=business(editor)
    c.gate=gate
    response=execute(c)
    assert response.status_code==code,response.text
    assert business(editor)==c.before and len(c.posts)==1
    assert 'private-provider-body' not in response.text


def test_followup_supplier_wait_has_no_authority_invoice_task_locks(editor,monkeypatch,tmp_path):
    c=setup_followup(editor,monkeypatch,tmp_path);checked=[]
    def gate(path):
        with Session(editor.ctx.engine) as db:
            db.execute(text('SET SESSION innodb_lock_wait_timeout=1'));db.commit()
            lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
            db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id).with_for_update())
            db.rollback()
        checked.append(path)
    c.gate=gate
    response=execute(c)
    assert response.status_code==200,response.text
    assert any(path.endswith('/inventory-list') for path in checked) and len(c.posts)==1


@pytest.mark.parametrize('status,reason,expected', [('pending','regenerate:1','pending'),
    ('waiting_stock','regenerate:1 Insufficient warehouse stock','pending'),('skipped','deleted:701','pending')])
def test_followup_actual_regeneration_and_verified_deletion(editor,monkeypatch,tmp_path,status,reason,expected):
    from app.shipping_inspection.models import ShippingOperationEvent
    from app.core.time import beijing_now
    from datetime import timedelta
    c=setup_followup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        task.status,task.reason=status,reason
        if reason.startswith('regenerate:'):
            original=InvoiceSyncLog(invoice_id=editor.invoice_id,action='update',success=1,operator_id=editor.ctx.admin,
                response_body='{"order_id":"'+c.target+'"}',created_at=beijing_now()-timedelta(minutes=20))
            db.add(original);db.flush();task.reason=f'regenerate:{original.id}'+(' Insufficient warehouse stock' if status=='waiting_stock' else '')
        if status=='skipped':
            db.add(ShippingOperationEvent(scope='outbound-delete',request_id='701',action='outbound_deleted',
                source='pc',login_user_id=editor.ctx.admin,operator_user_id=editor.ctx.admin,
                operator_name='Isolated',login_name='Isolated',outbound_record_id='701',
                created_at=beijing_now()-timedelta(minutes=10),
                payload={'outbound_invoice_id':'701','order_ids':[c.target],'tasks':[{'id':task.id,'status':'done','reason':None}]}))
        db.commit()
    response=execute(c)
    assert response.status_code==200,response.text
    with Session(editor.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        latest=db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==editor.invoice_id,
            InvoiceSyncLog.action.in_(['create','update']),InvoiceSyncLog.success==1).order_by(InvoiceSyncLog.id.desc()))
        assert task.status==expected and task.reason==f'regenerate:{latest.id}'
    assert len(c.posts)==1


@pytest.mark.parametrize('status', ['running','uncertain'])
def test_followup_cannot_overwrite_worker_takeover(editor,monkeypatch,tmp_path,status):
    c=setup_followup(editor,monkeypatch,tmp_path)
    def gate(path):
        if not path.endswith('/inventory-list'):return
        c.gate=None
        with Session(editor.ctx.engine) as db:
            lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
            task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
            task.status=status;task.attempts+=1;task.last_error='Original worker fencing evidence';db.commit()
        c.before=business(editor)
    c.gate=gate
    response=execute(c)
    assert response.status_code==409,response.text
    assert business(editor)==c.before and len(c.posts)==1


def test_followup_inflight_off_does_not_return_to_legacy(editor,monkeypatch,tmp_path):
    from app.portal.authority import get_settings
    c=setup_followup(editor,monkeypatch,tmp_path)
    def gate(path):
        if not path.endswith('/inventory-list'):return
        c.gate=None;monkeypatch.setattr(get_settings(),'PORTAL_ENABLED',False)
        with Session(editor.ctx.engine) as db:
            lock_authority(db,force=True);db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
        c.before=business(editor)
    c.gate=gate
    response=execute(c)
    assert response.status_code==403,response.text
    assert business(editor)==c.before and len(c.posts)==1


@pytest.mark.parametrize('bad', ['order','task','outbound','missing'])
def test_followup_cannot_borrow_other_order_deletion(editor,monkeypatch,tmp_path,bad):
    from app.shipping_inspection.models import ShippingOperationEvent
    from app.core.time import beijing_now
    from datetime import timedelta
    c=setup_followup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        task.status,task.reason='skipped','deleted:801'
        payload={'outbound_invoice_id':'801','order_ids':[c.target],'tasks':[{'id':task.id}]}
        if bad=='order':payload['order_ids']=['999999']
        if bad=='task':payload['tasks']=[{'id':999999}]
        if bad=='outbound':payload['outbound_invoice_id']='802'
        if bad=='missing':payload={}
        db.add(ShippingOperationEvent(scope='outbound-delete',request_id='801',action='outbound_deleted',
            source='pc',login_user_id=editor.ctx.admin,operator_user_id=editor.ctx.admin,
            operator_name='Isolated',login_name='Isolated',outbound_record_id='801',payload=payload,
            created_at=beijing_now()-timedelta(minutes=10)))
        db.commit()
    def gate(*args):
        raise AssertionError('Untrusted deletion evidence must be rejected before supplier I/O')
    c.gate=gate
    response=execute(c)
    assert response.status_code==409,response.text
    with Session(editor.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        assert task.status=='skipped' and task.reason=='deleted:801'
    assert len(c.posts)==1 and c.reads==[]


@pytest.mark.parametrize('field', ['count','unit_price','cost_amount','amount'])
def test_followup_incomplete_commercial_shape_is_503(editor,monkeypatch,tmp_path,field):
    c=setup_followup(editor,monkeypatch,tmp_path)
    def alter(data):
        (data if field=='amount' else data['product_list'][0]).pop(field)
    c.mutate_order=alter
    def gate(path):
        if c.before is None:c.before=business(editor)
    c.gate=gate
    response=execute(c)
    assert response.status_code==503,response.text
    assert business(editor)==c.before and len(c.posts)==1


@pytest.mark.parametrize('reason', ['regenerate:garbage','regenerate:0501','regenerate:999999'])
def test_followup_untrusted_generation_cannot_be_rewritten(editor,monkeypatch,tmp_path,reason):
    c=setup_followup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        task.status,task.reason='pending',reason;db.commit()
    response=execute(c)
    assert response.status_code==409,response.text
    with Session(editor.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        assert task.status=='pending' and task.reason==reason
    assert len(c.posts)==1 and c.reads==[]



def test_followup_cannot_borrow_same_pi_other_target_generation(editor,monkeypatch,tmp_path):
    c=setup_followup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
        old=InvoiceSyncLog(invoice_id=editor.invoice_id,action='update',success=1,
            operator_id=editor.ctx.admin,response_body='{"order_id":"777777"}')
        db.add(old);db.flush()
        reason=f'regenerate:{old.id}'
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        task.status,task.reason='pending',reason;db.commit()
    response=execute(c)
    assert response.status_code==409,response.text
    with Session(editor.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
        assert task.status=='pending' and task.reason==reason
    assert len(c.posts)==1 and c.reads==[]


@pytest.mark.parametrize('phase', ['get','refresh'])
def test_actual_get_token_helper_revocation_window(editor,monkeypatch,tmp_path,phase):
    import httpx
    from urllib.parse import urlsplit
    from app.invoice import okki_client
    c=setup_followup(editor,monkeypatch,tmp_path)
    monkeypatch.setattr(followup.remote,'read',c.actual_read)
    fetch_original=okki_client.fetch_token;hit=[]
    def revoke():
        if hit:return
        hit.append(phase)
        with Session(editor.ctx.engine) as db:
            db.execute(text('SET SESSION innodb_lock_wait_timeout=1'));db.commit()
            lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
            db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id).with_for_update())
            db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
        c.before=business(editor)
    def fetch():
        if c.tokens and phase=='refresh':revoke()
        return fetch_original()
    def get(url,*,headers,timeout,params):
        path=urlsplit(url).path
        if phase=='refresh' and len(c.tokens)==1:return httpx.Response(401)
        if phase=='get' and path.endswith('/inventory-list'):revoke()
        return httpx.Response(200,json={'code':200,'data':c.supplier_read(None,path,params)})
    monkeypatch.setattr(okki_client,'fetch_token',fetch)
    monkeypatch.setattr(okki_client.httpx,'get',get)
    response=execute(c)
    assert hit==[phase] and response.status_code==403,response.text
    assert c.before is not None and business(editor)==c.before and len(c.posts)==1
    assert len(c.tokens)==(2 if phase=='refresh' else 1)


@pytest.mark.parametrize('failure', ['before_commit','lost_ack'])
def test_queue_audit_atomic_and_commit_ack_preserves_original(editor,monkeypatch,tmp_path,failure):
    from sqlalchemy.exc import OperationalError
    from app.invoice import outbound_followup_execution
    c=setup_followup(editor,monkeypatch,tmp_path);commit_original=Session.commit;hit=[]
    def commit(db):
        if not hit and any(isinstance(row,InvoiceSyncLog) and row.action=='outbound_queue' for row in db.new):
            hit.append(failure)
            if failure=='lost_ack':commit_original(db)
            raise OperationalError('owned queue transaction fault',{},RuntimeError('synthetic boundary'))
        return commit_original(db)
    monkeypatch.setattr(Session,'commit',commit)
    response=execute(c)
    assert response.status_code==503 and hit==[failure],response.text
    with Session(editor.ctx.engine) as db:
        invoice=db.get(Invoice,editor.invoice_id)
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==invoice.id))
        count=len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==invoice.id,
            InvoiceSyncLog.action=='outbound_queue')).all())
        assert invoice.sync_status=='synced' and invoice.xiaoman_order_id==c.target
        assert task.status==('pending' if failure=='lost_ack' else 'waiting_stock')
        assert count==(1 if failure=='lost_ack' else 0)
    with Session(editor.ctx.engine) as db:
        result=outbound_followup_execution.run(db,editor.invoice_id,{'id':editor.ctx.admin})
        assert result['status']=='pending'
    with Session(editor.ctx.engine) as db:
        assert len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==editor.invoice_id,
            InvoiceSyncLog.action=='outbound_queue')).all())==1
    assert len(c.posts)==1


@pytest.mark.parametrize('commit_first', [True,False])
def test_final_queue_authority_serializes_revocation_commit_and_rollback(editor,monkeypatch,tmp_path,commit_first):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from queue import Queue
    from sqlalchemy.exc import OperationalError
    from test_mysql_concurrency import wait_for_lock
    c=setup_followup(editor,monkeypatch,tmp_path)
    ready,release,revoked=Event(),Event(),Event();connections=Queue();original=Session.commit;hit=[]
    def commit(db):
        queue_write=any(isinstance(row,InvoiceSyncLog) and row.action=='outbound_queue' for row in db.new)
        if queue_write and not hit:
            hit.append(True);db.flush();ready.set();assert release.wait(8)
            if commit_first:original(db)
            else:db.rollback()
            assert revoked.wait(8)
            if not commit_first:raise OperationalError('owned queue rollback',{},RuntimeError('synthetic boundary'))
            return
        return original(db)
    monkeypatch.setattr(Session,'commit',commit)
    def revoke():
        with Session(editor.ctx.engine) as db:
            connections.put(db.scalar(text('SELECT CONNECTION_ID()')))
            lock_authority(db);db.get(ArkUser,editor.ctx.admin).is_active=False;db.commit()
        revoked.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=pool.submit(execute,c)
        try:
            assert ready.wait(6)
            before=business(editor)
            revocation=pool.submit(revoke)
            wait_for_lock(editor.ctx.engine,connections.get(timeout=3))
            assert not revocation.done()
            release.set();revocation.result(timeout=8);response=result.result(timeout=8)
        finally:release.set();revoked.set()
    assert response.status_code==(403 if commit_first else 503),response.text
    assert len(c.posts)==1 and hit==[True]
    after=business(editor)
    if not commit_first:assert after==before
    else:
        core=list(after[0]);extra=list(after[1]);logs=core[2]
        assert len(logs)==len(before[0][2])+1 and tuple(logs[:-1])==before[0][2]
        log_fields=[column.name for column in InvoiceSyncLog.__table__.columns]
        entry=dict(zip(log_fields,logs[-1]))
        assert entry['action']=='outbound_queue' and entry['invoice_id']==editor.invoice_id
        assert entry['operator_id']==editor.ctx.admin and entry['success']==1
        core[2]=before[0][2]
        fields=[column.name for column in OkkiOutboundTask.__table__.columns]
        allowed={'status','reason','last_error','updated_at'}
        assert len(extra[2])==len(before[1][2])
        normalized=[]
        for old,new in zip(before[1][2],extra[2]):
            previous,current=dict(zip(fields,old)),dict(zip(fields,new))
            if current['invoice_id']==editor.invoice_id:
                assert current['status']=='pending' and current['reason'] is None and current['last_error'] is None
                for field in allowed:current[field]=previous[field]
            normalized.append(tuple(current[field] for field in fields))
        extra[2]=tuple(normalized)
        assert (tuple(core),tuple(extra))==before
    with Session(editor.ctx.engine) as db:
        invoice=db.get(Invoice,editor.invoice_id)
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==invoice.id))
        audit_count=len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==invoice.id,
            InvoiceSyncLog.action=='outbound_queue')).all())
        assert invoice.sync_status=='synced' and invoice.xiaoman_order_id==c.target
        assert task.status==('pending' if commit_first else 'waiting_stock') and audit_count==int(commit_first)
        assert db.get(ArkUser,editor.ctx.admin).is_active is False
    before=business(editor)
    assert execute(c).status_code==403 and business(editor)==before and len(c.posts)==1


@pytest.mark.parametrize('mutation', ['attachment','latest_log','generation','deletion'])
def test_followup_final_binding_covers_proof_and_source_records(editor,monkeypatch,tmp_path,mutation):
    from app.receipt.models import ReceiptAttachment
    from app.shipping_inspection.models import ShippingOperationEvent
    from app.core.time import beijing_now
    from datetime import timedelta
    c=setup_followup(editor,monkeypatch,tmp_path);source_id=None
    if mutation in {'generation','deletion'}:
        with Session(editor.ctx.engine) as db:
            lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
            task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==editor.invoice_id))
            if mutation=='generation':
                row=InvoiceSyncLog(invoice_id=editor.invoice_id,action='update',success=1,
                    response_body='{"order_id":"'+c.target+'"}',operator_id=editor.ctx.admin)
                db.add(row);db.flush();source_id=row.id;task.status='pending';task.reason=f'regenerate:{source_id}'
            else:
                task.status='skipped';task.reason='deleted:901'
                row=ShippingOperationEvent(scope='outbound-delete',request_id='901',action='outbound_deleted',
                    source='pc',login_user_id=editor.ctx.admin,operator_user_id=editor.ctx.admin,
                    operator_name='Isolated',login_name='Isolated',outbound_record_id='901',
                    created_at=beijing_now()-timedelta(minutes=10),
                    payload={'outbound_invoice_id':'901','order_ids':[c.target],'tasks':[{'id':task.id}]})
                db.add(row);db.flush();source_id=row.id
            db.commit()
    def gate(path):
        if not path.endswith('/outbound/list'):return
        c.gate=None
        with Session(editor.ctx.engine) as db:
            lock_authority(db);edit_authority.lock_document(db,editor.invoice_id)
            if mutation=='attachment':
                proof=db.scalar(select(ReceiptAttachment).where(ReceiptAttachment.invoice_id==editor.invoice_id))
                proof.sha256='b'*64
            elif mutation=='latest_log':
                row=db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==editor.invoice_id,
                    InvoiceSyncLog.action.in_(['create','update'])).order_by(InvoiceSyncLog.id.desc()))
                row.request_digest='Concurrent change to original generation evidence'
            elif mutation=='generation':db.get(InvoiceSyncLog,source_id).request_digest='Concurrent original generation change'
            else:
                row=db.get(ShippingOperationEvent,source_id);row.payload={**row.payload,'concurrent_evidence':'new'}
            db.commit()
        c.before=business(editor)
        with Session(editor.ctx.engine) as db:
            c.source_before=tuple(db.execute(select(*ShippingOperationEvent.__table__.columns)
                .order_by(ShippingOperationEvent.id)).all())
    c.gate=gate
    response=execute(c)
    assert response.status_code==409,response.text
    assert business(editor)==c.before and len(c.posts)==1
    with Session(editor.ctx.engine) as db:
        assert tuple(db.execute(select(*ShippingOperationEvent.__table__.columns)
            .order_by(ShippingOperationEvent.id)).all())==c.source_before


@pytest.mark.parametrize('fault', ['incomplete_scan','order_readback_changed'])
def test_followup_scanning_and_readback_are_evidence_not_absence(editor,monkeypatch,tmp_path,fault):
    c=setup_followup(editor,monkeypatch,tmp_path);supplier=c.supplier_read;info_calls=[]
    def read(db,path,params):
        if c.before is None:c.before=business(editor)
        if fault=='incomplete_scan' and path.endswith('/outbound/list'):
            return {'count':2,'list':[]}
        result=supplier(db,path,params)
        if path.endswith('/order/info'):
            info_calls.append(True)
            if fault=='order_readback_changed' and len(info_calls)>1:result['remark']='Changed supplier observation'
        return result
    monkeypatch.setattr(followup.remote,'read',read)
    response=execute(c)
    assert response.status_code==(503 if fault=='incomplete_scan' else 409),response.text
    assert c.before is not None and business(editor)==c.before and len(c.posts)==1
