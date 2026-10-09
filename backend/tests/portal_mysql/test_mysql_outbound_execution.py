"""Actual JWT/MySQL outbound writer phases; only supplier HTTP/mirror are synthetic."""
import asyncio
from copy import deepcopy
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import HTTPException
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.portal.authority import lock_authority
from app.shipping_inspection import outbound_sync_service as sync, outbound_sync_state as state
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection, ShippingInspectionPhoto
from test_mysql_outbound_prepare import setup, preview, snapshot
from test_mysql_invoice_cancellation_refresh import demote_admin
from app.shipping_inspection import outbound_facts as facts, outbound_execution as execution
from app.core.time import beijing_now
from datetime import datetime, timedelta


def send(c, version, **options):
    return asyncio.run(c.e.write(c.route.removesuffix('/preview'),
        {'expected_version': version, **options}, 'POST', c.e.admin_token))


def install_post(c, monkeypatch, gate=None):
    def post(url, *, headers, json, timeout):
        assert url.endswith('/v1/invoices/outbound/push')
        if gate: gate()
        c.posts.append(deepcopy(json))
        c.outbound['record_list'] = deepcopy(json['record_list'])
        c.outbound.update(remark=json['remark'], update_time='2026-10-05 12:00:00')
        if 'serial_id' in json: c.outbound['serial_id'] = json['serial_id']
        return httpx.Response(200, json={'code':200, 'data':{'outbound_invoice_id':701}})
    monkeypatch.setattr(sync.okki_client.httpx, 'post', post)


def event(c):
    with Session(c.e.ctx.engine) as db:
        row=db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==state.SCOPE,
                       ShippingOperationEvent.request_id==c.record['outbound_record_id']))
        return row.action, deepcopy(row.payload), deepcopy(row.result)


def test_post_releases_authority_and_invoice_locks_and_keeps_late_original_fact(editor, monkeypatch, tmp_path):
    c=setup(editor,monkeypatch,tmp_path)
    first=preview(c);assert first.status_code==200,first.text
    errors=[]; phases=[]
    original_prepare=sync._prepare
    def observe_prepare(*args,**kwargs):
        phases.append('prepare:start'); result=original_prepare(*args,**kwargs); phases.append('prepare:end'); return result
    monkeypatch.setattr(sync,'_prepare',observe_prepare)
    original_token=sync.okki_client.ensure_access_token
    def observe_token(*args,**kwargs):
        phases.append('token:start'); result=original_token(*args,**kwargs); phases.append('token:end'); return result
    monkeypatch.setattr(sync.okki_client,'ensure_access_token',observe_token)
    def revoke():
        phases.append('post:start')
        try:
            with Session(editor.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db,force=True)
                invoice=sync.Invoice
                db.scalar(select(invoice).where(invoice.id==editor.invoice_id).with_for_update())
                db.get(ArkUser,editor.ctx.admin).is_active=False
                db.commit()
        except (OperationalError, HTTPException) as error: errors.append(type(error).__name__)
    # Independent connection must acquire both locks while the actual HTTP POST is in progress.
    install_post(c,monkeypatch,revoke)
    response=send(c,first.json()['data']['version'])
    assert errors==[], 'Outbound POST still holds authority/PI locks'
    assert response.status_code==403,(response.text,phases,c.reads,len(c.posts))
    assert len(c.posts)==1
    action,payload,result=event(c)
    assert action=='sync_sending' and not result.get('verified')
    with Session(editor.ctx.engine) as db:
        facts=db.scalars(select(ShippingOperationEvent).where(ShippingOperationEvent.scope=='outbound-sync-fact',
            ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id'])).all()
        assert len(facts)==1 and facts[0].result['result_class']=='accepted'
        assert facts[0].payload['outbound_invoice_id']=='701'



def rows(c,scope):
    with Session(c.e.ctx.engine) as db:
        return [(row.request_id,deepcopy(row.payload),deepcopy(row.result)) for row in db.scalars(
            select(ShippingOperationEvent).where(ShippingOperationEvent.scope==scope,
                ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id']).order_by(ShippingOperationEvent.id)).all()]


@pytest.mark.parametrize('window',['token','presend','post','readback'])
@pytest.mark.parametrize('change',['inactive','permission','scope','photo'])
def test_current_authority_and_complete_photo_binding_at_writer_windows(editor,monkeypatch,tmp_path,window,change):
    c=setup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        inspection=ShippingInspection(outbound_record_id=c.record['outbound_record_id'],outbound_no='CK-OWN')
        db.add(inspection);db.flush()
        photo=ShippingInspectionPhoto(inspection_id=inspection.id,file_path='old-owned.png');db.add(photo);db.commit();photo_id=photo.id
    first=preview(c);assert first.status_code==200,first.text
    hit=[];after=[]
    def mutate():
        if hit:return
        hit.append(window)
        if change in ('permission','scope'):
            demote_admin(editor,[] if change=='permission' else ['invoice:sync','shipping_inspection:write','shipping_inspection:read_all'])
        else:
            with Session(editor.ctx.engine) as db:
                lock_authority(db,force=True)
                db.scalar(select(sync.Invoice).where(sync.Invoice.id==editor.invoice_id).with_for_update())
                if change=='inactive':db.get(ArkUser,editor.ctx.admin).is_active=False
                else:db.get(ShippingInspectionPhoto,photo_id).file_path='new-owned.png'
                db.commit()
        after.append(snapshot(c))
    if window=='token':
        original=sync.okki_client.fetch_token
        def fetch():mutate();return original()
        monkeypatch.setattr(sync.okki_client,'fetch_token',fetch)
    if window in ('presend','readback'):
        def gate(stage):
            if window=='readback' and c.posts and stage.startswith('outbound:'):mutate()
            if window=='presend' and stage=='related' and event(c)[0]=='sync_pending':mutate()
        c.gate=gate
    install_post(c,monkeypatch,mutate if window=='post' else None)
    response=send(c,first.json()['data']['version'],confirm_recheck=True)
    assert hit==[window],(response.text,hit)
    assert response.status_code==({'inactive':403,'permission':403,'scope':404,'photo':409}[change]),response.text
    assert 'no-store' in response.headers['cache-control']
    assert snapshot(c)[0]==after[0][0] and snapshot(c)[1][1:]==after[0][1][1:]
    assert len(c.posts)==(1 if window in ('post','readback') else 0)
    assert rows(c,facts.FINISH)==[]
    if c.posts:assert len(rows(c,facts.FACT))==1 and rows(c,facts.FACT)[0][2]['result_class']=='accepted'


def test_post_inflight_off_and_current_task_takeover_keep_original_fact(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c);assert first.status_code==200
    saved=[]
    def takeover():
        from app.portal.authority import get_settings
        monkeypatch.setattr(get_settings(),'PORTAL_ENABLED',False)
        with Session(editor.ctx.engine) as db:
            lock_authority(db,force=True)
            current=db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==state.SCOPE,
                ShippingOperationEvent.request_id==c.record['outbound_record_id']).with_for_update())
            current.payload={**current.payload,'send_nonce':'new-owner-nonce'}
            current.result={**current.result,'message':'New owner state'};db.commit()
        saved.append(event(c))
    install_post(c,monkeypatch,takeover)
    response=send(c,first.json()['data']['version'])
    assert response.status_code==409,response.text
    assert event(c)==saved[0] and len(c.posts)==1 and rows(c,facts.FINISH)==[]
    assert rows(c,facts.FACT)[0][2]['result_class']=='accepted'


@pytest.mark.parametrize('result_class',['accepted','unknown','auth_rejected'])
def test_actual_post_classification_no_blind_replay_and_current_verified_result(editor,monkeypatch,tmp_path,result_class):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c);assert first.status_code==200
    def post(url,*,headers,json,timeout):
        c.posts.append(deepcopy(json))
        if result_class=='unknown':raise httpx.ReadTimeout('Synthetic ACK loss')
        if result_class=='auth_rejected':return httpx.Response(401)
        c.outbound['record_list']=deepcopy(json['record_list']);c.outbound.update(remark=json['remark'],update_time='2026-10-05 12:00:00')
        return httpx.Response(200,json={'code':200,'data':{'outbound_invoice_id':701}})
    monkeypatch.setattr(sync.okki_client.httpx,'post',post)
    response=send(c,first.json()['data']['version'])
    assert response.status_code==200,response.text
    assert response.json()['data']['status']==('sync_done' if result_class=='accepted' else 'sync_uncertain')
    assert rows(c,facts.FACT)[0][2]['result_class']==result_class
    again=send(c,first.json()['data']['version'],check_only=True)
    assert again.status_code==200,again.text
    assert len(c.posts)==1


def test_original_fact_duplicate_save_is_idempotent_and_orm_namespace_escape_is_blocked(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c);install_post(c,monkeypatch)
    assert send(c,first.json()['data']['version']).status_code==200
    original=rows(c,facts.FACT)
    nonce=original[0][0]
    with Session(editor.ctx.engine) as db:
        start=facts.get(db,facts.START,nonce)
        attempt=facts.Attempt(nonce,deepcopy(start.payload));db.rollback()
        # Same original provider response under a later wall clock must reuse its first timestamp.
        monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(seconds=10))
        facts.observe(db,attempt,'accepted',{'outbound_invoice_id':701});db.commit()
    assert rows(c,facts.FACT)==original
    with Session(editor.ctx.engine) as db:
        row=facts.get(db,facts.FACT,nonce);db.expire(row,['scope'])
        row.scope='ordinary-history';row.result={'result_class':'unknown'}
        with pytest.raises(ValueError,match='immutable'):db.flush()
        db.rollback()
    with Session(editor.ctx.engine) as db:
        row=facts.get(db,facts.FACT,nonce);db.expire(row,['scope']);db.delete(row)
        with pytest.raises(ValueError,match='immutable'):db.flush()
        db.rollback()
    assert rows(c,facts.FACT)==original
    # Ordinary mutable synchronization rows keep their established update semantics.
    with Session(editor.ctx.engine) as db:
        row=db.scalar(select(ShippingOperationEvent).where(ShippingOperationEvent.scope==state.SCOPE,
            ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id']))
        row.result={**row.result,'message':'Authorized local control'};db.commit()
    assert event(c)[2]['message']=='Authorized local control'


@pytest.mark.parametrize('start',['2026-10-05T23:58:00','2026-10-05T15:58:00+00:00','2026-10-05T08:58:00-07:00'])
def test_outbound_lease_beijing_midnight_and_non_beijing_server(monkeypatch,start):
    attempt=facts.Attempt('owned',{'started_at':start})
    monkeypatch.setattr(facts,'beijing_now',lambda:datetime(2026,10,6,0,2,59))
    assert facts.expired(attempt) is False
    monkeypatch.setattr(facts,'beijing_now',lambda:datetime(2026,10,6,0,3,0))
    assert facts.expired(attempt) is True



@pytest.mark.parametrize('phase',[facts.START,facts.SEND,facts.FACT,facts.FINISH])
@pytest.mark.parametrize('lost_ack',[False,True])
def test_actual_commits_before_failure_or_lost_ack_do_not_replay_post(editor,monkeypatch,tmp_path,phase,lost_ack):
    c=setup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        inspection=ShippingInspection(outbound_record_id=c.record['outbound_record_id'],outbound_no='CK-OWN')
        db.add(inspection);db.flush();db.add(ShippingInspectionPhoto(inspection_id=inspection.id,file_path='owned.png'));db.commit()
    first=preview(c);assert first.status_code==200
    install_post(c,monkeypatch)
    original_commit=Session.commit;hit=[]
    def gate(db):
        target=db.in_transaction() and db.connection().scalar(select(ShippingOperationEvent.id).where(
            ShippingOperationEvent.scope==phase,ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id']).limit(1)) is not None
        if target and not hit:
            hit.append(phase)
            if lost_ack:original_commit(db)
            raise OperationalError('Synthetic commit boundary',None,RuntimeError('ACK unavailable'))
        return original_commit(db)
    monkeypatch.setattr(Session,'commit',gate)
    response=send(c,first.json()['data']['version'],confirm_recheck=True)
    assert hit==[phase] and response.status_code==503,(response.text,hit)
    assert len(c.posts)==(1 if phase in (facts.FACT,facts.FINISH) else 0)
    monkeypatch.setattr(Session,'commit',original_commit)
    if phase==facts.FINISH:
        # FINISH/inspection/overlay either all absent or all committed, then safe original readback recovery.
        with Session(editor.ctx.engine) as db:
            row=db.scalar(select(ShippingInspection).where(ShippingInspection.outbound_record_id==c.record['outbound_record_id']))
            assert row.edit_version==(1 if lost_ack else 0)
        assert len(rows(c,facts.FINISH))==(1 if lost_ack else 0)
        if not lost_ack:
            monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
        again=send(c,first.json()['data']['version'],check_only=True)
        assert again.status_code==200 and again.json()['data']['status']=='sync_done',again.text
        with Session(editor.ctx.engine) as db:
            assert db.scalar(select(ShippingInspection).where(ShippingInspection.outbound_record_id==c.record['outbound_record_id'])).edit_version==1
        assert len(c.posts)==1 and len(rows(c,facts.FINISH))==1
    else:
        again=send(c,first.json()['data']['version'],check_only=True,confirm_recheck=True)
        assert again.status_code==200,again.text
        assert len(c.posts)==(1 if phase==facts.FACT else 0)


def partial_case(c):
    # Add a legitimate second synchronized PI/order line; the original outbound has only the first.
    with Session(c.e.ctx.engine) as db:
        lock_authority(db,force=True)
        invoice=sync._invoice(db,c.outbound,{'roles':['super_admin'],'sub':str(c.e.ctx.admin)})
        item=invoice.items[0]
        copy={column.name:getattr(item,column.name) for column in item.__table__.columns if column.name not in ('id','created_at','updated_at')}
        copy.update(xiaoman_unique_id='502',sort_order=1)
        db.add(sync.InvoiceItem(**copy));invoice.total_amount*=2;db.commit()
    second={**deepcopy(c.order['product_list'][0]),'unique_id':'502'}
    c.order['product_list'].append(second);c.order['amount']=str(float(c.order['amount'])*2)


@pytest.mark.parametrize('reference',['0701','７０１',True,None,702,701])
def test_invalid_response_identity_never_authorizes_automatic_missing_row_repair(editor,monkeypatch,tmp_path,reference):
    c=setup(editor,monkeypatch,tmp_path);partial_case(c);first=preview(c);assert first.status_code==200,first.text
    def post(url,*,headers,json,timeout):
        c.posts.append(deepcopy(json))
        # Provider acknowledges but only original existing rows have appeared.
        c.outbound['record_list']=deepcopy([row for row in json['record_list'] if row.get('outbound_record_id')])
        c.outbound.update(remark=json['remark'],update_time='2026-10-05 12:00:00')
        return httpx.Response(200,json={'code':200,'data':{} if reference is None else {'outbound_invoice_id':reference}})
    monkeypatch.setattr(sync.okki_client.httpx,'post',post)
    response=send(c,first.json()['data']['version'])
    assert response.status_code==200 and response.json()['data']['status']=='sync_uncertain',response.text
    assert response.json()['data']['repairable'] is (reference==701 and type(reference) is int)
    assert rows(c,facts.FACT)[0][2]['result_class']==('accepted' if type(reference) is int and reference==701 else 'unknown')
    if not (type(reference) is int and reference==701):
        again=send(c,first.json()['data']['version'],repair=True)
        assert again.status_code==200 and again.json()['data']['repairable'] is False,again.text
        assert len(c.posts)==1


def test_accepted_partial_response_repairs_one_new_uid_with_original_cost_and_handler(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);partial_case(c);first=preview(c);assert first.status_code==200
    def post(url,*,headers,json,timeout):
        c.posts.append(deepcopy(json))
        if len(c.posts)==1:
            c.outbound['record_list']=deepcopy([row for row in json['record_list'] if row.get('outbound_record_id')])
        else:
            c.outbound['record_list']=deepcopy(json['record_list'])
            for row in c.outbound['record_list']:
                if not row.get('outbound_record_id'):row['outbound_record_id']=902
                row.setdefault('cost_unit_price_rmb',0)
        c.outbound.update(remark=json['remark'],update_time='2026-10-05 12:00:00')
        return httpx.Response(200,json={'code':200,'data':{'outbound_invoice_id':701}})
    monkeypatch.setattr(sync.okki_client.httpx,'post',post)
    initial=send(c,first.json()['data']['version']);assert initial.status_code==200 and initial.json()['data']['repairable'] is True,initial.text
    response=send(c,first.json()['data']['version'],repair=True)
    assert response.status_code==200 and response.json()['data']['status']=='sync_done',response.text
    assert len(c.posts)==2 and len(rows(c,facts.START))==2 and len(rows(c,facts.FINISH))==2
    assert len([row for row in c.posts[1]['record_list'] if not row.get('outbound_record_id')])==1
    assert c.posts[1]['handler']==c.posts[0]['handler']
    existing=[row for row in c.posts[1]['record_list'] if row.get('outbound_record_id')][0]
    assert existing['outbound_record_id']==801 and existing['cost_unit_price_rmb']==0
    again=send(c,first.json()['data']['version'],check_only=True)
    assert again.status_code==200 and len(c.posts)==2,again.text



def test_finish_then_late_original_post_fact_has_authorized_readonly_review(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path)
    with Session(editor.ctx.engine) as db:
        inspection=ShippingInspection(outbound_record_id=c.record['outbound_record_id'],outbound_no='CK-OWN')
        db.add(inspection);db.flush();db.add(ShippingInspectionPhoto(inspection_id=inspection.id,file_path='owned.png'));db.commit()
    first=preview(c);install_post(c,monkeypatch)
    original_commit=Session.commit;hit=[]
    def lose_fact(db):
        if not hit and db.in_transaction() and db.connection().scalar(select(ShippingOperationEvent.id).where(
                ShippingOperationEvent.scope==facts.FACT,ShippingOperationEvent.outbound_record_id==c.record['outbound_record_id']).limit(1)):
            hit.append(True);raise OperationalError('Synthetic fact not committed',None,RuntimeError('ACK unavailable'))
        return original_commit(db)
    monkeypatch.setattr(Session,'commit',lose_fact)
    initial=send(c,first.json()['data']['version'],confirm_recheck=True)
    assert initial.status_code==503 and hit==[True] and len(c.posts)==1 and rows(c,facts.FACT)==[]
    monkeypatch.setattr(Session,'commit',original_commit)
    nonce,data,_=rows(c,facts.START)[0];attempt=facts.Attempt(nonce,data)
    monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
    recovered=send(c,first.json()['data']['version'],check_only=True)
    assert recovered.status_code==200 and recovered.json()['data']['status']=='sync_done',recovered.text
    before=snapshot(c)
    with Session(editor.ctx.engine) as db:
        facts.observe(db,attempt,'accepted',{'outbound_invoice_id':701});db.commit()
    result=send(c,first.json()['data']['version'],check_only=True)
    assert result.status_code==200 and result.json()['data']['status']=='sync_done',result.text
    assert len(rows(c,facts.REVIEW))==1 and len(c.posts)==1
    assert snapshot(c)[0]==before[0] and snapshot(c)[1][1:]==before[1][1:]
    assert preview(c).status_code==200


def test_concurrent_late_read_cannot_permanently_block_finished_original(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c)
    def timeout(url,*,headers,json,timeout):
        c.posts.append(deepcopy(json));raise httpx.ReadTimeout('Synthetic lost response')
    monkeypatch.setattr(sync.okki_client.httpx,'post',timeout)
    initial=send(c,first.json()['data']['version']);assert initial.status_code==200 and initial.json()['data']['status']=='sync_uncertain'
    c.outbound['record_list']=deepcopy(c.posts[0]['record_list']);c.outbound['remark']=c.posts[0]['remark']
    c.outbound['update_time']='2026-10-05 12:00:00'
    ready,release=Event(),Event();blocked=[]
    def gate(stage):
        if stage.startswith('outbound:') and not blocked:
            blocked.append(True);ready.set();assert release.wait(10)
    c.gate=gate
    with ThreadPoolExecutor(max_workers=1) as pool:
        late=pool.submit(send,c,first.json()['data']['version'],check_only=True)
        try:
            assert ready.wait(6)
            finished=send(c,first.json()['data']['version'],check_only=True)
            assert finished.status_code==200 and finished.json()['data']['status']=='sync_done',finished.text
            before=event(c);release.set();old=late.result(timeout=10)
        finally:release.set()
    assert old.status_code==409,old.text
    assert event(c)==before and len(c.posts)==1 and len(rows(c,facts.FINISH))==1
    assert preview(c).status_code==200
    assert send(c,first.json()['data']['version'],check_only=True).status_code==200


def test_expired_sender_without_terminal_fact_does_not_authorize_new_repair_post(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);partial_case(c);first=preview(c)
    install_post(c,monkeypatch)
    ready,release=Event(),Event();hit=[];original_commit=Session.commit
    def pause(db):
        result=original_commit(db)
        if not hit and any(isinstance(row,ShippingOperationEvent) and row.scope==state.SCOPE and row.action=='sync_sending'
                and row.outbound_record_id==c.record['outbound_record_id'] for row in db.identity_map.values()):
            hit.append(True);ready.set();assert release.wait(10)
        return result
    monkeypatch.setattr(Session,'commit',pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old=pool.submit(send,c,first.json()['data']['version'])
        try:
            assert ready.wait(6)
            monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
            c.outbound.update(remark='',update_time='2026-10-05 12:00:00')
            recovery=send(c,first.json()['data']['version'],repair=True)
            assert recovery.status_code==200 and recovery.json()['data']['status']=='sync_uncertain',recovery.text
            assert recovery.json()['data']['repairable'] is False and c.posts==[]
            release.set();response=old.result(timeout=10)
        finally:release.set()
    assert response.status_code==409 and len(c.posts)==1,response.text
    assert len(rows(c,facts.START))==len(rows(c,facts.SEND))==len(rows(c,facts.FACT))==1


def test_fact_arriving_during_get_invalidates_old_evidence_then_original_recovery_succeeds(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c)
    def timeout(url,*,headers,json,timeout):
        c.posts.append(deepcopy(json));raise httpx.ReadTimeout('Synthetic uncertain response')
    monkeypatch.setattr(sync.okki_client.httpx,'post',timeout)
    assert send(c,first.json()['data']['version']).status_code==200
    nonce,data,_=rows(c,facts.START)[0];attempt=facts.Attempt(nonce,data)
    c.outbound['record_list']=deepcopy(c.posts[0]['record_list']);c.outbound.update(remark='',update_time='2026-10-05 12:00:00')
    hit=[]
    def gate(stage):
        if stage.startswith('outbound:') and not hit:
            hit.append(True)
            with Session(editor.ctx.engine) as db:
                # New independent immutable observation, without changing the mutable current event.
                facts.observe(db,attempt,'unknown',{'separate_read':'new observation'},reading=True);db.commit()
    c.gate=gate;before=event(c)
    rejected=send(c,first.json()['data']['version'],check_only=True)
    assert rejected.status_code==409 and hit==[True],rejected.text
    assert event(c)==before and rows(c,facts.FINISH)==[] and len(c.posts)==1
    c.gate=None
    result=send(c,first.json()['data']['version'],check_only=True)
    assert result.status_code==200 and result.json()['data']['status']=='sync_done',result.text
    assert len(c.posts)==1



def test_internal_followup_cannot_relax_original_manual_warehouse_authority(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c)
    def revoke_write():
        demote_admin(editor,['invoice:sync','invoice:read_all','shipping_inspection:read_all'])
    install_post(c,monkeypatch,revoke_write)
    rejected=send(c,first.json()['data']['version'])
    assert rejected.status_code==403 and len(c.posts)==1,rejected.text
    before=snapshot(c);read_count=len(c.reads)
    monkeypatch.setattr(facts,'beijing_now',lambda:beijing_now()+timedelta(minutes=6))
    with Session(editor.ctx.engine) as db:
        with pytest.raises(HTTPException) as error:
            sync.synchronize(db,c.record,{'sub':str(editor.ctx.admin)},None,check_only=True,
                             force_authority=True,warehouse=False)
        assert error.value.status_code==403
    assert snapshot(c)==before and len(c.reads)==read_count and len(c.posts)==1


def test_finished_manual_attempt_rejects_relaxed_internal_authority_before_evidence(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c);install_post(c,monkeypatch)
    completed=send(c,first.json()['data']['version'])
    assert completed.status_code==200 and completed.json()['data']['status']=='sync_done',completed.text
    demote_admin(editor,['invoice:sync','invoice:read_all','shipping_inspection:read_all'])
    before=snapshot(c);read_count=len(c.reads)
    with Session(editor.ctx.engine) as db:
        with pytest.raises(HTTPException) as error:
            sync.synchronize(db,c.record,{'sub':str(editor.ctx.admin)},None,check_only=True,
                             force_authority=True,warehouse=False)
        assert error.value.status_code==403
    assert snapshot(c)==before and len(c.reads)==read_count and len(c.posts)==1


def test_manual_finish_between_preflight_and_prepare_invalidates_old_requirement(editor,monkeypatch,tmp_path):
    c=setup(editor,monkeypatch,tmp_path);first=preview(c);install_post(c,monkeypatch)
    ready,release=Event(),Event();original_prepare=execution.prepare.prepare
    def pause(*args,**kwargs):
        if not kwargs.get('warehouse'):
            ready.set();assert release.wait(12)
        return original_prepare(*args,**kwargs)
    monkeypatch.setattr(execution.prepare,'prepare',pause)
    def follow():
        with Session(editor.ctx.engine) as db:
            try:
                sync.synchronize(db,c.record,{'sub':str(editor.ctx.actor)},None,check_only=True,
                                 force_authority=True,warehouse=False)
                return 200
            except HTTPException as error:return error.status_code
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(follow)
        try:
            assert ready.wait(6)
            completed=send(c,first.json()['data']['version'])
            assert completed.status_code==200 and completed.json()['data']['status']=='sync_done',completed.text
            before=snapshot(c);read_count=len(c.reads)
            release.set();assert pending.result(timeout=10)==409
        finally:release.set()
    assert snapshot(c)==before and len(c.reads)==read_count and len(c.posts)==1
