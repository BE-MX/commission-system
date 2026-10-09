"""Actual JWT/HTTP and independent MySQL phase gates for cancellation effects."""
import asyncio
from sqlalchemy.orm import Session
from app.auth.models import ArkUser
from app.invoice import lifecycle_remote, okki_client
from app.portal.authority import lock_authority
from test_mysql_invoice_cancellation_refresh import setup_refresh


def setup_remove(e, monkeypatch):
    route, body, method = setup_refresh(e, monkeypatch)
    monkeypatch.setattr(okki_client,'ensure_access_token',lambda *a:'synthetic-private-token')
    calls=[]
    def request(token,kind,identity,*,remove=False):
        calls.append((kind,str(identity),remove))
        return True if remove else None
    monkeypatch.setattr(lifecycle_remote,'request',request)
    return route,{**body,'action':'remove'},method,calls


def test_stopped_admin_real_jwt_cannot_send_delete(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    with Session(e.ctx.engine) as db:
        lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    before=e.snapshot();response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==403,response.text
    assert calls==[] and e.snapshot()==before


from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from sqlalchemy import select, text, event
import pytest
from app.core.time import beijing_now
from app.invoice import cancellation_facts as facts, cancellation_execution as execution, edit_authority
from app.invoice.models import Invoice, InvoiceSyncLog
from app.portal.event_models import AuditEvent
from test_mysql_invoice_cancellation_refresh import demote_admin


def events(e, action):
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        return [dict(row.safe_diff_json) for row in facts.journal(db,invoice) if row.action==action]


def result_state(e):
    with Session(e.ctx.engine) as db:
        row=db.get(Invoice,e.invoice_id)
        return row.status,dict(row.cancellation)


@pytest.mark.parametrize('codes,status',[([],403),(['invoice:admin'],404)])
def test_remove_rechecks_old_jwt_roles_and_scope(editor,monkeypatch,codes,status):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);demote_admin(e,codes)
    before=e.snapshot();response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==status,response.text
    assert calls==[] and e.snapshot()==before


def test_remove_claim_fact_fencing_and_safe_token_projection(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    state=response.json()['data'];assert 'token' not in state
    assert state['status']=='remote_deleted' and not state['recovery_summary']['review_required']
    assert len(calls)==2 and [call[2] for call in calls]==[True,False]
    starts=events(e,facts.START);observed=events(e,facts.FACT)
    assert len(starts)==1 and len(observed)==2
    assert {(row['effect_kind'],row['result_class'],row['evidence']) for row in observed}=={
        ('delete_response','succeeded','accepted'),('readback_observation','succeeded','absent')}
    _,private=result_state(e)
    with Session(e.ctx.engine) as db:
        logs=db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==e.invoice_id)).all()
        assert all(private['token'] not in (row.request_digest or '') for row in logs)
    assert private['token'] not in str(starts+observed) and 'synthetic-private-token' not in response.text
    snapshot=e.snapshot();again=asyncio.run(e.write(route,body,method,e.admin_token))
    assert again.status_code==200 and len(calls)==2 and e.snapshot()==snapshot


@pytest.mark.parametrize('phase',['token','inspect'])
@pytest.mark.parametrize('change',['inactive','binding','document'])
def test_remove_capture_is_unlocked_and_final_authority_binding_blocks_send(editor,monkeypatch,phase,change):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);ready=Event();release=Event()
    module,name=(okki_client,'ensure_access_token') if phase=='token' else (execution.cancel,'inspect')
    original=getattr(module,name)
    def gate(*args,**kwargs):ready.set();assert release.wait(8);return original(*args,**kwargs)
    monkeypatch.setattr(module,name,gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='binding':invoice.xiaoman_order_id='changed-target'
                else:invoice.remark='Changed after capture'
                db.commit()
            snapshot=e.snapshot();release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 409),response.text
    assert calls==[] and e.snapshot()==snapshot


@pytest.mark.parametrize('phase',['delete','readback'])
@pytest.mark.parametrize('change',['inactive','lease','takeover','document'])
def test_inflight_remove_releases_locks_and_keeps_original_facts(editor,monkeypatch,phase,change):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);ready=Event();release=Event()
    original=execution.lifecycle_remote.request
    def gate(token,kind,identity,*,remove=False):
        if remove==(phase=='delete'):ready.set();assert release.wait(8)
        return original(token,kind,identity,remove=remove)
    monkeypatch.setattr(execution.lifecycle_remote,'request',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='lease':invoice.cancellation={**invoice.cancellation,'lease_until':(beijing_now()-timedelta(seconds=1)).isoformat()}
                elif change=='takeover':invoice.cancellation={**invoice.cancellation,'token':'new-owner-token','attempt_key':'new-owner-attempt'}
                else:invoice.remark='Changed during external operation'
                db.commit()
            before=result_state(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 409),response.text
    assert len(events(e,facts.START))==1 and len(events(e,facts.FACT))==2
    assert [call[2] for call in calls]==[True,False]
    if change=='inactive':assert result_state(e)[1]['status']=='remote_deleted'
    else:assert result_state(e)==before


def test_delete_accepted_readback_unavailable_keeps_two_facts_and_never_resends(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    def request(token,kind,identity,*,remove=False):
        calls.append((kind,str(identity),remove))
        if remove:return True
        raise okki_client.OkkiApiError('PRIVATE-UPSTREAM-RESPONSE')
    monkeypatch.setattr(lifecycle_remote,'request',request)
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    assert response.json()['data']['status']=='uncertain' and 'PRIVATE-UPSTREAM-RESPONSE' not in response.text
    observed=events(e,facts.FACT)
    assert {(row['effect_kind'],row['result_class']) for row in observed}=={
        ('delete_response','succeeded'),('readback_observation','unknown')}
    assert response.json()['data']['recovery_summary']['review_required']
    again=asyncio.run(e.write(route,body,method,e.admin_token));assert again.status_code==200,again.text
    assert 'token' not in again.json()['data'] and 'synthetic-private-token' not in again.text
    refreshed=asyncio.run(e.write(route,{**body,'action':'refresh'},method,e.admin_token))
    assert refreshed.status_code==200 and 'token' not in refreshed.json()['data']
    assert sum(call[2] for call in calls)==1 and len(events(e,facts.FACT))==2


def test_expired_remove_retained_terminal_shows_and_reconciles_late_facts(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);ready=Event();release=Event()
    original=lifecycle_remote.request
    def gate(token,kind,identity,*,remove=False):
        if not remove:ready.set();assert release.wait(8)
        return original(token,kind,identity,remove=remove)
    monkeypatch.setattr(lifecycle_remote,'request',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                invoice.cancellation={**invoice.cancellation,'lease_until':(beijing_now()-timedelta(seconds=1)).isoformat()};db.commit()
            retained=asyncio.run(e.write(route,{**body,'action':'retain'},method,e.admin_token));assert retained.status_code==200,retained.text
            assert '远端单据及' not in retained.text
            before=result_state(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==409 and result_state(e)==before
    read=asyncio.run(e.write(route,{},'GET',e.admin_token));assert read.status_code==200,read.text
    assert read.json()['data']['recovery_summary']['review_required'] and 'token' not in read.json()['data']['cancellation']
    reconciled=asyncio.run(e.write(route,{**body,'action':'refresh'},method,e.admin_token));assert reconciled.status_code==200,reconciled.text
    assert result_state(e)==before and not reconciled.json()['data']['recovery_summary']['review_required']
    assert sum(call[2] for call in calls)==1


from dataclasses import replace
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.parametrize('ack_lost',[False,True])
def test_claim_commit_failure_never_sends_new_delete(editor,monkeypatch,ack_lost):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    original=Session.commit;lost=[]
    def commit(db):
        starts=db.scalars(select(AuditEvent).where(AuditEvent.action==facts.START)).all()
        should_fail=not lost and any(row.safe_diff_json.get('invoice_id')==e.invoice_id for row in starts)
        if should_fail:
            lost.append(True)
            if ack_lost:original(db)
            raise SQLAlchemyError('PRIVATE-COMMIT-ACK')
        return original(db)
    monkeypatch.setattr(Session,'commit',commit)
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==503 and calls==[] and 'PRIVATE-COMMIT-ACK' not in response.text
    assert len(events(e,facts.START))==int(ack_lost) and events(e,facts.FACT)==[]
    assert result_state(e)[1]['status']==('deleting' if ack_lost else 'pending')
    if ack_lost:
        again=asyncio.run(e.write(route,body,method,e.admin_token));assert again.status_code==200,again.text
        assert calls==[] and 'token' not in again.json()['data']
        with Session(e.ctx.engine) as db:
            lock_authority(db);row=edit_authority.lock_document(db,e.invoice_id)
            row.cancellation={**row.cancellation,'lease_until':(beijing_now()-timedelta(seconds=1)).isoformat()};db.commit()
        again=asyncio.run(e.write(route,body,method,e.admin_token));assert again.status_code==200,again.text
        assert calls==[] and len(events(e,facts.START))==1


def test_result_commit_ack_loss_returns_original_durable_completion(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    original=Session.commit;lost=[]
    def commit(db):
        finished=db.scalars(select(AuditEvent).where(AuditEvent.action==facts.FINISHED)).all()
        drop=not lost and any(row.safe_diff_json.get('invoice_id')==e.invoice_id for row in finished)
        original(db)
        if drop:
            lost.append(True)
            raise SQLAlchemyError('PRIVATE-COMMIT-ACK')
    monkeypatch.setattr(Session,'commit',commit)
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    assert lost==[True] and len(calls)==2 and result_state(e)[1]['status']=='remote_deleted'
    assert len(events(e,facts.FACT))==2 and len(events(e,facts.FINISHED))==1 and len(events(e,facts.RECONCILED))==1
    before=e.snapshot();again=asyncio.run(e.write(route,body,method,e.admin_token))
    assert again.status_code==200 and len(calls)==2 and e.snapshot()==before


@pytest.mark.parametrize('failures',[2,4])
def test_fact_save_bounded_retry_preserves_observation_identity(editor,monkeypatch,failures):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    original=facts.append;original_persist=execution.persist_result;failed=[];captured=[]
    def append(db,invoice_id,key,action,data,**kwargs):
        if action==facts.FACT and len(failed)<failures:
            failed.append(True);raise SQLAlchemyError('PRIVATE-FACT-SAVE')
        return original(db,invoice_id,key,action,data,**kwargs)
    def persist(db,attempt,observations):
        captured.append((attempt,observations));return original_persist(db,attempt,observations)
    monkeypatch.setattr(facts,'append',append);monkeypatch.setattr(execution,'persist_result',persist)
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==(200 if failures==2 else 503),response.text
    assert len(failed)==min(failures,3) and len(calls)==2 and 'PRIVATE-FACT-SAVE' not in response.text
    if failures==2:
        observed=events(e,facts.FACT);expected=captured[0][1]
        assert sorted(row['observed_at'] for row in observed)==sorted(row['observed_at'] for row in expected)
        before=e.snapshot();monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(days=1))
        with Session(e.ctx.engine) as db:assert original_persist(db,*captured[0])
        assert e.snapshot()==before and len(calls)==2
    else:
        assert events(e,facts.FACT)==[] and result_state(e)[1]['status']=='deleting'
        again=asyncio.run(e.write(route,body,method,e.admin_token));assert again.status_code==200,again.text
        assert len(calls)==2 and len(events(e,facts.START))==1


def late_attempt(e):
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        attempt=facts.start(db,invoice,edit_authority._binding(db,invoice),'restricted-original-token',e.ctx.admin)
        invoice.cancellation={**invoice.cancellation,'status':'retained','attempt_key':attempt.key,
            'token':attempt.token,'lease_until':(beijing_now()-timedelta(seconds=1)).isoformat()}
        invoice.status='cancelled';db.commit()
        return attempt


def append_late(e,attempt,fact):
    with Session(e.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,e.invoice_id)
        facts.record(db,attempt,(fact,));db.commit()


def test_reconciliation_cannot_cover_facts_arriving_after_remote_observation(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);attempt=late_attempt(e)
    ready=Event();release=Event()
    from app.receipt import remote
    def gate(*args):ready.set();assert release.wait(8);return []
    monkeypatch.setattr(remote,'order_receipts',gate)
    before=result_state(e)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,{**body,'action':'refresh'},method,e.admin_token))
        try:
            assert ready.wait(6)
            append_late(e,attempt,facts.observation(attempt,'readback_observation','succeeded','absent'))
            release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==409,response.text
    assert events(e,facts.RECONCILED)==[] and result_state(e)==before
    read=asyncio.run(e.write(route,{},'GET',e.admin_token));assert read.json()['data']['recovery_summary']['review_required']
    again=asyncio.run(e.write(route,{**body,'action':'refresh'},method,e.admin_token));assert again.status_code==200,again.text
    assert not again.json()['data']['recovery_summary']['review_required'] and result_state(e)==before
    append_late(e,attempt,facts.observation(attempt,'delete_response','succeeded','accepted'))
    read=asyncio.run(e.write(route,{},'GET',e.admin_token));assert read.json()['data']['recovery_summary']['review_required']
    assert sum(call[2] for call in calls)==0


@pytest.mark.parametrize('mutation',['token','invoice','object','target'])
def test_forged_original_attempt_cannot_record_cross_bound_facts(editor,monkeypatch,mutation):
    e=editor;setup_remove(e,monkeypatch);attempt=late_attempt(e)
    corrupt=replace(attempt,**{'token':{'token':'wrong'},'invoice':{'invoice_id':e.invoice_id+10000},
        'object':{'object_id':'00000000-0000-0000-0000-000000000000'},'target':{'target':'wrong-target'}}[mutation])
    fact=facts.observation(attempt,'readback_observation','succeeded','absent');before=e.snapshot()
    with Session(e.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,e.invoice_id)
        with pytest.raises(HTTPException) as caught:facts.record(db,corrupt,(fact,))
        assert caught.value.status_code==409;db.rollback()
    assert e.snapshot()==before


@pytest.mark.parametrize('stop',[False,True])
def test_inflight_flag_off_keeps_force_lineage_and_fresh_response_authority(editor,monkeypatch,stop):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);ready=Event();release=Event()
    from app.portal.authority import get_settings
    settings=get_settings();original=lifecycle_remote.request;locked=[];sql_locks=[];lock_original=edit_authority.lock_document
    def observe(conn,cursor,statement,params,context,many):
        if not settings.PORTAL_ENABLED and 'FOR UPDATE' in statement.upper():sql_locks.append(statement)
    event.listen(e.ctx.engine,'before_cursor_execute',observe)
    def track(db,identity,**kwargs):
        if kwargs.get('force') and not settings.PORTAL_ENABLED:locked.append(identity)
        return lock_original(db,identity,**kwargs)
    monkeypatch.setattr(edit_authority,'lock_document',track)
    def gate(token,kind,identity,*,remove=False):
        if not remove:ready.set();assert release.wait(8)
        return original(token,kind,identity,remove=remove)
    monkeypatch.setattr(lifecycle_remote,'request',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            if stop:
                with Session(e.ctx.engine) as db:
                    lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
            monkeypatch.setattr(settings,'PORTAL_ENABLED',False)
            release.set();response=pending.result(timeout=8)
        finally:
            release.set();monkeypatch.setattr(settings,'PORTAL_ENABLED',True)
            event.remove(e.ctx.engine,'before_cursor_execute',observe)
    assert response.status_code==(403 if stop else 200),response.text
    assert locked and all(identity==e.invoice_id for identity in locked)
    indices=[next(i for i,sql in enumerate(sql_locks) if 'FROM '+table in sql) for table in
        ('ark_order_portal_auth_barriers','ark_order_portal_requests','ark_order_portal_conversions','ark_invoices')]
    assert indices==sorted(indices) and len(set(indices))==4,sql_locks
    assert len(events(e,facts.FACT))==2 and result_state(e)[1]['status']=='remote_deleted'


@pytest.mark.parametrize('status',[200,401,403,404,409,503])
def test_lifecycle_http_success_and_rejections_are_uncached(editor,monkeypatch,status):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);token=e.admin_token
    if status==401:token='invalid-jwt'
    elif status==403:
        with Session(e.ctx.engine) as db:
            lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    elif status==404:demote_admin(e,['invoice:admin'])
    elif status==409:body={**body,'confirmed':False}
    elif status==503:
        def fail(*a):raise okki_client.OkkiApiError('PRIVATE-UPSTREAM')
        monkeypatch.setattr(okki_client,'ensure_access_token',fail)
    response=asyncio.run(e.write(route,body,method,token))
    assert response.status_code==status,response.text
    assert 'no-store' in response.headers.get('cache-control','')


@pytest.mark.parametrize('phase',['token','delete'])
def test_remove_checks_financial_intent_at_claim_and_result(editor,monkeypatch,phase):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);ready=Event();release=Event()
    module,name=(okki_client,'ensure_access_token') if phase=='token' else (lifecycle_remote,'request')
    original=getattr(module,name)
    def gate(*args,**kwargs):
        if phase=='token' or kwargs.get('remove'):ready.set();assert release.wait(8)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,name,gate)
    from app.receipt.models import ReceiptIntent
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                intent=ReceiptIntent(invoice_id=invoice.id,eligible=1,created_by=e.ctx.actor,attachment_ids=[],status='armed');db.add(intent);db.commit()
            release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==200,response.text
    state=response.json()['data'];assert state['status']==('blocked' if phase=='token' else 'uncertain')
    assert state['evidence']['blockers'] and result_state(e)[0]=='cancel_pending'
    assert sum(call[2] for call in calls)==(0 if phase=='token' else 1)
    assert len(events(e,facts.FACT))==(0 if phase=='token' else 2)


def test_summary_time_has_beijing_offset_without_moving_original_observation(editor,monkeypatch):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch)
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    from datetime import datetime
    value=response.json()['data']['recovery_summary']['last_observed_at']
    assert value.endswith('+08:00')
    internal=max(row['observed_at'] for row in events(e,facts.FACT))
    assert datetime.fromisoformat(value).replace(tzinfo=None)>=datetime.fromisoformat(internal)
    read=asyncio.run(e.write(route,{},'GET',e.admin_token));assert read.status_code==200,read.text
    assert read.json()['data']['recovery_summary']['last_observed_at']==value
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        journal=facts.journal(db,invoice)
        frozen=max(row.safe_diff_json['observed_at'] for row in journal if row.action in {facts.FACT,facts.RECONCILED})
    assert datetime.fromisoformat(value).replace(tzinfo=None)==datetime.fromisoformat(frozen)


@pytest.mark.parametrize('reviewed',[False,True])
def test_reset_cancel_json_cannot_erase_original_execution_or_authorize_another_delete(editor,monkeypatch,reviewed):
    e=editor;route,body,method,calls=setup_remove(e,monkeypatch);attempt=late_attempt(e)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        if reviewed:facts.reconcile(db,invoice,'present',e.ctx.admin)
        invoice.cancellation={**invoice.cancellation,'status':'pending','token':None,'attempt_key':None,'lease_until':None}
        invoice.status='cancel_pending';db.commit()
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    assert calls==[] and len(events(e,facts.START))==1
    before=e.snapshot();aborted=asyncio.run(e.write(route,{**body,'action':'abort'},method,e.admin_token))
    assert aborted.status_code==409 and e.snapshot()==before


def test_fact_record_rejects_uncontrolled_extra_payload(editor,monkeypatch):
    e=editor;setup_remove(e,monkeypatch);attempt=late_attempt(e)
    fact={**facts.observation(attempt,'readback_observation','succeeded','absent'),'provider_body':'PRIVATE-DATA'}
    before=e.snapshot()
    with Session(e.ctx.engine) as db:
        lock_authority(db);edit_authority.lock_document(db,e.invoice_id)
        with pytest.raises(HTTPException) as rejected:facts.record(db,attempt,(fact,))
        assert rejected.value.status_code==409;db.rollback()
    assert e.snapshot()==before
