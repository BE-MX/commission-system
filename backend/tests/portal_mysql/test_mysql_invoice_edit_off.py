"""Installed OFF editors retain current authority; only verified legacy skips it."""
import asyncio
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, inspect, select, text, update
from sqlalchemy.orm import Session

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.auth.service import get_live_user_authorization
from app.invoice import edit_authority
from app.portal.authority import lock_authority
from app.receipt import remote


@contextmanager
def missing_protocol(engine):
    """Temporarily simulate the exact pre-portal marker on the owned test server."""
    table = 'ark_order_portal_auth_barriers'
    with engine.begin() as connection:
        created = not inspect(connection).has_table('alembic_version')
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        original = list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        connection.execute(text('DELETE FROM alembic_version'))
        connection.execute(text("INSERT INTO alembic_version VALUES ('171_customer_tag_display_value')"))
        connection.execute(text(f'RENAME TABLE {table} TO owned_editor_authority_backup'))
    try:
        yield
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_editor_authority_backup TO {table}'))
            if created:
                connection.execute(text('DROP TABLE alembic_version'))
            else:
                connection.execute(text('DELETE FROM alembic_version'))
                for head in original:
                    connection.execute(text('INSERT INTO alembic_version VALUES (:head)'), {'head': head})


@pytest.mark.parametrize('remaining', [None, 'invoice:write', 'invoice:sync'])
def test_off_validate_rechecks_any_permission_from_old_jwt(editor, monkeypatch, remaining):
    e = editor
    monkeypatch.setattr(edit_authority.authority.get_settings(), 'PORTAL_ENABLED', False)
    with Session(e.ctx.engine) as db:
        lock_authority(db)
        # Revoke only this actor; the shared sales role is used by later fixtures.
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id == e.ctx.actor))
        code = remaining or 'invoice:read'
        permission = db.scalar(select(ArkPermission.id).where(ArkPermission.code == code))
        if permission is None:
            row = ArkPermission(code=code, module='invoice', action='read', label='Read only',
                kind='action', is_legacy=False, sort=1)
            db.add(row); db.flush(); permission = row.id
        role = ArkRole(name='validate-off-' + uuid4().hex[:12], label='One current action')
        db.add(role); db.flush()
        db.add_all([ArkUserRole(user_id=e.ctx.actor, role_id=role.id),
            ArkRolePermission(role_id=role.id, permission_id=permission)])
        db.commit()
        roles, permissions = get_live_user_authorization(db, e.ctx.actor)
        assert roles and set(permissions) == {code}
    baseline = e.snapshot()
    response = asyncio.run(e.write(f'/api/invoice/invoices/{e.invoice_id}/validate', {}, 'POST'))
    assert response.status_code == (200 if remaining else 403), response.text
    if not remaining:
        assert e.snapshot() == baseline


@pytest.mark.parametrize('prior', ['read', 'dirty', 'flushed', 'core'])
def test_off_local_entry_rejects_existing_transaction(editor, monkeypatch, prior):
    e = editor
    monkeypatch.setattr(edit_authority.authority.get_settings(), 'PORTAL_ENABLED', False)
    with Session(e.ctx.engine) as db:
        if prior == 'core':
            db.execute(update(ArkUser).where(ArkUser.id == e.ctx.actor).values(is_active=False))
        else:
            user = db.get(ArkUser, e.ctx.actor)
            if prior != 'read':
                user.is_active = False
            if prior == 'flushed':
                db.flush()
        with pytest.raises(HTTPException) as caught:
            edit_authority.prepare_local(db, e.invoice_id, {'sub': str(e.ctx.actor)},
                'invoice:write', 'invoice:sync', any_permission=True)
        assert caught.value.status_code == 409
        db.rollback()
    with Session(e.ctx.engine) as db:
        assert db.get(ArkUser, e.ctx.actor).is_active


@pytest.mark.parametrize('local', [True, False])
def test_verified_preportal_entry_keeps_legacy_transaction(editor, monkeypatch, local):
    e = editor
    monkeypatch.setattr(edit_authority.authority.get_settings(), 'PORTAL_ENABLED', False)
    def forbidden(*args):
        pytest.fail('Legacy entry must not add external preflight or lineage reads')
    monkeypatch.setattr(remote, 'order_receipts', forbidden)
    statements, commits = [], []
    def observe(conn, cursor, statement, params, context, many):
        statements.append(statement)
    # Synthetic exact-parent boundary; does not claim a full legacy schema replay.
    with missing_protocol(e.ctx.engine):
        event.listen(e.ctx.engine, 'before_cursor_execute', observe)
        try:
            with Session(e.ctx.engine) as db:
                event.listen(db, 'after_commit', lambda session: commits.append(True))
                claims = {'sub': str(e.ctx.actor), 'permissions': ['invoice:write']}
                result = (edit_authority.prepare_local(db, e.invoice_id, claims, 'invoice:write')
                    if local else edit_authority.prepare(db, e.invoice_id, claims, 'invoice:write'))
                assert result[0].id == e.invoice_id and result[1] is claims
                if not local:
                    assert result[2] is None
                assert db.in_transaction() and commits == []
                db.rollback()
        finally:
            event.remove(e.ctx.engine, 'before_cursor_execute', observe)
    assert not any('FROM ark_order_portal_conversions' in sql
        or 'FROM ark_order_portal_requests' in sql for sql in statements)
