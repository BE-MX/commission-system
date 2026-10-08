"""Actual JWT/MySQL authorization and independent phase gates for local recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, select, text, event, update
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.invoice import edit_authority, linked_sync_service as linked, linked_outbound_service as outbounds
from app.invoice import okki_client, outbound_recovery
from app.invoice.models import Invoice, InvoiceLinkedSync, OkkiOutboundTask, XiaomanSettings, CustomProduct
from app.portal.authority import get_settings, lock_authority
from app.receipt import remote
from test_mysql_invoice_cancellation_refresh import demote_admin


def setup_outbound(e, monkeypatch, action):
    metadata=MetaData()
    for model in (XiaomanSettings,CustomProduct):
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(e.ctx.engine)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.xiaoman_order_id='401';invoice.sync_status='synced';invoice.linked_sync_id=None
        for index,item in enumerate(invoice.items):item.xiaoman_unique_id=str(501+index)
        db.flush()
        version=linked.edit_version(invoice)
        expected={'order_id':'401','company_id':str(invoice.customer_id),'currency':invoice.currency,
            'amount':str(invoice.total_amount-(invoice.surcharge_amount or 0)),'create_time':'2026-09-30 00:00:00'}
        if action=='ack_outbound':
            db.add(InvoiceLinkedSync(id=uuid4().hex,invoice_id=invoice.id,request_key=uuid4().hex,
                request_hash='a'*64,status='manual',before=linked.snapshot(invoice),after=linked.snapshot(invoice),
                steps={'order':{'status':'done'},'receipt':{'status':'done'},'outbound':{'status':'manual'}},created_by=e.ctx.admin))
        else:
            db.add(OkkiOutboundTask(invoice_id=invoice.id,order_id='401',status='failed',attempts=4,reason='Unsent test failure'))
        records=[{'order_id':'401','order_record_id':str(i.xiaoman_unique_id),'product_id':str(i.product_id),
            'sku_id':str(i.sku_id),'outbound_count':i.quantity} for i in invoice.items]
        db.commit()
    calls=[]
    def read(db,path,params=None):
        calls.append(('order',path));return deepcopy(expected)
    def receipts(*args):calls.append(('receipts',));return []
    def related(*args):
        calls.append(('outbounds',));return [] if action=='outbound_retry' else [{'outbound_invoice_id':'701','serial_id':'OUT-701','status':2,'record_list':deepcopy(records)}]
    monkeypatch.setattr(remote,'read',read);monkeypatch.setattr(remote,'order_receipts',receipts)
    monkeypatch.setattr(outbounds,'find_related',related)
    monkeypatch.setattr(okki_client,'ensure_access_token',lambda *a,**kw:pytest.fail('Unexpected actual client path'))
    return f'/api/invoice/invoices/{e.invoice_id}/lifecycle',{'action':action,'reason':'Reviewed original task and related outbound details','confirmed':True,'expected_version':version},calls


def snapshot(e):
    with Session(e.ctx.engine) as db:
        return e.snapshot(),tuple(db.execute(select(*OkkiOutboundTask.__table__.columns).order_by(OkkiOutboundTask.id)).all())


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
@pytest.mark.parametrize('revocation',['inactive','role','scope'])
def test_old_jwt_cannot_recover_after_current_authority_changes(editor,monkeypatch,action,revocation):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,action)
    if revocation=='inactive':
        with Session(e.ctx.engine) as db:lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    else:demote_admin(e,[] if revocation=='role' else ['invoice:admin'])
    before=snapshot(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==(404 if revocation=='scope' else 403),response.text
    assert calls==[] and snapshot(e)==before
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
@pytest.mark.parametrize('phase',['order','outbounds'])
@pytest.mark.parametrize('change',['inactive','document','binding','task','cancelled'])
def test_unlocked_evidence_rechecks_current_authority_and_full_state(editor,monkeypatch,action,phase,change):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,action);ready=Event();release=Event()
    module,name=(remote,'read') if phase=='order' else (outbounds,'find_related')
    original=getattr(module,name)
    def gate(*args,**kwargs):ready.set();assert release.wait(8);return original(*args,**kwargs)
    monkeypatch.setattr(module,name,gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='document':invoice.remark='Changed during actual independent SQL transaction'
                elif change=='binding':invoice.xiaoman_order_id='402'
                elif change=='cancelled':invoice.status='cancelled'
                elif action=='outbound_retry':db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==invoice.id)).attempts+=1
                else:
                    row=db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.invoice_id==invoice.id));row.steps={**row.steps,'receipt':{'status':'manual'}}
                db.commit()
            before=snapshot(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 409),response.text
    assert snapshot(e)==before


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
def test_success_and_repeated_command_never_replays_local_transition(editor,monkeypatch,action):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,action)
    response=asyncio.run(e.write(route,body,'POST',e.admin_token));assert response.status_code==200,response.text
    assert response.json()['data']['status']==('pending' if action=='outbound_retry' else 'done')
    before=snapshot(e);call_count=len(calls)
    repeat=asyncio.run(e.write(route,body,'POST',e.admin_token));assert repeat.status_code==409,repeat.text
    assert snapshot(e)==before and len(calls)==call_count
    with Session(e.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==e.invoice_id))
        operation=db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.invoice_id==e.invoice_id))
        if action=='outbound_retry':assert task.status=='pending' and task.attempts==0 and task.order_id=='401'
        else:assert operation.steps['outbound']['operator_id']==e.ctx.admin and operation.steps['outbound']['documents'][0]['id']=='701'


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
@pytest.mark.parametrize('fault',['api','binding','invalid'])
def test_untrusted_external_evidence_returns_safe_503_without_writes(editor,monkeypatch,action,fault):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,action)
    def fail(*a,**kw):
        if fault=='api':raise okki_client.OkkiApiError('PRIVATE_PROVIDER_BODY')
        return {} if fault=='binding' else None
    monkeypatch.setattr(remote,'read',fail);before=snapshot(e)
    response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==503,response.text
    assert 'PRIVATE_PROVIDER_BODY' not in response.text and snapshot(e)==before


@pytest.mark.parametrize('status',['running','uncertain','done','pending','deleted'])
def test_retry_refuses_created_or_unresolved_task_before_remote_reads(editor,monkeypatch,status):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,'outbound_retry')
    with Session(e.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==e.invoice_id));task.status=status;db.commit()
    before=snapshot(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409 and snapshot(e)==before and calls==[]


@pytest.mark.parametrize('reason',['delete_pending:old','regenerate:123','regenerate:invalid'])
def test_retry_preserves_original_deletion_or_regeneration_fence(editor,monkeypatch,reason):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,'outbound_retry')
    with Session(e.ctx.engine) as db:
        task=db.scalar(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==e.invoice_id));task.reason=reason;db.commit()
    before=snapshot(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409 and snapshot(e)==before and calls==[]


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
@pytest.mark.parametrize('stop',[False,True])
def test_inflight_off_still_uses_forced_current_authorization(editor,monkeypatch,action,stop):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,action);ready=Event();release=Event()
    original=outbounds.find_related;sql_locks=[]
    def observe(conn,cursor,statement,params,context,many):
        if not get_settings().PORTAL_ENABLED and 'FOR UPDATE' in statement.upper():sql_locks.append(statement)
    event.listen(e.ctx.engine,'before_cursor_execute',observe)
    def gate(*args):ready.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(outbounds,'find_related',gate);settings=get_settings()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            if stop:
                with Session(e.ctx.engine) as db:lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
            monkeypatch.setattr(settings,'PORTAL_ENABLED',False)
            release.set();response=pending.result(timeout=8)
        finally:
            release.set();monkeypatch.setattr(settings,'PORTAL_ENABLED',True)
            event.remove(e.ctx.engine,'before_cursor_execute',observe)
    assert response.status_code==(403 if stop else 200),response.text
    # Disabled employees stop after the barrier/current principal, before invoice locks.
    tables=('ark_order_portal_auth_barriers',) if stop else ('ark_order_portal_auth_barriers','ark_order_portal_requests','ark_order_portal_conversions','ark_invoices')
    indices=[next(i for i,sql in enumerate(sql_locks) if 'FROM '+table in sql) for table in tables]
    assert indices==sorted(indices) and len(set(indices))==len(tables),sql_locks


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
def test_two_overlapping_recoveries_apply_only_one_local_transition(editor,monkeypatch,action):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,action);first=Event();both=Event();release=Event()
    original=outbounds.find_related
    def gate(*args):
        if first.is_set():both.set()
        first.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(outbounds,'find_related',gate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert first.wait(6)
            two=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
            assert both.wait(6);release.set()
            responses=[one.result(timeout=8),two.result(timeout=8)]
        finally:release.set()
    assert sorted(r.status_code for r in responses)==[200,409],[r.text for r in responses]
    with Session(e.ctx.engine) as db:
        if action=='outbound_retry':
            rows=db.scalars(select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==e.invoice_id)).all()
            assert len(rows)==1 and rows[0].status=='pending' and rows[0].attempts==0
        else:
            rows=db.scalars(select(InvoiceLinkedSync).where(InvoiceLinkedSync.invoice_id==e.invoice_id)).all()
            assert len(rows)==1 and rows[0].status=='done' and rows[0].steps['outbound']['operator_id']==e.ctx.admin


@pytest.mark.parametrize('kind',['missing','difference','status','wrong_line'])
def test_ack_does_not_mark_unverified_outbound_done(editor,monkeypatch,kind):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,'ack_outbound');original=outbounds.find_related
    def changed(*args):
        documents=original(*args)
        if kind=='missing':return []
        if kind=='status':documents[0]['status']=7
        elif kind=='difference':documents[0]['record_list'][0]['outbound_count']+=1
        else:documents[0]['record_list'][0]['order_record_id']='unrelated-line'
        return documents
    monkeypatch.setattr(outbounds,'find_related',changed);before=snapshot(e)
    response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409,response.text
    assert snapshot(e)==before


def test_retry_receipt_reader_is_unlocked_and_rechecks_stop(editor,monkeypatch):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,'outbound_retry');ready=Event();release=Event()
    def gate(*args):ready.set();assert release.wait(8);return []
    monkeypatch.setattr(remote,'order_receipts',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);edit_authority.lock_document(db,e.invoice_id)
                db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
            before=snapshot(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==403 and snapshot(e)==before


@pytest.mark.parametrize('field',['currency','total_amount','xiaoman_unique_id'])
def test_retry_rejects_changed_remote_binding_even_when_legacy_version_unchanged(editor,monkeypatch,field):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,'outbound_retry');ready=Event();release=Event()
    original=outbounds.find_related
    def gate(*args):ready.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(outbounds,'find_related',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                original_version=invoice.portal_document_version
                if field=='xiaoman_unique_id':
                    from app.invoice.models import InvoiceItem
                    db.execute(update(InvoiceItem).where(InvoiceItem.id==invoice.items[0].id).values(xiaoman_unique_id='9001'))
                else:
                    value='EUR' if field=='currency' else invoice.total_amount+1
                    db.execute(update(Invoice).where(Invoice.id==invoice.id).values({field:value}))
                db.commit();db.expire_all();invoice=edit_authority.lock_document(db,e.invoice_id)
                assert linked.edit_version(invoice)==body['expected_version']
                assert invoice.portal_document_version==original_version
            before=snapshot(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==409,response.text
    assert snapshot(e)==before


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
def test_actual_token_helper_releases_business_locks_and_rechecks_current_employee(editor,monkeypatch,action):
    from datetime import timedelta
    from app.core.time import utc_now_naive
    e=editor;token_helper=okki_client.ensure_access_token;read_helper=remote.read
    route,body,calls=setup_outbound(e,monkeypatch,action);ready=Event();release=Event()
    with Session(e.ctx.engine) as db:
        settings=db.get(XiaomanSettings,1)
        if settings is None:
            settings=XiaomanSettings(id=1,default_currency='USD');db.add(settings)
        settings.access_token=None;settings.token_expires_at=None;db.commit()
    order_read=remote.read
    monkeypatch.setattr(okki_client,'ensure_access_token',token_helper)
    monkeypatch.setattr(remote,'read',read_helper)
    def fetch():ready.set();assert release.wait(8);return 'synthetic-owned-token',utc_now_naive()+timedelta(hours=8)
    monkeypatch.setattr(okki_client,'fetch_token',fetch)
    monkeypatch.setattr(okki_client,'_get_json',lambda path,token,**kwargs:order_read(None,path,kwargs.get('params')))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);edit_authority.lock_document(db,e.invoice_id)
                db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
            before=snapshot(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==403,response.text
    assert snapshot(e)==before
    with Session(e.ctx.engine) as db:assert db.get(XiaomanSettings,1).access_token is None


@pytest.mark.parametrize('action',['outbound_retry','ack_outbound'])
@pytest.mark.parametrize('shape',['list_body','list_row','detail_body','record','missing_order_id','null_order_id'])
def test_real_outbound_scan_rejects_malformed_provider_shape_as_safe_503(editor,monkeypatch,action,shape):
    scanner=outbounds.find_related;e=editor;route,body,calls=setup_outbound(e,monkeypatch,action)
    monkeypatch.setattr(outbounds,'find_related',scanner);order_reader=remote.read
    def read(db,path,params=None):
        if path=='/v1/invoices/order/info':return order_reader(db,path,params)
        assert path=='/v1/invoices/outbound/list'
        if shape=='list_body':return None
        return {'count':1,'list':[7] if shape=='list_row' else [{'outbound_invoice_id':'701'}]}
    monkeypatch.setattr(remote,'read',read)
    monkeypatch.setattr(outbounds,'_read_details',lambda *a:[None] if shape=='detail_body' else [{'outbound_invoice_id':'701','record_list':[{}] if shape=='missing_order_id' else [{'order_id':None}] if shape=='null_order_id' else [7]}])
    before=snapshot(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==503,response.text
    assert snapshot(e)==before and 'no-store' in response.headers['cache-control']



def test_partial_ack_completion_preserves_original_confirmation_on_repeat(editor,monkeypatch):
    e=editor;route,body,calls=setup_outbound(e,monkeypatch,'ack_outbound')
    with Session(e.ctx.engine) as db:
        operation=db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.invoice_id==e.invoice_id))
        operation.steps={**operation.steps,'receipt':{'status':'manual'}};db.commit()
    response=asyncio.run(e.write(route,body,'POST',e.admin_token));assert response.status_code==200,response.text
    assert response.json()['data']['status']=='manual' and response.json()['data']['outbound']['status']=='done'
    before=snapshot(e);call_count=len(calls)
    repeat=asyncio.run(e.write(route,{**body,'reason':'A different reason must not overwrite original confirmation'},'POST',e.admin_token))
    assert repeat.status_code==409 and snapshot(e)==before and len(calls)==call_count
