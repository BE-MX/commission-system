"""Editor task reads stay available while independent writers hold InnoDB locks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
import httpx
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.core.time import beijing_now
from app.invoice import linked_sync_service as linked, service
from app.invoice.models import Invoice, InvoiceLinkedSync
from app.portal import authority
from app.semifinished.models import InvoiceAllocation
from test_mysql_concurrency import wait_for_lock


async def read(e, *, token=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=e.app),
        base_url='https://ark.example.test') as client:
        return await client.get(f'/api/invoice/invoices/{e.invoice_id}/linked-sync',
            headers={'Authorization': 'Bearer ' + (token or e.token)})


def task(e, status='pending', lease=None):
    with Session(e.ctx.engine) as db:
        invoice = service.get_invoice(db, e.invoice_id)
        row = InvoiceLinkedSync(id=uuid4().hex, invoice_id=invoice.id,
            request_key=uuid4().hex, request_hash='a' * 64, created_by=e.ctx.actor,
            status=status, before=linked.snapshot(invoice), after=linked.snapshot(invoice),
            steps={key: {'status': 'pending'} for key in ('order', 'outbound', 'receipt')},
            run_token='original-runner' if status == 'running' else None, lease_until=lease)
        db.add(row)
        invoice.linked_sync_id = row.id
        db.commit()
        return row.id


@pytest.mark.parametrize('held', ['authority', 'invoice', 'task'])
@pytest.mark.parametrize('portal_enabled', [False, True])
def test_editor_task_read_does_not_wait_for_writer(editor, monkeypatch, held, portal_enabled):
    e = editor
    monkeypatch.setattr(authority.get_settings(), 'PORTAL_ENABLED', portal_enabled)
    monkeypatch.setattr(authority.get_settings(), 'PORTAL_LOCK_WAIT_SECONDS', 1)
    identity = task(e)
    before = e.snapshot()
    statements = []
    def observe(conn, cursor, statement, params, context, many):
        statements.append(statement)
    with Session(e.ctx.engine) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        if held == 'authority':
            authority.lock_authority(writer)
        elif held == 'invoice':
            writer.scalar(select(Invoice).where(Invoice.id == e.invoice_id).with_for_update())
        else:
            writer.scalar(select(InvoiceLinkedSync).where(InvoiceLinkedSync.id == identity).with_for_update())
        event.listen(e.ctx.engine, 'before_cursor_execute', observe)
        try:
            future = pool.submit(asyncio.run, read(e))
            response = future.result(timeout=4)
            assert response.status_code == 200, response.text
            assert response.json()['data']['id'] == identity
            assert response.json()['data']['status'] == 'pending'
            assert response.headers['Cache-Control'] == 'private, no-store'
        finally:
            writer.rollback()
            event.remove(e.ctx.engine, 'before_cursor_execute', observe)
    assert not any('FOR UPDATE' in sql.upper() or sql.lstrip().upper().startswith(
        ('INSERT', 'UPDATE', 'DELETE')) for sql in statements)
    assert e.snapshot() == before


@pytest.mark.parametrize('permission', ['invoice:read', 'invoice:write', 'invoice:sync'])
def test_task_read_uses_current_any_permission_and_scope(editor, permission):
    e = editor
    identity = task(e)
    with Session(e.ctx.engine) as db:
        code = db.scalar(select(ArkPermission).where(ArkPermission.code == permission))
        if code is None:
            code = ArkPermission(code=permission, module='invoice', action=permission.split(':')[1],
                label='Owned task reader', kind='action', is_legacy=False, sort=1)
            db.add(code); db.flush()
        role = ArkRole(name='task-reader-' + uuid4().hex[:12], label='One current action')
        db.add(role); db.flush()
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id == e.ctx.actor))
        db.add_all([ArkUserRole(user_id=e.ctx.actor, role_id=role.id),
            ArkRolePermission(role_id=role.id, permission_id=code.id)])
        db.commit()
    response = asyncio.run(read(e))
    assert response.status_code == 200 and response.json()['data']['id'] == identity
    with Session(e.ctx.engine) as db:
        db.get(Invoice, e.invoice_id).sales_user_id = e.ctx.admin
        db.get(Invoice, e.invoice_id).created_by = e.ctx.admin
        db.commit()
    assert asyncio.run(read(e)).status_code == 404
    with Session(e.ctx.engine) as db:
        db.get(ArkUser, e.ctx.actor).is_active = False
        db.commit()
    assert asyncio.run(read(e)).status_code == 403


@pytest.mark.parametrize('lease', ['active', 'expired', 'missing'])
def test_task_read_projects_expiry_without_changing_original_task(editor, lease):
    e = editor
    until = None if lease == 'missing' else beijing_now() + timedelta(minutes=5 if lease == 'active' else -5)
    identity = task(e, 'running', until)
    before = e.snapshot()
    response = asyncio.run(read(e))
    assert response.status_code == 200
    assert response.json()['data']['status'] == ('running' if lease == 'active' else 'uncertain')
    assert e.snapshot() == before
    # The existing explicit admin action must still work without a prior GET mutation.
    response = asyncio.run(e.write(f'/api/invoice/invoices/{e.invoice_id}/linked-sync/{identity}/resolve',
        {'reason': '已人工核对原订单、回款与库存并保留结果', 'confirmed': True}, 'POST', e.admin_token))
    assert response.status_code == (409 if lease == 'active' else 200), response.text
    with Session(e.ctx.engine) as db:
        row = db.get(InvoiceLinkedSync, identity)
        assert row.status == ('running' if lease == 'active' else 'manual')
        assert db.get(Invoice, e.invoice_id).linked_sync_id == (identity if lease == 'active' else None)
        if lease != 'active':
            with pytest.raises(linked.LostExecution):
                linked.ensure_running(db, db.get(Invoice, e.invoice_id), identity, 'original-runner')


def test_task_write_still_waits_for_authority_and_rechecks_revocation(editor):
    e = editor
    identity = task(e, 'failed')
    before = e.snapshot()
    with Session(e.ctx.engine) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        authority.lock_authority(writer)
        db_user = writer.get(ArkUser, e.ctx.actor)
        db_user.is_active = False
        writer.flush()
        future = pool.submit(asyncio.run, e.write(
            f'/api/invoice/invoices/{e.invoice_id}/linked-sync/{identity}/close', {}, 'POST'))
        try:
            wait_for_lock(e.ctx.engine, e.started.get(timeout=3))
            assert not future.done()
            writer.commit()
            assert future.result(timeout=5).status_code == 403
        finally:
            writer.rollback()
    assert e.snapshot() == before


@pytest.mark.parametrize('status', [None, 'done', 'failed'])
def test_editor_task_read_preserves_empty_and_finished_results(editor, status):
    e = editor
    identity = task(e, status) if status else None
    before = e.snapshot()
    with Session(e.ctx.engine) as writer:
        authority.lock_authority(writer)
        response = asyncio.run(read(e))
        assert response.status_code == 200
        result = response.json()['data']
        assert result is None if status is None else result['id'] == identity and result['status'] == status
        writer.rollback()
    assert e.snapshot() == before


def test_stale_super_admin_cannot_read_task_after_scope_revocation(editor):
    e = editor
    task(e)
    with Session(e.ctx.engine) as db:
        sync = db.scalar(select(ArkPermission.id).where(ArkPermission.code == 'invoice:sync'))
        role = ArkRole(name='former-admin-' + uuid4().hex[:12], label='Only sync after revocation')
        db.add(role); db.flush()
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id == e.ctx.admin))
        db.add_all([ArkUserRole(user_id=e.ctx.admin, role_id=role.id),
            ArkRolePermission(role_id=role.id, permission_id=sync)])
        db.commit()
    before = e.snapshot()
    assert asyncio.run(read(e, token=e.admin_token)).status_code == 404
    assert e.snapshot() == before


def test_revoked_action_cannot_read_task_with_old_jwt(editor):
    e = editor
    task(e)
    with Session(e.ctx.engine) as db:
        role = ArkRole(name='no-invoice-' + uuid4().hex[:12], label='Active role without invoice actions')
        db.add(role); db.flush()
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id == e.ctx.actor))
        db.add(ArkUserRole(user_id=e.ctx.actor, role_id=role.id))
        db.commit()
    before = e.snapshot()
    assert asyncio.run(read(e)).status_code == 403
    assert e.snapshot() == before


@pytest.mark.parametrize('blocker', ['changed_task', 'pending_inventory'])
def test_direct_expired_resolution_preserves_task_and_inventory_guards(editor, blocker):
    e = editor
    identity = task(e, 'running', beijing_now() - timedelta(minutes=5))
    if blocker == 'changed_task':
        task(e)
    else:
        with Session(e.ctx.engine) as db:
            db.add(InvoiceAllocation(invoice_id=e.invoice_id, material_id=1,
                pending_delta_grams=10, status='pending'))
            db.commit()
    before = e.snapshot()
    with Session(e.ctx.engine) as db:
        allocations = db.execute(select(*InvoiceAllocation.__table__.columns).order_by(InvoiceAllocation.id)).all()
    response = asyncio.run(e.write(f'/api/invoice/invoices/{e.invoice_id}/linked-sync/{identity}/resolve',
        {'reason': '已人工核对原订单、回款与库存并保留结果', 'confirmed': True}, 'POST', e.admin_token))
    assert response.status_code == 409, response.text
    assert e.snapshot() == before
    with Session(e.ctx.engine) as db:
        assert db.execute(select(*InvoiceAllocation.__table__.columns).order_by(InvoiceAllocation.id)).all() == allocations
        assert db.get(InvoiceLinkedSync, identity).status == 'running'
