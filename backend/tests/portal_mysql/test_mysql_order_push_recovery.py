"""Original push facts, safe manual reconciliation, collection races and commit faults."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from threading import Event

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, String, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.invoice import edit_authority, lifecycle_remote, okki_client, order_push_facts as facts
from app.invoice.models import Invoice, InvoiceItem, InvoiceSyncLog
from app.portal.authority import lock_authority, get_settings
from app.receipt.models import ReceiptIntent
from test_mysql_order_push_execution import setup_push, execute, audit, business


def capture_attempt(c, monkeypatch):
    original=facts.start
    def start(*args,**kwargs):
        attempt=original(*args,**kwargs);c.attempt=attempt;return attempt
    monkeypatch.setattr(facts,'start',start)


def accepted_after_expiry(c,monkeypatch,*,review_before=False):
    capture_attempt(c,monkeypatch)
    def post(url,**kwargs):
        with Session(c.e.ctx.engine) as db:
            lock_authority(db);invoice=edit_authority.lock_document(db,c.e.invoice_id)
            invoice.sync_attempt={**invoice.sync_attempt,'lease_until':(beijing_now()-timedelta(minutes=1)).isoformat()}
            intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
            intent.lease_until=beijing_now()-timedelta(minutes=1)
            db.commit()
        if review_before:
            # Actual HTTP/manual clear while POST is still unresolved and its lease has expired.
            response=recover(c,review_before if isinstance(review_before,str) else 'confirm_not_created',c.target if review_before=='bind_order' else None)
            assert response.status_code==200,response.text
        return c.post(url,**kwargs)
    monkeypatch.setattr(okki_client.httpx,'post',post)
    response=execute(c);assert response.status_code==200 and response.json()['data']['execution_changed'],response.text


def mirror(c):
    metadata=MetaData();table=Table('okki_orders',metadata,Column('order_id',String(64),primary_key=True),
        Column('order_no',String(64)),Column('name',String(200)),Column('company_id',String(64)))
    metadata.create_all(c.e.ctx.engine)
    with Session(c.e.ctx.engine) as db:
        invoice=db.get(Invoice,c.e.invoice_id)
        db.execute(table.insert().values(order_id=c.target,order_no='OWN-'+c.target,name=invoice.invoice_no,company_id=invoice.customer_id));db.commit()


def recover(c,resolution,target=None):
    return asyncio.run(c.e.write(f'/api/invoice/invoices/{c.e.invoice_id}/sync-uncertain/resolve',
        {'resolution':resolution,'reason':'Reviewed original accepted order and all commercial evidence',
         'xiaoman_order_id':target},'POST',c.e.admin_token))


def read_evidence(c):
    with Session(c.e.ctx.engine) as db:
        invoice=db.get(Invoice,c.e.invoice_id)
        return {**c.accepted(c.posts[0]),'company_id':str(invoice.customer_id),'currency':invoice.currency,
                'amount':str(invoice.total_amount-(invoice.surcharge_amount or 0))}


@pytest.mark.parametrize('resolution',['confirm_not_created','bind_order'])
def test_known_accepted_fact_cannot_be_cleared_or_bound_elsewhere(editor,monkeypatch,tmp_path,resolution):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch)
    before=business(e);response=recover(c,resolution,'1234' if resolution=='bind_order' else None)
    assert response.status_code==409 and business(e)==before and len(c.posts)==1,response.text
    assert not [row for row in audit(e) if row[0]==facts.REVIEW]


def test_original_known_acceptance_bind_uses_actual_projection_without_post(editor,monkeypatch,tmp_path):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch);mirror(c)
    response=recover(c,'bind_order',c.target);assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        assert invoice.xiaoman_order_id==c.target and invoice.sync_attempt is None and facts.unresolved(db,invoice)==[]
    assert len(c.posts)==1 and len([r for r in audit(e) if r[0]==facts.REVIEW])==1


def test_resetting_mutable_attempt_does_not_bypass_unresolved_start(editor,monkeypatch,tmp_path):
    e=editor;c=setup_push(e,monkeypatch,tmp_path)
    def post(url,**kwargs):c.posts.append(deepcopy(kwargs['json']));raise httpx.ReadTimeout('synthetic unknown')
    monkeypatch.setattr(okki_client.httpx,'post',post)
    assert execute(c).status_code==200
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.sync_attempt=None;invoice.status='ready';invoice.sync_status='not_synced';db.commit()
    before=business(e);response=execute(c)
    assert response.status_code==409 and business(e)==before and len(c.posts)==1,response.text


@pytest.mark.parametrize('bound',[False,True])
def test_late_fact_after_review_can_be_reconciled_again_without_post(editor,monkeypatch,tmp_path,bound):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);mirror(c)
    accepted_after_expiry(c,monkeypatch,review_before='bind_order' if bound else 'confirm_not_created')
    evidence=read_evidence(c);calls=[]
    monkeypatch.setattr(lifecycle_remote,'read',lambda *a:calls.append(a[1:]) or deepcopy(evidence))
    with Session(e.ctx.engine) as db:
        before_intent=tuple(db.execute(select(*ReceiptIntent.__table__.columns).where(ReceiptIntent.invoice_id==e.invoice_id)).one())
    response=recover(c,'confirm_existing' if bound else 'bind_order',None if bound else c.target)
    assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id)
        assert invoice.xiaoman_order_id==c.target and invoice.status=='ready' and invoice.sync_status=='not_synced'
        assert invoice.sync_attempt is None and facts.unresolved(db,invoice)==[]
        assert invoice.items[0].xiaoman_unique_id=='501'
        from app.invoice import xiaoman_service
        assert xiaoman_service.build_push_payload(db,invoice)[0]['product_list'][0]['unique_id']==501
        assert tuple(db.execute(select(*ReceiptIntent.__table__.columns).where(ReceiptIntent.invoice_id==e.invoice_id)).one())==before_intent
        assert db.scalar(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==invoice.id,InvoiceSyncLog.action=='push_fact_review'))
    assert len(c.posts)==1 and len(calls)==1 and len([r for r in audit(e) if r[0]==facts.REVIEW])==2


@pytest.mark.parametrize('late',[False,True])
def test_new_fact_during_get_cannot_be_marked_reviewed_by_old_observation(editor,monkeypatch,tmp_path,late):
    e=editor;c=setup_push(e,monkeypatch,tmp_path)
    accepted_after_expiry(c,monkeypatch,review_before=late);mirror(c)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.xiaoman_order_id=c.target;db.commit()
    evidence=read_evidence(c);ready=Event();release=Event()
    def read(*args):ready.set();assert release.wait(8);return deepcopy(evidence)
    monkeypatch.setattr(lifecycle_remote,'read',read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(recover,c,'confirm_existing')
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                extra=facts.observation(c.attempt,2,'accepted',c.target,{'synthetic':'new fact during GET'})
                facts.record(db,c.attempt,extra)
                db.commit()
            before=business(e);release.set();response=pending.result(timeout=10)
        finally:release.set()
    assert response.status_code==409 and business(e)==before and len(c.posts)==1,response.text


@pytest.mark.parametrize('change',['inactive','amount','receipt_lease'])
def test_late_recovery_rechecks_authority_binding_and_receipt_execution(editor,monkeypatch,tmp_path,change):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch);mirror(c)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.sync_attempt=None;invoice.status='ready';invoice.sync_status='not_synced';db.commit()
    evidence=read_evidence(c);ready=Event();release=Event()
    def read(*args):ready.set();assert release.wait(8);return deepcopy(evidence)
    monkeypatch.setattr(lifecycle_remote,'read',read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(recover,c,'bind_order',c.target)
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='amount':db.execute(update(Invoice).where(Invoice.id==invoice.id).values(total_amount=invoice.total_amount+1))
                else:db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).lease_until=beijing_now()+timedelta(minutes=1)
                db.commit()
            before=business(e);release.set();response=pending.result(timeout=10)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 409) and business(e)==before,response.text


@pytest.mark.parametrize('field',['actor_id','inventory_key','receipt_token','token'])
def test_forged_runtime_attempt_cannot_append_facts(editor,monkeypatch,tmp_path,field):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch)
    forged=replace(c.attempt,**{field:999999 if field=='actor_id' else 'forged'})
    before=business(e)
    with Session(e.ctx.engine) as db:
        with pytest.raises(HTTPException) as error:facts.record(db,forged,facts.observation(forged,2,'accepted',c.target))
        assert error.value.status_code==409;db.rollback()
    assert business(e)==before


@pytest.mark.parametrize('stage',['fact','business'])
def test_bounded_save_failure_keeps_original_claim_and_never_resends(editor,monkeypatch,tmp_path,stage):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);original=Session.commit;hits=[]
    def commit(db):
        if c.posts and db.get_bind() is e.ctx.engine:
            object_id,_=facts.object_binding(db,e.invoice_id)
            actions=set(db.scalars(select(facts.AuditEvent.action).where(facts.AuditEvent.object_public_id==object_id)).all())
            if (stage=='fact' and facts.FACT in actions and facts.FINISH not in actions
                    or stage=='business' and facts.FINISH in actions):
                hits.append(stage);raise OperationalError('synthetic unavailable commit',{},RuntimeError('owned fault'))
        return original(db)
    monkeypatch.setattr(Session,'commit',commit)
    response=execute(c);assert response.status_code==503 and hits==[stage]*3 and len(c.posts)==1,response.text
    rows=audit(e);assert bool([r for r in rows if r[0]==facts.FACT])==(stage=='business')
    before=business(e);repeat=execute(c)
    assert repeat.status_code==409 and business(e)==before and len(c.posts)==1


@pytest.mark.parametrize('state',['draft','active_receipt_lease'])
def test_late_recovery_rejects_invalid_current_state_before_get(editor,monkeypatch,tmp_path,state):
    e=editor;c=setup_push(e,monkeypatch,tmp_path);accepted_after_expiry(c,monkeypatch,review_before=True);mirror(c)
    calls=[];monkeypatch.setattr(lifecycle_remote,'read',lambda *a:calls.append(a) or read_evidence(c))
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        if state=='draft':invoice.status='draft'
        else:db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).lease_until=beijing_now()+timedelta(minutes=1)
        db.commit()
    before=business(e);response=recover(c,'bind_order',c.target)
    assert response.status_code==409 and business(e)==before and calls==[] and len(c.posts)==1,response.text
