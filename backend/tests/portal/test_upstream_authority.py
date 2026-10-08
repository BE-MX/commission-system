"""Real upstream mutations on isolated SQLite; lock ordering, not MySQL races."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from test_access_policy import binding_db
from test_employee_authorization import authorization_db
from app.auth import admin_router
from app.auth.admin_schemas import UserUpdateRequest
from app.auth.models import ArkRole, ArkUser, ArkUserRole
from app.portal import authority
from app.portal.models import AuthorityBarrier
from app.portal.upstream_authority import begin_employee_authority_write


@pytest.fixture
def upstream_db(authorization_db, monkeypatch):
    db = authorization_db
    AuthorityBarrier.__table__.create(db.get_bind())
    db.add(AuthorityBarrier(code="authority"))
    db.commit()
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=True))
    return db


def test_disabled_portal_retains_installed_authority_checks(upstream_db, monkeypatch):
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=False))
    db = upstream_db
    version = db.scalar(select(AuthorityBarrier.version)); db.commit()
    # Historical administrator claims cannot bypass the installed OFF protocol.
    with pytest.raises(HTTPException) as denied:
        begin_employee_authority_write(db, {"sub":"1", "roles":["super_admin"]}, "user:write")
    assert denied.value.status_code == 403
    assert db.scalar(select(AuthorityBarrier.version)) == version


@pytest.mark.parametrize("name", ["create_user", "update_user", "delete_user", "toggle_user_active",
                                  "create_role", "update_role", "delete_role", "reset_user_password"])
def test_stale_super_admin_claim_denied_before_endpoint_queries(upstream_db, name):
    db = upstream_db
    statements = []
    def capture(connection, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    actor = {"sub": "1", "roles": ["super_admin"], "permissions": ["user:write", "role:write"]}
    calls = {
        "create_user": lambda: admin_router.create_user(None, db, actor),
        "update_user": lambda: admin_router.update_user(2, None, db, actor),
        "delete_user": lambda: admin_router.delete_user(2, db, actor),
        "toggle_user_active": lambda: admin_router.toggle_user_active(2, db, actor),
        "create_role": lambda: admin_router.create_role(None, db, actor),
        "update_role": lambda: admin_router.update_role(2, None, db, actor),
        "delete_role": lambda: admin_router.delete_role(2, db, actor),
        "reset_user_password": lambda: admin_router.reset_user_password(2, None, db, actor),
    }
    try:
        with pytest.raises(HTTPException) as error:
            calls[name]()
        assert error.value.status_code == 403
        assert AuthorityBarrier.__tablename__ in statements[0]
        assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)


def make_admin(db):
    db.get(ArkRole, 1).name = "super_admin"
    db.commit()
    return {"sub": "1", "roles": ["super_admin"]}


def test_role_removal_commits_with_barrier_and_stale_claim_cannot_restore(upstream_db):
    db = upstream_db
    actor = make_admin(db)
    result = admin_router.update_user(1, UserUpdateRequest(role_ids=[]), db, actor)
    assert result.code == 200
    assert db.scalar(select(ArkUserRole).where(ArkUserRole.user_id == 1)) is None
    version = db.scalar(select(AuthorityBarrier.version))
    db.commit()
    with pytest.raises(HTTPException) as error:
        admin_router.update_user(1, UserUpdateRequest(role_ids=[1]), db, actor)
    assert error.value.status_code == 403
    db.rollback()
    assert db.scalar(select(AuthorityBarrier.version)) == version


def test_disabled_admin_cannot_use_old_claim(upstream_db):
    db = upstream_db
    actor = make_admin(db)
    admin_router.update_user(1, UserUpdateRequest(is_active=False), db, actor)
    with pytest.raises(HTTPException) as error:
        admin_router.update_user(1, UserUpdateRequest(is_active=True), db, actor)
    assert error.value.status_code == 403
    db.rollback()
    assert db.get(ArkUser, 1).is_active is False


def test_mutation_failure_rolls_back_barrier_and_role(upstream_db):
    db = upstream_db
    actor = make_admin(db)
    db.add(ArkRole(id=2, name="test", label="Before", is_system=False))
    db.commit()
    before = db.scalar(select(AuthorityBarrier.version))
    db.commit()
    with pytest.raises(RuntimeError):
        # Simulate failure after authorization, before the caller's commit.
        begin_employee_authority_write(db, actor, "role:write")
        db.get(ArkRole, 2).label = "After"
        db.flush()
        raise RuntimeError("injected")
    db.rollback()
    assert db.get(ArkRole, 2).label == "Before"
    assert db.scalar(select(AuthorityBarrier.version)) == before


def test_delegate_endpoint_checks_actor_before_target(upstream_db):
    from app.invoice.router import put_delegate_grants, DelegateGrantPayload
    with pytest.raises(HTTPException) as error:
        put_delegate_grants(999, DelegateGrantPayload(sales_user_ids=[]), upstream_db,
                            {"sub": "1", "roles": ["super_admin"]})
    # No target existence lookup can precede the current actor permission check.
    assert error.value.status_code == 403


def test_delegation_service_barrier_and_rollback(upstream_db):
    from app.invoice import delegation_service
    from app.invoice.models import InvoiceDelegateGrant
    db = upstream_db
    InvoiceDelegateGrant.__table__.create(db.get_bind())
    db.execute(ArkUser.__table__.insert(), {"id": 2, "username": "delegate", "password_hash": "test", "is_active": True})
    db.commit()
    statements = []
    def capture(connection, cursor, sql, params, context, many):
        statements.append(sql)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        delegation_service.replace_grants(db, 2, [1], operator_id=1)
        assert AuthorityBarrier.__tablename__ in statements[0]
        db.commit()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)
    assert delegation_service.can_act_for(db, 2, 1)
    db.commit()
    delegation_service.replace_grants(db, 2, [], operator_id=1)
    db.rollback()
    assert delegation_service.can_act_for(db, 2, 1)
    db.commit()
    delegation_service.replace_grants(db, 2, [], operator_id=1)
    db.commit()
    assert not delegation_service.can_act_for(db, 2, 1)


def test_disabled_document_guard_rebuilds_installed_current_identity(upstream_db, monkeypatch):
    from app.portal.upstream_authority import begin_employee_document_write
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=False))
    db = upstream_db
    version = db.scalar(select(AuthorityBarrier.version)); db.commit()
    stale = {"sub":"1", "roles":["super_admin"], "permissions":["invoice:write"]}
    with pytest.raises(HTTPException) as denied:
        begin_employee_document_write(db, stale, "invoice:write")
    assert denied.value.status_code == 403
    assert db.scalar(select(AuthorityBarrier.version)) == version


@pytest.mark.parametrize("entry", ["normal", "linked"])
def test_document_http_entry_rejects_stale_claim_before_invoice_read(upstream_db, entry):
    from app.invoice import router
    statements = []
    def capture(connection, cursor, sql, params, context, many): statements.append(sql)
    event.listen(upstream_db.get_bind(), "before_cursor_execute", capture)
    actor = {"sub":"1", "roles":["super_admin"], "permissions":["invoice:write", "invoice:sync"]}
    try:
        with pytest.raises(HTTPException) as failure:
            if entry == "normal": router.update_invoice(999, None, upstream_db, actor)
            else: router.save_linked(999, None, upstream_db, actor, actor)
        assert failure.value.status_code == 403
        assert AuthorityBarrier.__tablename__ in statements[0]
        assert not any("ark_invoices" in sql for sql in statements)
    finally: event.remove(upstream_db.get_bind(), "before_cursor_execute", capture)


def test_document_guard_returns_live_scope_without_bumping_authority(upstream_db):
    from app.portal.upstream_authority import begin_employee_document_write
    actor = make_admin(upstream_db)
    version = upstream_db.scalar(select(AuthorityBarrier.version)); upstream_db.commit()
    result = begin_employee_document_write(upstream_db, {**actor,"roles":["stale"]}, "invoice:write", "invoice:sync")
    assert result["id"] == 1 and result["roles"] == ["super_admin"]
    assert upstream_db.scalar(select(AuthorityBarrier.version)) == version
