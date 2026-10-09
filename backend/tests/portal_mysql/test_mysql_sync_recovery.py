"""Real JWT/ASGI and independent MySQL phases for uncertain order reconciliation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, String, select, delete, update, text, event
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.invoice import edit_authority, lifecycle_remote, linked_sync_service as linked, product_service
from app.invoice import outbound_recovery, okki_client, sync_recovery, service as invoice_service
from app.invoice.models import Invoice, InvoiceItem, InvoiceLinkedSync, InvoiceSyncLog, OkkiOutboundTask, XiaomanSettings
from app.portal.authority import lock_authority, get_settings
from app.semifinished.models import InvoiceAllocation
from test_mysql_outbound_recovery import setup_outbound
from test_mysql_invoice_cancellation_refresh import demote_admin


def prepare(e,monkeypatch,resolution):
    setup_outbound(e,monkeypatch,'outbound_retry')
    bind_target=str(900000+e.invoice_id)
    metadata=MetaData();mirror=Table('okki_orders',metadata,Column('order_id',String(64),primary_key=True),
        Column('order_no',String(64)),Column('name',String(200)),Column('company_id',String(64)))
    metadata.create_all(e.ctx.engine)
    monkeypatch.setattr(product_service,'_schema',lambda:e.ctx.engine.url.database)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.status=invoice.sync_status='sync_uncertain'
        invoice.sync_attempt={'token':uuid4().hex,'lease_until':(beijing_now()-timedelta(minutes=1)).isoformat()}
        if resolution!='confirm_existing':invoice.xiaoman_order_id=None
        else:
            db.add(InvoiceLinkedSync(id=uuid4().hex,invoice_id=invoice.id,request_key=uuid4().hex,
                request_hash='b'*64,status='uncertain',before={},after={},steps={'order':{'status':'uncertain'}},
                run_token=uuid4().hex,lease_until=beijing_now()-timedelta(minutes=1),created_by=e.ctx.admin))
            db.flush();invoice.linked_sync_id=db.scalar(select(InvoiceLinkedSync.id).where(InvoiceLinkedSync.invoice_id==invoice.id))
        db.execute(delete(mirror))
        db.execute(mirror.insert().values(order_id=bind_target,order_no='OWNED-'+bind_target,name=invoice.invoice_no,company_id=invoice.customer_id))
        db.commit();db.refresh(invoice)
        rows=outbound_recovery.product_rows(db,invoice)
        evidence={'order_id':'401','company_id':str(invoice.customer_id),'currency':invoice.currency,
            'amount':str(invoice.total_amount-(invoice.surcharge_amount or 0)),
            'product_list':deepcopy(rows)}
        for index,row in enumerate(evidence['product_list']):row['unique_id']=str(row.get('unique_id') or 501+index)
    calls=[]
    def read(*args):calls.append(args[1:]);return deepcopy(evidence)
    monkeypatch.setattr(lifecycle_remote,'read',read)
    return f'/api/invoice/invoices/{e.invoice_id}/sync-uncertain/resolve',{'resolution':resolution,
        'reason':'Reviewed original order identity, items and receipt before reconciliation',
        'xiaoman_order_id':bind_target if resolution=='bind_order' else None},calls,evidence


def business(e):
    with Session(e.ctx.engine) as db:
        return e.snapshot(),tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (OkkiOutboundTask,InvoiceAllocation))


@pytest.mark.parametrize('resolution',['confirm_existing','bind_order','confirm_not_created'])
@pytest.mark.parametrize('change',['inactive','role','scope'])
def test_resolution_rejects_old_jwt_without_any_effect(editor,monkeypatch,resolution,change):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,resolution)
    if change=='inactive':
        with Session(e.ctx.engine) as db:lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    else:demote_admin(e,[] if change=='role' else ['invoice:admin'])
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==(404 if change=='scope' else 403),response.text
    assert calls==[] and business(e)==before


@pytest.mark.parametrize('resolution',['confirm_existing','bind_order','confirm_not_created'])
def test_resolution_success_and_repeat_preserve_single_original_transition(editor,monkeypatch,resolution):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,resolution)
    response=asyncio.run(e.write(route,body,'POST',e.admin_token));assert response.status_code==200,response.text
    assert response.json()['data']['sync_status']=='not_synced' and 'no-store' in response.headers['cache-control']
    before=business(e);count=len(calls)
    repeat=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert repeat.status_code==409 and business(e)==before and len(calls)==count
    assert count==(1 if resolution=='confirm_existing' else 0)
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id)
        assert invoice.sync_attempt is None
        assert invoice.xiaoman_order_id==(body['xiaoman_order_id'] if resolution=='bind_order' else '401' if resolution=='confirm_existing' else None)
        if resolution=='confirm_existing':assert invoice.linked_sync_id is not None
        action={'confirm_existing':'verify_update','bind_order':'uncertain_bind','confirm_not_created':'uncertain_clear'}[resolution]
        assert db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==invoice.id,InvoiceSyncLog.action==action)).operator_id==e.ctx.admin


@pytest.mark.parametrize('change',['inactive','scope','document','currency','amount','uid','attempt','linked','allocation','cancelled'])
def test_unlocked_confirm_existing_rechecks_all_captured_state(editor,monkeypatch,change):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,'confirm_existing');ready=Event();release=Event()
    original=lifecycle_remote.read
    def gate(*args):ready.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(lifecycle_remote,'read',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            if change=='scope':demote_admin(e,['invoice:admin'])
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                version=invoice.portal_document_version;old_hash=linked.edit_version(invoice)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='document':invoice.remark='Another actual transaction changed this invoice'
                elif change in {'currency','amount'}:db.execute(update(Invoice).where(Invoice.id==invoice.id).values({ 'currency' if change=='currency' else 'total_amount':'EUR' if change=='currency' else invoice.total_amount+1}))
                elif change=='uid':db.execute(update(InvoiceItem).where(InvoiceItem.id==invoice.items[0].id).values(xiaoman_unique_id='9001'))
                elif change=='attempt':invoice.sync_attempt={**invoice.sync_attempt,'token':uuid4().hex}
                elif change=='linked':db.get(InvoiceLinkedSync,invoice.linked_sync_id).run_token=uuid4().hex
                elif change=='allocation':db.add(InvoiceAllocation(invoice_id=invoice.id,material_id=123,status='pending',operation_key=uuid4().hex,allocated_qty_grams=1,pending_delta_grams=1))
                elif change=='cancelled':invoice.status='cancelled'
                db.commit();db.expire_all();invoice=edit_authority.lock_document(db,e.invoice_id)
                if change in {'currency','amount','uid'}:assert linked.edit_version(invoice)==old_hash and invoice.portal_document_version==version
            before=business(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 404 if change=='scope' else 409),response.text
    assert business(e)==before


@pytest.mark.parametrize('resolution',['confirm_existing','bind_order','confirm_not_created'])
@pytest.mark.parametrize('status',['cancel_pending','cancelled','ready'])
def test_non_uncertain_or_terminal_state_cannot_be_reopened(editor,monkeypatch,resolution,status):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,resolution)
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id);invoice.status=status
        if status=='ready':invoice.sync_status='not_synced'
        db.commit()
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409 and business(e)==before and calls==[]


@pytest.mark.parametrize('fault',['missing','wrong_order','wrong_company','wrong_currency','missing_rows','bad_uid','duplicate_uid','amount','nan','primitive'])
def test_remote_evidence_never_releases_protection_without_verification(editor,monkeypatch,fault):
    e=editor;route,body,calls,evidence=prepare(e,monkeypatch,'confirm_existing')
    if fault=='missing':evidence=None
    elif fault=='wrong_order':evidence['order_id']='999'
    elif fault=='wrong_company':evidence['company_id']='other'
    elif fault=='wrong_currency':evidence['currency']='EUR'
    elif fault=='missing_rows':evidence['product_list']=None
    elif fault=='bad_uid':evidence['product_list'][0]['unique_id']='untrusted'
    elif fault=='duplicate_uid':evidence['product_list'].append(deepcopy(evidence['product_list'][0]))
    elif fault=='amount':evidence['amount']='not-a-number'
    elif fault=='nan':evidence['product_list'][0]['count']='NaN'
    else:evidence=7
    monkeypatch.setattr(lifecycle_remote,'read',lambda *a:evidence)
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==(503 if fault in {'missing','wrong_order','primitive'} else 409),response.text
    assert business(e)==before and 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('stop',[False,True])
def test_inflight_off_preserves_current_authorization_and_lineage_order(editor,monkeypatch,stop):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,'confirm_existing');ready=Event();release=Event();statements=[]
    original=lifecycle_remote.read;settings=get_settings()
    def observe(conn,cursor,statement,params,ctx,many):
        if not settings.PORTAL_ENABLED and 'FOR UPDATE' in statement.upper():statements.append(statement)
    event.listen(e.ctx.engine,'before_cursor_execute',observe)
    def gate(*args):ready.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(lifecycle_remote,'read',gate)
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
    if not stop:
        indices=[next(i for i,sql in enumerate(statements) if 'FROM '+table in sql) for table in ('ark_order_portal_auth_barriers','ark_order_portal_requests','ark_order_portal_conversions','ark_invoices')]
        assert indices==sorted(indices) and len(set(indices))==4,statements


def two_unanchored_lines(e,evidence):
    """Commercially exact, distinct lines: UID rejection cannot pass for missing anchor."""
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        assert len(invoice.items)==1
        original=invoice.items[0]
        fields={c.name:deepcopy(getattr(original,c.name)) for c in InvoiceItem.__table__.columns
                if c.name not in {'id','invoice_id'}}
        fields.update(product_id=original.product_id+100,sku_id=original.sku_id+100,xiaoman_unique_id=None)
        original.xiaoman_unique_id=None
        invoice.items.append(InvoiceItem(**fields))
        invoice_service._refresh_invoice_totals(invoice);invoice.status=invoice.sync_status="sync_uncertain"
        db.commit();db.refresh(invoice)
        rows=outbound_recovery.product_rows(db,invoice)
        assert len(rows)==2 and all('unique_id' not in row for row in rows)
        assert len({(r['product_id'],r['sku_id']) for r in rows})==2
        evidence.update(product_list=deepcopy(rows),amount=str(invoice.total_amount-(invoice.surcharge_amount or 0)))
        for row,uid in zip(evidence['product_list'],('501','502')):row['unique_id']=uid


@pytest.mark.parametrize('uid',['0501','501',501,True,False,0,-1,'0','-1','+502',' 502','502 ',
                                '1e2','502.0',502.0,'١٢','²',None,'','9'*65])
def test_invalid_unanchored_uid_is_http_409_and_entire_business_unchanged(editor,monkeypatch,uid):
    e=editor;route,body,calls,data=prepare(e,monkeypatch,'confirm_existing')
    two_unanchored_lines(e,data);data['product_list'][1]['unique_id']=uid
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409,response.text
    assert business(e)==before and len(calls)==1 and 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('uids',[(501,502),('501','502'),(501,'502')])
def test_canonical_new_uid_success_commits_exact_assignment_once(editor,monkeypatch,uids):
    e=editor;route,body,calls,data=prepare(e,monkeypatch,'confirm_existing')
    two_unanchored_lines(e,data)
    for row,uid in zip(data['product_list'],uids):row['unique_id']=uid
    response=asyncio.run(e.write(route,body,'POST',e.admin_token));assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        assert [i.xiaoman_unique_id for i in invoice.items]==['501','502']
        assert invoice.sync_attempt is None and invoice.status=='ready'
        assert len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==invoice.id,
                       InvoiceSyncLog.action=='verify_update')).all())==1
    before=business(e);repeat=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert repeat.status_code==409 and business(e)==before and len(calls)==1


@pytest.mark.parametrize('resolution',['confirm_existing','bind_order','confirm_not_created'])
def test_active_original_push_lease_rejects_before_any_remote_read(editor,monkeypatch,resolution):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,resolution)
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id)
        invoice.sync_attempt={**invoice.sync_attempt,'lease_until':(beijing_now()+timedelta(minutes=5)).isoformat()}
        db.commit()
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409 and business(e)==before and calls==[]


@pytest.mark.parametrize('fault',['active','running','missing','wrong_invoice'])
def test_original_linked_execution_guard_is_current_and_zero_read(editor,monkeypatch,fault):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,'confirm_existing')
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id);row=db.get(InvoiceLinkedSync,invoice.linked_sync_id)
        if fault=='active':row.lease_until=beijing_now()+timedelta(minutes=5)
        elif fault=='running':row.status='running'
        elif fault=='missing':invoice.linked_sync_id=uuid4().hex
        else:row.invoice_id+=10000
        db.commit()
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409 and business(e)==before and calls==[]


@pytest.mark.parametrize('lease',['push','linked'])
def test_active_lease_created_during_unlocked_read_blocks_final_recovery(editor,monkeypatch,lease):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,'confirm_existing');ready=Event();release=Event()
    original=lifecycle_remote.read
    def gate(*args):ready.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(lifecycle_remote,'read',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if lease=='push':invoice.sync_attempt={**invoice.sync_attempt,'lease_until':(beijing_now()+timedelta(minutes=5)).isoformat()}
                else:db.get(InvoiceLinkedSync,invoice.linked_sync_id).lease_until=beijing_now()+timedelta(minutes=5)
                db.commit()
            before=business(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==409 and business(e)==before and len(calls)==1


@pytest.mark.parametrize('change',['inactive','scope'])
@pytest.mark.parametrize('resolution',['confirm_existing','bind_order','confirm_not_created'])
def test_post_commit_response_revocation_preserves_one_durable_reconciliation(editor,monkeypatch,change,resolution):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,resolution);observed=[]
    original=sync_recovery.current_response
    action={'confirm_existing':'verify_update','bind_order':'uncertain_bind','confirm_not_created':'uncertain_clear'}[resolution]
    def gate(db,invoice_id,user):
        assert not db.in_transaction()
        with Session(e.ctx.engine) as verify:
            invoice=verify.get(Invoice,e.invoice_id)
            assert invoice.sync_status=='not_synced' and invoice.status=='ready' and invoice.sync_attempt is None
            assert len(verify.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==e.invoice_id,InvoiceSyncLog.action==action)).all())==1
        if change=='scope':demote_admin(e,['invoice:admin'])
        else:
            with Session(e.ctx.engine) as revoke:
                lock_authority(revoke);revoke.get(ArkUser,e.ctx.admin).is_active=False;revoke.commit()
        observed.append(business(e))
        return original(db,invoice_id,user)
    monkeypatch.setattr(sync_recovery,'current_response',gate)
    response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==(403 if change=='inactive' else 404),response.text
    assert len(observed)==1 and business(e)==observed[0] and 'no-store' in response.headers['cache-control']
    assert 'invoice_no' not in response.json() and e.body['customer_name'] not in response.text


def test_real_token_helper_slow_window_is_unlocked_and_rechecks_actor(editor,monkeypatch):
    from app.core.time import utc_now_naive
    e=editor;token_helper=okki_client.ensure_access_token;read_helper=lifecycle_remote.read
    route,body,calls,data=prepare(e,monkeypatch,'confirm_existing');ready=Event();release=Event()
    with Session(e.ctx.engine) as db:
        settings=db.get(XiaomanSettings,1)
        if settings is None:settings=XiaomanSettings(id=1,default_currency='USD');db.add(settings)
        settings.access_token=None;settings.token_expires_at=None;db.commit()
    monkeypatch.setattr(okki_client,'ensure_access_token',token_helper)
    monkeypatch.setattr(lifecycle_remote,'read',read_helper)
    def fetch():ready.set();assert release.wait(8);return 'synthetic-owned-token',utc_now_naive()+timedelta(hours=8)
    requests=[]
    def request(token,kind,identity,*,remove=False):
        assert kind=='order' and str(identity)=='401' and not remove
        requests.append((kind,identity));return deepcopy(data)
    monkeypatch.setattr(okki_client,'fetch_token',fetch);monkeypatch.setattr(lifecycle_remote,'request',request)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);edit_authority.lock_document(db,e.invoice_id)
                db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
            before=business(e);release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==403 and business(e)==before and len(requests)==1
    with Session(e.ctx.engine) as db:assert db.get(XiaomanSettings,1).access_token is None


def test_two_overlapping_existing_captures_only_verify_once(editor,monkeypatch):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,'confirm_existing');first=Event();both=Event();release=Event()
    original=lifecycle_remote.read
    def gate(*args):
        if first.is_set():both.set()
        first.set();assert release.wait(8);return original(*args)
    monkeypatch.setattr(lifecycle_remote,'read',gate)
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
        assert len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==e.invoice_id,InvoiceSyncLog.action=='verify_update')).all())==1
    assert len(calls)==2


@pytest.mark.parametrize('resolution',['bind_order','confirm_not_created'])
def test_local_resolution_actual_lock_wait_proves_single_transition(editor,monkeypatch,resolution):
    from test_mysql_concurrency import wait_for_lock
    e=editor;route,body,calls,_=prepare(e,monkeypatch,resolution)
    ready=Event();release=Event();original_commit=Session.commit
    action='uncertain_bind' if resolution=='bind_order' else 'uncertain_clear'
    def commit(db):
        matching=any(isinstance(row,InvoiceSyncLog) and row.invoice_id==e.invoice_id and row.action==action for row in db.new)
        if matching:
            db.flush()
            invoice=db.get(Invoice,e.invoice_id)
            assert invoice.status=='ready' and invoice.sync_status=='not_synced' and invoice.sync_attempt is None
            ready.set();assert release.wait(8)
        return original_commit(db)
    monkeypatch.setattr(Session,'commit',commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
        try:
            assert ready.wait(6)
            first_ids={e.started.get(timeout=3)}
            while not e.started.empty():first_ids.add(e.started.get_nowait())
            assert len(first_ids)==1  # root/savepoint events belong to the first held connection
            two=pool.submit(asyncio.run,e.write(route,body,'POST',e.admin_token))
            second_id=e.started.get(timeout=3)
            assert second_id not in first_ids
            wait_for_lock(e.ctx.engine,second_id)
            assert not two.done();release.set()
            responses=[one.result(timeout=8),two.result(timeout=8)]
        finally:release.set()
    assert sorted(r.status_code for r in responses)==[200,409],[r.text for r in responses]
    with Session(e.ctx.engine) as db:
        action='uncertain_bind' if resolution=='bind_order' else 'uncertain_clear'
        assert len(db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==e.invoice_id,InvoiceSyncLog.action==action)).all())==1
    assert calls==[]


@pytest.mark.parametrize('fault',['missing','wrong_company','wrong_name'])
def test_bind_requires_matching_actual_owned_mirror(editor,monkeypatch,fault):
    e=editor;route,body,calls,_=prepare(e,monkeypatch,'bind_order')
    with e.ctx.engine.begin() as conn:
        if fault=='missing':conn.execute(text('DELETE FROM okki_orders WHERE order_id=:target'),{'target':body['xiaoman_order_id']})
        else:conn.execute(text("UPDATE okki_orders SET "+('company_id' if fault=='wrong_company' else 'name')+'=:value WHERE order_id=:target'),{'value':'other-object','target':body['xiaoman_order_id']})
    before=business(e);response=asyncio.run(e.write(route,body,'POST',e.admin_token))
    assert response.status_code==409 and business(e)==before and calls==[]
