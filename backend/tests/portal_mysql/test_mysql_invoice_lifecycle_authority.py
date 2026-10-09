"""Real employee JWT and transaction ordering for local invoice lifecycle writes."""
import asyncio
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import queue
from uuid import uuid4

import pytest
from sqlalchemy import select, delete, text, event
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole, ArkUserRole, ArkPermission, ArkRolePermission
from app.invoice import edit_authority, lifecycle_remote, okki_client, service as invoices, linked_sync_service as linked
from app.invoice.schemas import InvoiceCreate
from app.core.time import beijing_now
from datetime import timedelta
from app.invoice.models import Invoice, InvoiceItem, InvoiceSyncLog
from app.portal.authority import lock_authority
from app.portal.models import Publication, PiAmendment
from app.receipt import remote
from test_mysql_concurrency import wait_for_lock


def lifecycle_case(e,action):
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.xiaoman_order_id='isolated-'+uuid4().hex
        invoice.sync_status='synced';db.commit()
        expected=linked.edit_version(invoice)
    route=f'/api/invoice/invoices/{e.invoice_id}/lifecycle'
    body={'action':action,'confirmed':True,'expected_version':expected,
        'reason':'Reviewed the original order and cancellation consequences'}
    if action!='begin':
        response=asyncio.run(e.write(route,{**body,'action':'begin'},'POST',e.admin_token))
        assert response.status_code==200,response.text
    while not e.started.empty():e.started.get_nowait()
    return route,body,'POST'


@pytest.mark.parametrize('action',['begin','retain','abort'])
def test_inactive_real_admin_jwt_cannot_change_portal_invoice_lifecycle(editor,action):
    e=editor;route,body,method=lifecycle_case(e,action)
    with Session(e.ctx.engine) as db:
        lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    baseline=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==403,response.text
    assert e.snapshot()==baseline


@pytest.mark.parametrize('action',['begin','retain','abort'])
def test_removed_admin_role_cannot_keep_old_lifecycle_permission(editor,action):
    e=editor;route,body,method=lifecycle_case(e,action)
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        role=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==e.ctx.admin,ArkUserRole.role_id==role));db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==403 and e.snapshot()==baseline


@pytest.mark.parametrize('action',['begin','retain','abort'])
def test_live_lifecycle_permission_does_not_keep_old_global_scope(editor,action):
    e=editor;route,body,method=lifecycle_case(e,action)
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        root=db.scalar(select(ArkRole.id).where(ArkRole.name=='super_admin'))
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==e.ctx.admin,ArkUserRole.role_id==root))
        permission=db.scalar(select(ArkPermission).where(ArkPermission.code=='invoice:admin'))
        if permission is None:
            permission=ArkPermission(code='invoice:admin',module='invoice',action='admin',label='Isolated lifecycle',kind='action',is_legacy=False,sort=1)
            db.add(permission);db.flush()
        role=ArkRole(name='local-scope-'+uuid4().hex[:8],label='Admin action without global scope');db.add(role);db.flush()
        db.add_all([ArkUserRole(user_id=e.ctx.admin,role_id=role.id),ArkRolePermission(role_id=role.id,permission_id=permission.id)]);db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==404 and e.snapshot()==baseline


def forbid_remote(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Local action attempted remote I/O')
    for module,name in ((remote,'order_receipts'),(lifecycle_remote,'read'),(lifecycle_remote,'request'),(okki_client,'ensure_access_token')):
        monkeypatch.setattr(module,name,forbidden)


@pytest.mark.parametrize('action',['begin','retain','abort'])
def test_authorized_local_lifecycle_withdraws_without_remote_io(editor,monkeypatch,action):
    e=editor;route,body,method=lifecycle_case(e,action);forbid_remote(monkeypatch)
    with Session(e.ctx.engine) as db:
        before=invoices.get_invoice(db,e.invoice_id)
        commercial=linked.edit_version(before);remote_id=before.xiaoman_order_id
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        invoice=invoices.get_invoice(db,e.invoice_id)
        expected='cancel_pending' if action=='begin' else 'cancelled' if action=='retain' else 'ready'
        assert invoice.status==expected and invoice.xiaoman_order_id==remote_id
        assert linked.edit_version(invoice)==commercial and invoice.portal_document_version>e.version
        assert invoice.cancellation['created_by']==e.ctx.admin
        assert invoice.cancellation['status']=={'begin':'pending','retain':'retained','abort':'aborted'}[action]
        assert db.scalar(select(Publication).where(Publication.invoice_id==invoice.id)).status=='withdrawn'
        amendment=db.scalar(select(PiAmendment).where(PiAmendment.invoice_id==invoice.id))
        assert amendment.status=='withdrawn' and amendment.accepted_revision_id is None
        logs=db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id==invoice.id)).all()
        assert logs and all(row.operator_id==e.ctx.admin for row in logs)


@pytest.mark.parametrize('action',['begin','retain','abort'])
@pytest.mark.parametrize('commit_revocation',[True,False])
def test_local_lifecycle_obeys_real_revocation_commit_or_rollback(editor,action,commit_revocation):
    e=editor;route,body,method=lifecycle_case(e,action);baseline=e.snapshot()
    with Session(e.ctx.engine) as first,ThreadPoolExecutor(max_workers=1) as pool:
        lock_authority(first);first.get(ArkUser,e.ctx.admin).is_active=False;first.flush()
        future=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            wait_for_lock(e.ctx.engine,e.started.get(timeout=3));assert not future.done()
            if commit_revocation:first.commit()
            else:first.rollback()
            response=future.result(timeout=8)
        finally:first.rollback()
    assert response.status_code==(403 if commit_revocation else 200),response.text
    if commit_revocation:assert e.snapshot()==baseline


@pytest.mark.parametrize('action',['begin','retain','abort'])
def test_local_action_commits_before_waiting_admin_revocation(editor,action):
    e=editor;route,body,method=lifecycle_case(e,action);e.pause.enabled=True;started=queue.Queue()
    e.pause.invoice_status={'begin':'cancel_pending','retain':'cancelled','abort':'ready'}[action]
    def revoke():
        with Session(e.ctx.engine) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            lock_authority(db);db.get(ArkUser,e.ctx.admin).is_active=False;db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(asyncio.run,e.write(route,body,method,e.admin_token))
        try:
            assert e.pause.ready.wait(6)
            second=pool.submit(revoke)
            wait_for_lock(e.ctx.engine,started.get(timeout=3));assert not second.done()
            e.pause.release.set();response=first.result(timeout=8);second.result(timeout=8)
        finally:e.pause.release.set()
    assert response.status_code==200,response.text
    with Session(e.ctx.engine) as db:
        assert db.get(Invoice,e.invoice_id).status==e.pause.invoice_status
        assert not db.get(ArkUser,e.ctx.admin).is_active
    baseline=e.snapshot();e.pause.enabled=False
    retry=asyncio.run(e.write(route,body,method,e.admin_token))
    assert retry.status_code==403 and e.snapshot()==baseline


def test_retain_cannot_end_a_live_remote_delete_lease(editor,monkeypatch):
    e=editor;route,body,method=lifecycle_case(e,'retain')
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.cancellation={**invoice.cancellation,'status':'deleting','token':uuid4().hex,
            'lease_until':(beijing_now()+timedelta(minutes=2)).isoformat()};db.commit()
    forbid_remote(monkeypatch);baseline=e.snapshot()
    response=asyncio.run(e.write(route,body,method,e.admin_token))
    assert response.status_code==409 and e.snapshot()==baseline


def test_abort_cannot_reactivate_a_retained_cancelled_pi(editor,monkeypatch):
    e=editor;route,body,method=lifecycle_case(e,'retain');forbid_remote(monkeypatch)
    response=asyncio.run(e.write(route,body,method,e.admin_token));assert response.status_code==200
    baseline=e.snapshot()
    response=asyncio.run(e.write(route,{**body,'action':'abort'},method,e.admin_token))
    assert response.status_code==409 and e.snapshot()==baseline


@pytest.mark.parametrize('action',['begin','retain','abort'])
def test_local_lifecycle_locks_request_conversion_before_invoice(editor,action):
    e=editor;route,body,method=lifecycle_case(e,action);locks=[]
    def observe(conn,cursor,statement,params,context,many):
        if 'FOR UPDATE' in statement.upper():locks.append(statement)
    event.listen(e.ctx.engine,'before_cursor_execute',observe)
    try:response=asyncio.run(e.write(route,body,method,e.admin_token))
    finally:event.remove(e.ctx.engine,'before_cursor_execute',observe)
    assert response.status_code==200,response.text
    indices=[next(i for i,s in enumerate(locks) if ('FROM '+name) in s) for name in
        ('ark_order_portal_auth_barriers','ark_order_portal_requests','ark_order_portal_conversions','ark_invoices')]
    assert indices==sorted(indices) and len(set(indices))==4,locks


@pytest.mark.parametrize('capability',['write_only','sync_only','neither','inactive'])
def test_validate_rechecks_live_any_permission_before_marking_ready(editor,capability):
    e=editor
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id);invoice.status='draft'
        candidates=db.scalars(select(ArkRole).join(ArkUserRole,ArkUserRole.role_id==ArkRole.id).where(ArkUserRole.user_id==e.ctx.actor)).unique().all()
        for role in candidates:
            remove=(role.name=='sales' and capability in {'sync_only','neither'}) or (role.name.startswith('edit-') and capability in {'write_only','neither'})
            if remove:db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==e.ctx.actor,ArkUserRole.role_id==role.id))
        if capability=='inactive':db.get(ArkUser,e.ctx.actor).is_active=False
        db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(f'/api/invoice/invoices/{e.invoice_id}/validate',{},'POST'))
    allowed=capability in {'write_only','sync_only'}
    assert response.status_code==(200 if allowed else 403),response.text
    if allowed:
        assert response.json()['data']['ok'] is True
        with Session(e.ctx.engine) as db:
            invoice=db.get(Invoice,e.invoice_id)
            assert invoice.status=='ready' and invoice.portal_document_version==e.version
            assert db.scalar(select(Publication).where(Publication.invoice_id==invoice.id)).status=='published'
    else:assert e.snapshot()==baseline


@pytest.mark.parametrize('source',['portal','ordinary'])
@pytest.mark.parametrize('disabled',[False,True])
def test_delete_current_authority_and_existing_portal_lineage_protection(editor,source,disabled):
    e=editor;identity=e.invoice_id
    if source=='ordinary':
        values=deepcopy(e.body);values['invoice_no']='LOCAL-'+uuid4().hex[:12];values['source_type']='manual'
        for field in ('source_order_id','source_order_no','source_order_name','source_image_sha256','source_preview_token'):values[field]=None
        with Session(e.ctx.engine) as db:
            invoice=invoices.create_invoice(db,InvoiceCreate.model_validate(values),e.ctx.actor);db.commit();identity=invoice.id
    if disabled:
        with Session(e.ctx.engine) as db:
            lock_authority(db);db.get(ArkUser,e.ctx.actor).is_active=False;db.commit()
    baseline=e.snapshot();response=asyncio.run(e.write(f'/api/invoice/invoices/{identity}',{},'DELETE'))
    expected=403 if disabled else 400 if source=='portal' else 200
    assert response.status_code==expected,response.text
    if expected!=200:assert e.snapshot()==baseline
    else:
        with Session(e.ctx.engine) as db:
            assert db.get(Invoice,identity) is None
            assert not db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id==identity)).all()
            assert db.get(Invoice,e.invoice_id) is not None
            assert db.scalar(select(Publication).where(Publication.invoice_id==e.invoice_id)).status=='published'
