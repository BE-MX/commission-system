"""Actual employee JWT and HTTP PI editors coordinate with current authorization."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import queue
from threading import Event
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, delete, event, update
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.core.time import beijing_now, beijing_today
from app.invoice import service as invoices, linked_sync_service as linked, edit_authority, okki_client
from app.invoice.models import Invoice, InvoiceItem, InvoiceLinkedSync
from app.receipt import remote
from app.receipt.models import Receipt
from app.portal.authority import lock_authority
from app.portal.models import Publication, PiAmendment
from test_mysql_concurrency import wait_for_lock


@pytest.mark.parametrize('entry',['normal','linked'])
def test_old_real_employee_jwt_cannot_edit_after_committed_disable(editor,entry):
    e=editor;ctx=e.ctx;route,body,method=e.prepare(entry)
    with Session(ctx.engine) as db:
        lock_authority(db);db.get(ArkUser,ctx.actor).is_active=False;db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method))
    assert response.status_code==403
    assert e.snapshot()==baseline


@pytest.mark.parametrize('entry',['normal','linked'])
@pytest.mark.parametrize('commit_revocation',[True,False])
def test_actual_http_editor_waits_for_revocation_commit_or_rollback(editor,entry,commit_revocation):
    e=editor;ctx=e.ctx;route,body,method=e.prepare(entry);baseline=e.snapshot()
    with Session(ctx.engine) as first,ThreadPoolExecutor(max_workers=1) as pool:
        lock_authority(first);first.get(ArkUser,ctx.actor).is_active=False;first.flush()
        future=pool.submit(asyncio.run,e.write(route,body,method))
        try:
            wait_for_lock(ctx.engine,e.started.get(timeout=3));assert not future.done()
            if commit_revocation:first.commit()
            else:first.rollback()
            response=future.result(timeout=8)
        finally:first.rollback()
    assert response.status_code==(403 if commit_revocation else 200)
    if commit_revocation:assert e.snapshot()==baseline
    else:
        with Session(ctx.engine) as db:
            invoice=db.get(Invoice,e.invoice_id);assert invoice.remark==e.body['remark'] and invoice.portal_document_version>e.version
            assert db.scalar(select(Publication).where(Publication.invoice_id==invoice.id)).status=='withdrawn'
            amendment=db.scalar(select(PiAmendment).where(PiAmendment.invoice_id==invoice.id));assert amendment.status=='withdrawn' and amendment.accepted_revision_id is None
            if entry=='linked':assert db.get(InvoiceLinkedSync,invoice.linked_sync_id).status=='pending'


@pytest.mark.parametrize('entry',['normal','linked'])
def test_old_super_admin_claim_does_not_keep_cross_sales_write_scope(editor,entry):
    e=editor;ctx=e.ctx;route,body,method=e.prepare(entry)
    with Session(ctx.engine) as db:
        lock_authority(db)
        super_role=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
        sales_role=db.scalar(select(ArkRole.id).where(ArkRole.name=='sales'))
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==ctx.admin,ArkUserRole.role_id==super_role))
        if db.scalar(select(ArkUserRole.user_id).where(ArkUserRole.user_id==ctx.admin,ArkUserRole.role_id==sales_role)) is None:
            db.add(ArkUserRole(user_id=ctx.admin,role_id=sales_role))
        sync_permission=db.scalar(select(ArkPermission.id).where(ArkPermission.code=='invoice:sync'))
        role=ArkRole(name='scope-'+uuid4().hex[:12],label='Isolated live sync');db.add(role);db.flush()
        db.add_all([ArkUserRole(user_id=ctx.admin,role_id=role.id),ArkRolePermission(role_id=role.id,permission_id=sync_permission)]);db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==404
    assert e.snapshot()==baseline


@pytest.mark.parametrize('entry,role_name',[('normal','sales'),('linked','sales'),('linked','edit')])
def test_real_editor_jwt_cannot_keep_removed_write_or_sync_permission(editor,entry,role_name):
    e=editor;ctx=e.ctx;route,body,method=e.prepare(entry)
    with Session(ctx.engine) as db:
        lock_authority(db)
        candidate=select(ArkRole.id).join(ArkUserRole,ArkUserRole.role_id==ArkRole.id).where(ArkUserRole.user_id==ctx.actor)
        candidate=candidate.where(ArkRole.name=='sales' if role_name=='sales' else ArkRole.name.like('edit-%'))
        role=db.scalar(candidate);assert role is not None
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==ctx.actor,ArkUserRole.role_id==role));db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method))
    assert response.status_code==403 and e.snapshot()==baseline


@pytest.mark.parametrize('entry',['normal','linked'])
def test_actual_http_edit_commits_before_waiting_revocation(editor,entry):
    e=editor;ctx=e.ctx;route,body,method=e.prepare(entry);e.pause.enabled=True;revocation_started=queue.Queue()
    def revoke():
        with Session(ctx.engine) as db:
            revocation_started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            lock_authority(db);db.get(ArkUser,ctx.actor).is_active=False;db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(asyncio.run,e.write(route,body,method))
        try:
            assert e.pause.ready.wait(6)
            second=pool.submit(revoke)
            wait_for_lock(ctx.engine,revocation_started.get(timeout=3));assert not second.done()
            e.pause.release.set();response=first.result(timeout=8);second.result(timeout=8)
        finally:e.pause.release.set()
    assert response.status_code==200
    with Session(ctx.engine) as db:
        invoice=db.get(Invoice,e.invoice_id);assert invoice.remark==e.body['remark'] and invoice.portal_document_version>e.version
        assert db.scalar(select(Publication).where(Publication.invoice_id==invoice.id)).status=='withdrawn'
        assert not db.get(ArkUser,ctx.actor).is_active
    baseline=e.snapshot();e.pause.enabled=False
    replay=asyncio.run(e.write(route,body,method))
    assert replay.status_code==403 and e.snapshot()==baseline


def synced_editor(e, entry):
    route, body, method = e.prepare(entry)
    if entry == 'normal':
        with Session(e.ctx.engine) as db:
            invoice = invoices.get_invoice(db, e.invoice_id)
            invoice.xiaoman_order_id = 'isolated-' + uuid4().hex
            invoice.sync_status = 'synced'
            db.commit()
    return route, body, method


def local_operation(e, action, *, lease=False):
    route, body, method = synced_editor(e, 'linked')
    response = asyncio.run(e.write(route, body, method))
    assert response.status_code == 200
    identity = response.json()['data']['operation']['id']
    with Session(e.ctx.engine) as db:
        row = db.get(InvoiceLinkedSync, identity)
        row.status = 'failed' if action == 'close' else 'uncertain'
        row.run_token = uuid4().hex if action == 'resolve' else None
        row.lease_until = beijing_now() + timedelta(minutes=2) if lease else beijing_now() - timedelta(seconds=1)
        db.commit()
    return (f'/api/invoice/invoices/{e.invoice_id}/linked-sync/{identity}/{action}',
        {} if action == 'close' else {'confirmed':True,'reason':'Independently checked original order, outbound and receipts'},
        'POST', identity)


@pytest.mark.parametrize('entry', ['normal', 'linked'])
@pytest.mark.parametrize('change', ['none', 'disable', 'scope', 'document', 'raw_line', 'remote_id', 'task_lease', 'receipt'])
def test_remote_preflight_releases_locks_and_rechecks_current_state(editor, monkeypatch, entry, change):
    e = editor; route, body, method = synced_editor(e, entry)
    if change == 'task_lease':
        with Session(e.ctx.engine) as db:
            invoice = invoices.get_invoice(db, e.invoice_id)
            row = InvoiceLinkedSync(id=uuid4().hex, invoice_id=invoice.id, request_key=uuid4().hex,
                request_hash='a'*64, created_by=e.ctx.actor, status='failed', before={}, after={},
                steps={k:{'status':'pending'} for k in ('order','outbound','receipt')})
            db.add(row); invoice.linked_sync_id = row.id; db.commit()
    if change == 'receipt' and entry == 'normal':
        body['shipping_fee'] = '0.00'
    ready, release, calls = Event(), Event(), []
    def read_receipts(db, order_id):
        assert not db.in_transaction(), 'Remote I/O must start after capture transaction has ended'
        calls.append(order_id); ready.set(); assert release.wait(8)
        return []
    monkeypatch.setattr(remote, 'order_receipts', read_receipts)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, e.write(route, body, method,e.admin_token if change=='scope' else e.token))
        try:
            assert ready.wait(6)
            with Session(e.ctx.engine) as db:
                # An actual independent connection must acquire both locks while
                # the first request is still paused at the external boundary.
                db.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
                lock_authority(db)
                invoice = edit_authority.lock_document(db, e.invoice_id)
                if change == 'disable': db.get(ArkUser, e.ctx.actor).is_active = False
                elif change == 'scope':
                    super_role=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
                    sales_role=db.scalar(select(ArkRole.id).where(ArkRole.name=='sales'))
                    db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==e.ctx.admin,ArkUserRole.role_id==super_role))
                    if db.scalar(select(ArkUserRole.user_id).where(ArkUserRole.user_id==e.ctx.admin,ArkUserRole.role_id==sales_role)) is None:
                        db.add(ArkUserRole(user_id=e.ctx.admin,role_id=sales_role))
                    sync_permission=db.scalar(select(ArkPermission.id).where(ArkPermission.code=='invoice:sync'))
                    role=ArkRole(name='scope-inline-'+uuid4().hex[:8],label='Keep action, revoke global scope')
                    db.add(role);db.flush()
                    db.add_all([ArkUserRole(user_id=e.ctx.admin,role_id=role.id),ArkRolePermission(role_id=role.id,permission_id=sync_permission)])
                elif change == 'document': invoice.remark = 'Concurrent commercial edit must survive'
                elif change == 'raw_line':
                    # Deliberately bypass the ORM protocol in this isolated test:
                    # legacy hash must still detect changed rows without a version bump.
                    db.execute(update(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id)
                        .values(price_per_piece=InvoiceItem.price_per_piece+1,total_price=InvoiceItem.total_price+InvoiceItem.quantity))
                    assert invoice.portal_document_version == e.version
                elif change == 'remote_id': invoice.xiaoman_order_id = 'changed-' + uuid4().hex
                elif change == 'task_lease':
                    task = db.get(InvoiceLinkedSync, invoice.linked_sync_id)
                    task.run_token = uuid4().hex; task.lease_until = beijing_now() + timedelta(minutes=2)
                elif change == 'receipt':
                    db.add(Receipt(receipt_no='LOCAL-'+uuid4().hex, invoice_id=invoice.id, source='manual',
                        request_key=uuid4().hex, request_hash='b'*64, amount=invoice.total_amount,
                        currency=invoice.currency, collection_date=beijing_today(), payment_type='transfer',
                        customer_id=invoice.customer_id, xiaoman_order_id=invoice.xiaoman_order_id,
                        sync_status='synced' if entry == 'normal' else 'syncing', created_by=e.ctx.actor))
                db.commit()
            baseline = e.snapshot(); assert not future.done()
            release.set(); response = future.result(timeout=8)
        finally: release.set()
    expected = 200 if change == 'none' else 403 if change == 'disable' else 404 if change=='scope' else 400 if change == 'receipt' and entry == 'normal' else 409
    assert response.status_code == expected, response.text
    assert len(calls) == 1, 'Final protected write must reuse verified rows without more network I/O'
    if change != 'none': assert e.snapshot() == baseline
    if change in {'document','raw_line','remote_id','task_lease'}:
        assert response.json()['detail'] == '发票在回款核对期间已变化，请重新读取后编辑'
    if change == 'none':
        with Session(e.ctx.engine) as db:
            invoice = db.get(Invoice,e.invoice_id)
            assert invoice.remark == e.body['remark'] and invoice.portal_document_version > e.version
            assert db.scalar(select(Publication).where(Publication.invoice_id==invoice.id)).status == 'withdrawn'


@pytest.mark.parametrize('entry', ['normal','linked'])
@pytest.mark.parametrize('failure', ['value','api','incomplete'])
def test_remote_preflight_unavailable_never_becomes_empty_receipt_evidence(editor,monkeypatch,entry,failure):
    e=editor;route,body,method=synced_editor(e,entry);baseline=e.snapshot();calls=[]
    def unavailable(db, order_id):
        assert not db.in_transaction();calls.append(order_id)
        if failure=='incomplete':return None
        error=ValueError if failure=='value' else okki_client.OkkiApiError
        raise error('PRIVATE_UPSTREAM_PAYLOAD_WITH_SECRET')
    monkeypatch.setattr(remote,'order_receipts',unavailable)
    response=asyncio.run(e.write(route,body,method))
    assert response.status_code==503 and 'PRIVATE_UPSTREAM' not in response.text
    assert len(calls)==1 and e.snapshot()==baseline


@pytest.mark.parametrize('entry',['normal','linked'])
def test_actual_http_editor_locks_portal_lineage_before_invoice(editor,entry):
    e=editor;route,body,method=e.prepare(entry);locks=[]
    def observe(conn,cursor,statement,params,context,many):
        if 'FOR UPDATE' in statement.upper():locks.append(statement)
    event.listen(e.ctx.engine,'before_cursor_execute',observe)
    try:response=asyncio.run(e.write(route,body,method))
    finally:event.remove(e.ctx.engine,'before_cursor_execute',observe)
    assert response.status_code==200,response.text
    indices=[next(i for i,s in enumerate(locks) if ('FROM '+name) in s) for name in
        ('ark_order_portal_requests','ark_order_portal_conversions','ark_invoices')]
    assert indices==sorted(indices) and len(set(indices))==3,locks


@pytest.mark.parametrize('prior_write',['dirty','flushed','core'])
def test_capture_refuses_to_commit_callers_pending_business_changes(editor,prior_write):
    e=editor
    with Session(e.ctx.engine) as db:
        if prior_write=='core':
            db.execute(update(ArkUser).where(ArkUser.id==e.ctx.actor).values(is_active=False))
        else:
            user=db.get(ArkUser,e.ctx.actor);user.is_active=False
            if prior_write=='flushed':db.flush()
        if prior_write!='dirty':assert not (db.new or db.dirty or db.deleted)
        with pytest.raises(HTTPException) as caught:
            edit_authority.prepare(db,e.invoice_id,{'sub':str(e.ctx.actor)},'invoice:write')
        assert getattr(caught.value,'status_code',None)==409
        db.rollback()
    with Session(e.ctx.engine) as db:assert db.get(ArkUser,e.ctx.actor).is_active


@pytest.mark.parametrize('action',['close','resolve'])
@pytest.mark.parametrize('change',['disable','permission'])
def test_real_old_jwt_cannot_locally_recover_after_revocation(editor,monkeypatch,action,change):
    e=editor;route,body,method,identity=local_operation(e,action)
    actor=e.ctx.actor if action=='close' else e.ctx.admin
    token=e.token if action=='close' else e.admin_token
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        if change=='disable':db.get(ArkUser,actor).is_active=False
        else:
            candidate=select(ArkRole.id).join(ArkUserRole,ArkUserRole.role_id==ArkRole.id).where(ArkUserRole.user_id==actor)
            candidate=candidate.where(ArkRole.name.like('edit-%') if action=='close' else ArkRole.name=='super_admin')
            role=db.scalar(candidate);assert role is not None
            db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==actor,ArkUserRole.role_id==role))
        db.commit()
    def forbidden(*args):raise AssertionError('Local recovery must not contact the remote system')
    monkeypatch.setattr(remote,'order_receipts',forbidden)
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method,token))
    assert response.status_code==403 and e.snapshot()==baseline


@pytest.mark.parametrize('action',['close','resolve'])
def test_authorized_local_recovery_preserves_commercial_document(editor,monkeypatch,action):
    e=editor;route,body,method,identity=local_operation(e,action)
    token=e.token if action=='close' else e.admin_token
    def forbidden(*args):raise AssertionError('Local recovery must not contact the remote system')
    monkeypatch.setattr(remote,'order_receipts',forbidden)
    with Session(e.ctx.engine) as db:
        invoice=invoices.get_invoice(db,e.invoice_id)
        commercial=(invoice.portal_document_version,linked.edit_version(invoice),invoice.xiaoman_order_id,invoice.sync_status)
    response=asyncio.run(e.write(route,body,method,token));assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=invoices.get_invoice(db,e.invoice_id);row=db.get(InvoiceLinkedSync,identity)
        assert row.status=='manual' and invoice.linked_sync_id is None
        assert (invoice.portal_document_version,linked.edit_version(invoice),invoice.xiaoman_order_id,invoice.sync_status)==commercial
        assert db.scalar(select(Publication).where(Publication.invoice_id==invoice.id)).status=='withdrawn'
        if action=='resolve':
            assert row.run_token is None and row.lease_until is None
            assert row.steps['resolution']['operator_id']==e.ctx.admin


def test_manual_recovery_keeps_live_runner_lease_locked(editor,monkeypatch):
    e=editor;route,body,method,identity=local_operation(e,'resolve',lease=True);baseline=e.snapshot()
    def forbidden(*args):raise AssertionError('Local recovery must not contact the remote system')
    monkeypatch.setattr(remote,'order_receipts',forbidden)
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==409 and e.snapshot()==baseline


@pytest.mark.parametrize('mode',['replay','binding','different','revoked'])
def test_linked_original_command_survives_lost_response_and_remote_outage(editor,monkeypatch,mode):
    e=editor;route,body,method=synced_editor(e,'linked')
    with pytest.raises(httpx.ReadError):
        asyncio.run(e.write(route,body,method,drop_success=True))
    with Session(e.ctx.engine) as db:
        row=db.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.request_key==body['request_key']))
        assert row is not None
        identity=row.id
    if mode in {'binding','revoked'}:
      with Session(e.ctx.engine) as db:
        lock_authority(db)
        if mode=='binding':
            invoice=edit_authority.lock_document(db,e.invoice_id)
            row=db.get(InvoiceLinkedSync,identity)
            invoice.xiaoman_order_id='rebound-'+uuid4().hex
            row.status='running';row.run_token=uuid4().hex;row.lease_until=beijing_now()+timedelta(minutes=2)
            db.commit()
        elif mode=='revoked':
            db.get(ArkUser,e.ctx.actor).is_active=False;db.commit()
    calls=[]
    def outage(*args):
        calls.append(True);raise ValueError('PRIVATE_REMOTE_OUTAGE')
    monkeypatch.setattr(remote,'order_receipts',outage)
    baseline=e.snapshot();retry=deepcopy(body)
    if mode=='different':retry['invoice']['remark']='Different payload cannot reuse original command'
    response=asyncio.run(e.write(route,retry,method))
    assert response.status_code==(403 if mode=='revoked' else 409 if mode=='different' else 200),response.text
    assert calls==[] and e.snapshot()==baseline
    if response.status_code==200:assert response.json()['data']['operation']['id']==identity


@pytest.mark.parametrize('action',['close','resolve'])
def test_demoted_old_admin_cannot_recover_foreign_invoice_with_current_action_permission(editor,monkeypatch,action):
    e=editor;route,body,method,identity=local_operation(e,action)
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        super_role=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==e.ctx.admin,ArkUserRole.role_id==super_role))
        code='invoice:sync' if action=='close' else 'invoice:admin'
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
        if permission is None:
            permission=ArkPermission(code=code,module='invoice',action=code.split(':')[1],label='Isolated recovery',kind='action',is_legacy=False,sort=1)
            db.add(permission);db.flush()
        role=ArkRole(name='recover-scope-'+uuid4().hex[:8],label='Action without global scope');db.add(role);db.flush()
        db.add_all([ArkUserRole(user_id=e.ctx.admin,role_id=role.id),ArkRolePermission(role_id=role.id,permission_id=permission.id)]);db.commit()
    def forbidden(*args):raise AssertionError('Local recovery must not contact remote systems')
    monkeypatch.setattr(remote,'order_receipts',forbidden)
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==404 and e.snapshot()==baseline


def test_concurrent_identical_linked_commands_replay_after_both_remote_preflights(editor,monkeypatch):
    e=editor;route,body,method=synced_editor(e,'linked')
    ready=[Event(),Event()];release=[Event(),Event()];calls=[]
    def read_receipts(db,order_id):
        assert not db.in_transaction()
        index=len(calls);calls.append(order_id)
        assert index < 2,'Final write must not perform another remote read'
        ready[index].set();assert release[index].wait(8)
        return []
    monkeypatch.setattr(remote,'order_receipts',read_receipts)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(asyncio.run,e.write(route,body,method))
        try:
            assert ready[0].wait(6)
            second=pool.submit(asyncio.run,e.write(route,deepcopy(body),method))
            assert ready[1].wait(6)
            assert not first.done() and not second.done()
            release[0].set();one=first.result(timeout=8)
            assert one.status_code==200,one.text
            baseline=e.snapshot()
            release[1].set();two=second.result(timeout=8)
        finally:
            for gate in release:gate.set()
    assert two.status_code==200,two.text
    assert one.json()['data']['operation']['id']==two.json()['data']['operation']['id']
    assert len(calls)==2 and e.snapshot()==baseline
    with Session(e.ctx.engine) as db:
        assert len(db.scalars(select(InvoiceLinkedSync).where(InvoiceLinkedSync.request_key==body['request_key'])).all())==1
        invoice=db.get(Invoice,e.invoice_id)
        assert invoice.remark==e.body['remark'] and invoice.portal_document_version>e.version
