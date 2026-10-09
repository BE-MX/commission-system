"""Actual JWT, independent locks and current financial evidence for reconciliation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select, delete, text
from sqlalchemy.orm import Session
from app.auth.models import ArkUser, ArkUserRole, ArkRole, ArkPermission, ArkRolePermission
from app.core.time import beijing_now
from app.invoice import edit_authority, lifecycle_remote, linked_outbound_service, okki_client, service as invoices
from app.invoice.models import Invoice
from app.portal.authority import lock_authority
from app.receipt import remote
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from test_mysql_invoice_lifecycle_authority import lifecycle_case, forbid_remote


def setup_refresh(e, monkeypatch, *, missing=False):
    route, body, method = lifecycle_case(e, 'begin')
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    monkeypatch.setattr(lifecycle_remote,'read',lambda *a:None if missing else
        {'company_id':e.body['customer_id'],'currency':'USD','status':'draft'})
    monkeypatch.setattr(linked_outbound_service,'find_related',lambda *a:[])
    monkeypatch.setattr(remote,'order_receipts',lambda *a:[])
    return route,{**body,'action':'refresh'},method


def uncertain(e):
    with Session(e.ctx.engine) as db:
        lock_authority(db);row=edit_authority.lock_document(db,e.invoice_id)
        row.cancellation={**row.cancellation,'status':'uncertain','token':uuid4().hex,
            'lease_until':(beijing_now()-timedelta(seconds=5)).isoformat()};db.commit()


@pytest.mark.parametrize('method',['POST','GET'])
def test_stopped_real_admin_cannot_reconcile_or_read_lifecycle(editor,monkeypatch,method):
    e=editor;route,body,_=setup_refresh(e,monkeypatch)
    with Session(e.ctx.engine) as db:
        lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    forbid_remote(monkeypatch);before=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==403,response.text
    assert e.snapshot()==before


@pytest.mark.parametrize('phase',['order','outbounds','receipts'])
@pytest.mark.parametrize('change',['inactive','document','binding','token'])
def test_refresh_releases_locks_and_rechecks_exact_current_binding(editor,monkeypatch,phase,change):
    e=editor;route,body,method=setup_refresh(e,monkeypatch);ready=Event();release=Event()
    module,name={'order':(lifecycle_remote,'read'),'outbounds':(linked_outbound_service,'find_related'),
        'receipts':(remote,'order_receipts')}[phase]
    original=getattr(module,name)
    def gate(*args,**kwargs):
        ready.set();assert release.wait(8);return original(*args,**kwargs)
    monkeypatch.setattr(module,name,gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if change=='inactive':db.get(ArkUser,e.ctx.admin).is_active=False
                elif change=='document':invoice.remark='Another committed commercial edit'
                elif change=='binding':invoice.xiaoman_order_id='different-order'
                else:invoice.cancellation={**invoice.cancellation,'token':uuid4().hex}
                db.commit()
            before=e.snapshot();release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==(403 if change=='inactive' else 409),response.text
    assert e.snapshot()==before


@pytest.mark.parametrize('kind',['receipt','intent','allocation','pending_delta'])
def test_refresh_missing_remote_rechecks_concurrent_local_blockers(editor,monkeypatch,kind):
    e=editor;route,body,method=setup_refresh(e,monkeypatch,missing=True);uncertain(e)
    ready=Event();release=Event()
    def gate(*args):ready.set();assert release.wait(8);return []
    monkeypatch.setattr(remote,'order_receipts',gate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
                if kind=='receipt':
                    db.add(Receipt(receipt_no='R-'+uuid4().hex[:10],invoice_id=invoice.id,source='manual',
                        request_key=uuid4().hex,request_hash='a'*64,amount=1,currency='USD',
                        collection_date=invoice.invoice_date,payment_type='T/T',bank_charge=0,customer_id=invoice.customer_id,
                        xiaoman_order_id=invoice.xiaoman_order_id,sync_status='pending',created_by=e.ctx.actor,status='active'))
                elif kind=='intent':
                    db.add(ReceiptIntent(invoice_id=invoice.id,eligible=1,created_by=e.ctx.actor,attachment_ids=[],status='armed'))
                else:
                    db.add(InvoiceAllocation(invoice_id=invoice.id,material_id=123,status='allocated',
                        allocated_qty_grams=1 if kind=='allocation' else 0,pending_delta_grams=1 if kind=='pending_delta' else 0))
                db.commit()
            release.set();response=pending.result(timeout=8)
        finally:release.set()
    assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id)
        assert invoice.status=='cancel_pending' and invoice.cancellation['status']=='uncertain'
        assert invoice.cancellation['evidence']['blockers']
        assert invoice.cancellation['evidence']['local_receipt_count']==(1 if kind=='receipt' else 0)


@pytest.mark.parametrize('fault',['value','api','nonlist'])
def test_reconciliation_bad_remote_evidence_is_safe_and_writes_nothing(editor,monkeypatch,fault):
    e=editor;route,body,method=setup_refresh(e,monkeypatch)
    def fail(*args):
        if fault=='nonlist':return None
        raise (ValueError if fault=='value' else okki_client.OkkiApiError)('PRIVATE-UPSTREAM-CONTENT')
    monkeypatch.setattr(remote,'order_receipts',fail);before=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==503,response.text
    assert 'PRIVATE-UPSTREAM-CONTENT' not in response.text and e.snapshot()==before


@pytest.mark.parametrize('status',['pending','uncertain'])
def test_authorized_refresh_does_not_treat_unattempted_absence_as_delete(editor,monkeypatch,status):
    e=editor;route,body,method=setup_refresh(e,monkeypatch,missing=True)
    if status=='uncertain':uncertain(e)
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id)
        assert invoice.cancellation['status']==('pending' if status=='pending' else 'remote_deleted')
        assert invoice.status==('cancel_pending' if status=='pending' else 'cancelled')


def test_live_delete_lease_refresh_does_not_take_external_evidence(editor,monkeypatch):
    e=editor;route,body,method=setup_refresh(e,monkeypatch)
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.cancellation={**invoice.cancellation,'status':'deleting','token':uuid4().hex,
            'lease_until':(beijing_now()+timedelta(minutes=2)).isoformat()};db.commit()
    forbid_remote(monkeypatch);before=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==200,response.text
    assert e.snapshot()==before


@pytest.mark.parametrize('helper',['local','edit'])
def test_committed_expire_false_cache_cannot_restore_stale_invoice(editor,helper):
    e=editor
    with Session(e.ctx.engine,expire_on_commit=False) as db:
        cached=invoices.get_invoice(db,e.invoice_id);old=cached.portal_document_version;db.commit()
        with Session(e.ctx.engine) as writer:
            lock_authority(writer);current=edit_authority.lock_document(writer,e.invoice_id)
            current.remark='New committed version';writer.commit();new_version=current.portal_document_version
        assert cached.portal_document_version==old and new_version>old
        user={'sub':str(e.ctx.admin),'roles':['super_admin'],'permissions':[]}
        prepared=getattr(edit_authority,'prepare_local' if helper=='local' else 'prepare')(db,e.invoice_id,user,'invoice:write')[0]
        assert prepared is cached and prepared.portal_document_version==new_version
        assert prepared.remark=='New committed version';db.rollback()


def demote_admin(e,codes):
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        root=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==e.ctx.admin,ArkUserRole.role_id==root))
        role=ArkRole(name='limited-'+uuid4().hex[:12],label='Isolated live role');db.add(role);db.flush()
        db.add(ArkUserRole(user_id=e.ctx.admin,role_id=role.id))
        for code in codes:
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                permission=ArkPermission(code=code,module='invoice',action=code.split(':')[1],label='Isolated action',
                    kind='data' if code.endswith('read_all') else 'action',is_legacy=False,sort=1)
                db.add(permission);db.flush()
            db.add(ArkRolePermission(role_id=role.id,permission_id=permission.id))
        db.commit()


@pytest.mark.parametrize('method',['POST','GET'])
@pytest.mark.parametrize('scope',['removed','admin_without_global'])
def test_reconcile_and_read_do_not_keep_old_role_or_global_scope(editor,monkeypatch,method,scope):
    e=editor;route,body,_=setup_refresh(e,monkeypatch)
    demote_admin(e,[] if scope=='removed' else ['invoice:admin']);forbid_remote(monkeypatch);before=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==(403 if scope=='removed' else 404),response.text
    assert e.snapshot()==before


@pytest.mark.parametrize('state',['retained','remote_deleted','aborted'])
def test_terminal_refresh_does_not_read_remote_or_restore_publication(editor,monkeypatch,state):
    e=editor;route,body,method=setup_refresh(e,monkeypatch)
    if state in {'retained','aborted'}:
        response=asyncio.run(e.write(route,{**body,'action':'retain' if state=='retained' else 'abort'},method,e.admin_token))
        assert response.status_code==200,response.text
    else:
        with Session(e.ctx.engine) as db:
            lock_authority(db);row=edit_authority.lock_document(db,e.invoice_id)
            row.status='cancelled';row.cancellation={**row.cancellation,'status':state};db.commit()
    forbid_remote(monkeypatch);before=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==(409 if state=='aborted' else 200),response.text
    assert e.snapshot()==before


@pytest.mark.parametrize('endpoint',['validate','delete'])
@pytest.mark.parametrize('capability',['read_all_only','write_without_scope'])
def test_validate_and_delete_separate_current_action_from_scope(editor,endpoint,capability):
    e=editor;demote_admin(e,['invoice:read_all'] if capability=='read_all_only' else ['invoice:write'])
    route=f'/api/invoice/invoices/{e.invoice_id}'+('/validate' if endpoint=='validate' else '')
    before=e.snapshot();response=asyncio.run(e.write(route,{},'POST' if endpoint=='validate' else 'DELETE',e.admin_token))
    assert response.status_code==(403 if capability=='read_all_only' else 404),response.text
    assert e.snapshot()==before
