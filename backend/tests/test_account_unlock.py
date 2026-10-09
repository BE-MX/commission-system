"""Account unlock must preserve login evidence and keep future failures effective."""
import importlib.util
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mysql

from app.auth import account_lock_service, service
from app.auth.admin_router import router as admin_router
from app.auth.router import router as login_router
from app.auth.models import ArkAccountUnlockAudit, ArkLoginLog, ArkUser
from app.auth.utils import create_access_token, hash_password
from app.core.database import get_db
from app.core.time import BEIJING_TIMEZONE
from tests.authority_helpers import seed_authority


@pytest.fixture
def accounts(db, monkeypatch):
    now = datetime(2026, 10, 10, 0, 5)
    monkeypatch.setattr(account_lock_service, "beijing_now", lambda: now)
    monkeypatch.setattr(service, "beijing_now", lambda: now)
    monkeypatch.setattr(service.settings, "LOGIN_MAX_FAIL", 5)
    monkeypatch.setattr(service.settings, "LOGIN_LOCK_MINUTES", 30)
    db.add_all([
        ArkUser(id=201, username="admin", real_name="Admin", password_hash="x", is_active=True),
        ArkUser(id=202, username="ck", real_name="CK", password_hash=hash_password("correct-password"), is_active=True),
        ArkUser(id=203, username="other", real_name="Other", password_hash="x", is_active=True),
    ])
    db.commit()
    seed_authority(db, 201, "user:write", "user:read")
    return now


def failures(db, now, username="Ck", user_id=202, count=5):
    rows = [ArkLoginLog(
        username=username, user_id=user_id, status="failed", ip_address="127.0.0.1",
        fail_reason="密码错误", created_at=now - timedelta(minutes=4),
    ) for _ in range(count)]
    db.add_all(rows)
    db.commit()
    return rows


def client(db, permissions=("user:write", "user:read"), roles=()):
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/auth")
    app.include_router(login_router, prefix="/api/auth")
    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    token = create_access_token({"sub":"201", "username":"admin", "permissions":list(permissions), "roles":list(roles)})
    return TestClient(app, headers={"Authorization":f"Bearer {token}"})


def test_unlock_restores_login_preserves_logs_and_does_not_affect_other_account(db, accounts):
    ck_logs = failures(db, accounts)
    failures(db, accounts, username="other", user_id=203)
    original = [(r.id, r.status, r.fail_reason, r.created_at) for r in ck_logs]
    api = client(db)
    assert api.post("/api/auth/login", json={"username":"Ck", "password":"correct-password"}).status_code == 423
    result = api.post("/api/auth/users/202/unlock")
    assert result.status_code == 200
    assert result.json()["data"]["unlocked"] is True
    db.expire_all()
    rows = db.query(ArkLoginLog).filter(ArkLoginLog.id.in_([r[0] for r in original])).order_by(ArkLoginLog.id).all()
    assert [(r.id, r.status, r.fail_reason, r.created_at) for r in rows] == original
    audit = db.query(ArkAccountUnlockAudit).one()
    assert (audit.user_id, audit.operator_user_id, audit.operator_username, audit.failed_count) == (202, 201, "admin", 5)
    assert audit.created_at == accounts
    assert audit.through_login_log_id == original[-1][0]
    assert api.post("/api/auth/login", json={"username":"CK", "password":"correct-password"}).status_code == 200
    with pytest.raises(service.AccountLockedException):
        service.check_account_lockout(db, "other")


def test_future_failures_relock_even_in_same_second_and_retry_does_not_reset_them(db, accounts):
    failures(db, accounts)
    api = client(db)
    assert api.post("/api/auth/users/202/unlock").json()["data"]["unlocked"] is True
    for _ in range(4):
        assert api.post("/api/auth/login", json={"username":"ck", "password":"wrong-password"}).status_code == 401
    assert api.post("/api/auth/users/202/unlock").json()["data"]["unlocked"] is False
    assert db.query(ArkAccountUnlockAudit).count() == 1
    assert api.post("/api/auth/login", json={"username":"ck", "password":"wrong-password"}).status_code == 401
    assert api.post("/api/auth/login", json={"username":"ck", "password":"correct-password"}).status_code == 423
    assert api.post("/api/auth/users/202/unlock").json()["data"]["unlocked"] is True
    assert db.query(ArkAccountUnlockAudit).count() == 2


def test_permission_required_and_super_admin_supported(db, accounts):
    failures(db, accounts)
    denied = client(db, permissions=("user:read",)).post("/api/auth/users/202/unlock")
    assert denied.status_code == 403
    assert db.query(ArkAccountUnlockAudit).count() == 0
    assert client(db, permissions=(), roles=("super_admin",)).post("/api/auth/users/202/unlock").status_code == 200


def test_stale_jwt_cannot_unlock_after_live_role_revoke_or_operator_disable(db, accounts):
    from app.auth.models import ArkUserRole
    failures(db, accounts)
    api = client(db, roles=("super_admin",))
    role_id = db.query(ArkUserRole.role_id).filter(ArkUserRole.user_id == 201).scalar()
    db.query(ArkUserRole).filter(ArkUserRole.user_id == 201).delete()
    db.commit()
    assert api.post("/api/auth/users/202/unlock").status_code == 403
    assert api.post("/api/auth/users/999/unlock").status_code == 403
    db.add(ArkUserRole(user_id=201, role_id=role_id))
    db.commit()
    db.get(ArkUser, 201).is_active = False
    db.commit()
    assert api.post("/api/auth/users/202/unlock").status_code == 403
    assert db.query(ArkAccountUnlockAudit).count() == 0


def test_unlock_does_not_change_portal_authority_version(db, accounts):
    from app.portal.models import AuthorityBarrier
    failures(db, accounts)
    version = db.query(AuthorityBarrier.version).scalar()
    db.commit()
    assert client(db).post("/api/auth/users/202/unlock").status_code == 200
    assert db.query(AuthorityBarrier.version).scalar() == version


def test_authority_unavailable_and_busy_are_not_silent_or_successful(db, accounts, monkeypatch):
    from app.portal import authority
    from app.portal.errors import PortalError, TransactionBusy
    failures(db, accounts)
    def unavailable(_db):
        raise PortalError("SERVICE_UNAVAILABLE", "unavailable", 503)
    monkeypatch.setattr(authority, "lock_authority", unavailable)
    assert client(db).post("/api/auth/users/202/unlock").status_code == 503
    def busy(_db):
        raise TransactionBusy()
    monkeypatch.setattr(authority, "lock_authority", busy)
    with pytest.raises(TransactionBusy):
        account_lock_service.unlock_account(db, 202, {"sub":"201","username":"admin"})
    assert db.query(ArkAccountUnlockAudit).count() == 0


def test_disabled_deleted_and_missing_accounts_are_rejected(db, accounts):
    failures(db, accounts)
    target = db.get(ArkUser, 202)
    target.is_active = False
    db.commit()
    api = client(db)
    assert api.post("/api/auth/users/202/unlock").status_code == 400
    assert db.get(ArkUser, 202).is_active is False
    target.deleted_at = accounts
    db.commit()
    assert api.post("/api/auth/users/202/unlock").status_code == 404
    assert api.post("/api/auth/users/999/unlock").status_code == 404
    assert db.query(ArkAccountUnlockAudit).count() == 0


def test_list_uses_login_rule_and_refreshes_after_unlock(db, accounts):
    failures(db, accounts)
    api = client(db)
    def target():
        return next(r for r in api.get("/api/auth/users/list").json()["data"]["items"] if r["id"] == 202)
    assert target()["login_locked"] is True
    assert target()["login_failed_count"] == 5
    assert target()["login_lock_expires_at"] == (accounts + timedelta(minutes=26)).isoformat()
    api.post("/api/auth/users/202/unlock")
    assert target()["login_locked"] is False
    assert target()["login_failed_count"] == 0


def test_window_crosses_beijing_midnight_and_uses_beijing_clock(db, accounts, monkeypatch):
    # A UTC server clock is still the same instant as Beijing 00:05.
    utc_clock = accounts.replace(tzinfo=BEIJING_TIMEZONE).astimezone(timezone.utc)
    beijing_clock = utc_clock.astimezone(BEIJING_TIMEZONE).replace(tzinfo=None)
    monkeypatch.setattr(account_lock_service, "beijing_now", lambda: beijing_clock)
    failures(db, accounts)
    db.add(ArkLoginLog(username="ck",user_id=202,status="failed",ip_address="127.0.0.1",created_at=accounts - timedelta(minutes=30, seconds=1)))
    db.commit()
    assert account_lock_service.get_account_lock_states(db, [202])[202]["login_failed_count"] == 5
    monkeypatch.setattr(account_lock_service, "beijing_now", lambda: accounts + timedelta(minutes=26, seconds=1))
    assert account_lock_service.get_account_lock_states(db, [202])[202]["login_locked"] is False


def test_commit_failure_rolls_back_unlock(db, accounts, monkeypatch):
    failures(db, accounts)
    with monkeypatch.context() as scoped:
        scoped.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            account_lock_service.unlock_account(db, 202, {"sub":"201","username":"admin"})
    assert db.query(ArkAccountUnlockAudit).count() == 0
    with pytest.raises(service.AccountLockedException):
        service.check_account_lockout(db, "ck")


def test_old_unknown_user_failures_are_also_reset_by_username(db, accounts):
    failures(db, accounts, user_id=None)
    result = account_lock_service.unlock_account(db, 202, {"sub":"201","username":"admin"})
    assert result["unlocked"] is True
    service.check_account_lockout(db, "CK")
    assert db.query(ArkLoginLog).filter(ArkLoginLog.user_id.is_(None)).count() == 5


def test_more_than_threshold_failures_uses_the_correct_expiry(db, accounts):
    rows = failures(db, accounts, count=7)
    for offset, row in enumerate(rows):
        row.created_at = accounts - timedelta(minutes=10 - offset)
    db.commit()
    state = account_lock_service.get_account_lock_states(db, [202])[202]
    assert state["login_failed_count"] == 7
    assert state["login_lock_expires_at"] == (accounts + timedelta(minutes=22)).isoformat()


def test_successful_login_does_not_clear_window_without_admin_unlock(db, accounts):
    failures(db, accounts, count=4)
    api = client(db)
    assert api.post("/api/auth/login", json={"username":"ck","password":"correct-password"}).status_code == 200
    assert api.post("/api/auth/login", json={"username":"ck","password":"wrong-password"}).status_code == 401
    assert api.post("/api/auth/login", json={"username":"ck","password":"correct-password"}).status_code == 423


def test_migration_preserves_logs_and_matches_unsigned_user_foreign_keys():
    path = Path(__file__).parents[1] / "alembic/versions/178_account_unlock.py"
    spec = importlib.util.spec_from_file_location("account_unlock_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    for name in ("user_id", "operator_user_id"):
        column = ArkAccountUnlockAudit.__table__.c[name]
        assert str(column.type.compile(dialect=mysql.dialect())) == "INTEGER UNSIGNED"
    assert str(migration.USER_ID.compile(dialect=mysql.dialect())) == "INTEGER UNSIGNED"
    assert migration.down_revision == "177_portal_pi_header" and len(migration.revision) <= 32
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="mysql", opts={"as_sql":True,"output_buffer":output})):
        migration.upgrade()
    ddl = output.getvalue()
    assert "user_id INTEGER UNSIGNED NOT NULL" in ddl
    assert "operator_user_id INTEGER UNSIGNED NOT NULL" in ddl
    assert "FOREIGN KEY(operator_user_id) REFERENCES ark_users (id)" in ddl
    assert "ark_login_logs" not in ddl
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE ark_users (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE ark_login_logs (id INTEGER PRIMARY KEY, status TEXT)"))
        conn.execute(sa.text("INSERT INTO ark_login_logs VALUES (1, 'failed')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.execute(sa.text("SELECT status FROM ark_login_logs WHERE id=1")).scalar_one() == "failed"
        assert len(sa.inspect(conn).get_foreign_keys("ark_account_unlock_audits")) == 2
    engine.dispose()
