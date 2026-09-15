"""Live grants and HTTP boundaries, using isolated SQLite fixtures."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkRolePermission
from app.auth.service import seed_role_permissions
from app.core.database import get_db
from app.mini.auth import get_current_mini_user
from app.mini.access import ENTRY_PERMISSIONS, allowed_entries
from app.mini.router import router


@pytest.fixture
def context(engine):
    with Session(engine) as db:
        user = ArkUser(username="nav-worker", real_name="测试", password_hash="x", is_active=True)
        role = ArkRole(name="nav-worker", label="测试角色")
        user.roles.append(role)
        db.add(user)
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_mini_user] = lambda: user
        with TestClient(app) as client:
            yield db, user, role, client


def grant(db, role, code):
    perm = ArkPermission(code=code, module=code.split(":")[0], action=code.split(":")[1], label=code)
    db.add(perm)
    db.flush()
    db.add(ArkRolePermission(role_id=role.id, permission_id=perm.id))
    db.commit()
    return perm


@pytest.mark.parametrize("entry,code", ENTRY_PERMISSIONS.items())
def test_verify_reflects_grant_and_revocation(context, entry, code):
    db, user, role, client = context
    assert client.get("/auth/verify").json()["allowed_entries"] == []
    perm = grant(db, role, code)
    assert client.get("/auth/verify").json()["allowed_entries"] == [entry]
    db.query(ArkRolePermission).filter_by(role_id=role.id, permission_id=perm.id).delete()
    db.commit()
    assert client.get("/auth/verify").json()["allowed_entries"] == []


def test_super_admin_and_disabled_user(context):
    db, user, role, client = context
    role.name = "super_admin"
    db.commit()
    assert allowed_entries(db, user) == list(ENTRY_PERMISSIONS)
    user.is_active = False
    db.commit()
    assert allowed_entries(db, user) == []


@pytest.mark.parametrize("url", ["/scan/history", "/domestic/history", "/domestic/lookup?code=test", "/shipping-inspection/images/test.png"])
def test_denied_before_business_access(context, url):
    assert context[3].get(url).status_code == 403


def test_lookup_does_not_grant_reporting(context, monkeypatch):
    db, user, role, client = context
    grant(db, role, "mini_lookup:read")
    assert client.get("/domestic/history").status_code == 403
    assert client.get("/scan/history").status_code == 403
    from app.mini import router as module
    monkeypatch.setattr(module.domestic_order_service, "lookup_order", lambda *args, **kwargs: {"order_no": "test"})
    assert client.get("/domestic/lookup?code=test").status_code == 200


def test_public_progress_remains_signed_not_login_gated(context):
    assert context[3].get("/domestic/track").status_code == 422


def test_seed_does_not_grant_ordinary_admin(context):
    db, user, role, client = context
    role.name = "admin"
    db.commit()
    seed_role_permissions(db)
    seed_role_permissions(db)
    assert db.query(ArkPermission).filter(ArkPermission.code.in_(ENTRY_PERMISSIONS.values())).count() == 4
    assert allowed_entries(db, user) == []


def test_business_routes_have_capability_guards():
    for route in router.routes:
        path = route.path
        expected = None
        if path.startswith("/scan/"): expected = {"export"}
        elif path.startswith("/shipping-inspection/"): expected = {"shipping"}
        elif path.startswith("/domestic/") and not path.startswith("/domestic/track"):
            expected = {"domestic", "lookup"} if path.startswith(("/domestic/orders", "/domestic/images/")) else {"lookup"} if path == "/domestic/lookup" else {"domestic"}
        if expected is not None:
            assert expected in [set(getattr(dep.call, "mini_entries", ())) for dep in route.dependant.dependencies], path
