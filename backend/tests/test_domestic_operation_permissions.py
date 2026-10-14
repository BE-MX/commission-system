"""Independent main-site report and manual-skip authorization."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.auth.service import seed_role_permissions
from app.core.database import get_db
from app.domestic import report_service
from app.domestic.router import router


@pytest.mark.parametrize("method,path,payload,service,required", [
    ("POST", "/reports", {"item_id": 1, "progress_id": 1, "qty": 1,
                           "on_behalf_user_id": 2, "request_id": "report-permission"},
     "submit_report", "domestic_report:write"),
    ("POST", "/reports/revoke", {"log_id": 1}, "revoke_report", "domestic_report:write"),
    ("POST", "/reports/skip", {"item_id": 1, "progress_id": 1, "qty": 1,
                                "reason": "Confirmed exception", "request_id": "skip-permission"},
     "submit_manual_skip", "domestic_skip:write"),
    ("POST", "/reports/skip/1/revoke", None, "revoke_manual_skip", "domestic_skip:write"),
    ("GET", "/reports/skips?item_id=1", None, "list_manual_skip_audits", "domestic_skip:write"),
])
@pytest.mark.parametrize("permissions,roles", [
    ([], []), (["domestic:read", "domestic:write", "domestic:admin"], ["admin"]),
    (["domestic_report:write"], []), (["domestic_skip:write"], []),
    (["domestic_report:write", "domestic:admin"], []),
    (["domestic_report:write", "domestic_skip:write"], []), ([], ["super_admin"]),
])
def test_operation_routes_require_their_own_permission(db, monkeypatch, method, path,
                                                      payload, service, required, permissions, roles):
    calls = []

    def operation(*args, **kwargs):
        calls.append(kwargs)
        return [] if service == "list_manual_skip_audits" else {"skipped_qty": 1}

    monkeypatch.setattr(report_service, service, operation)
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "permissions": permissions, "roles": roles,
    }
    with TestClient(app) as client:
        response = client.request(method, "/api/domestic" + path, json=payload)
    granted = required in permissions or "super_admin" in roles
    assert response.status_code == (200 if granted else 403)
    assert len(calls) == int(granted)
    if granted and service == "revoke_report":
        assert calls[0]["is_admin"] == ("domestic:admin" in permissions or "super_admin" in roles)


def test_operation_permissions_are_seeded_without_automatic_role_grants(db):
    admin = ArkRole(name="admin", label="Administrator")
    db.add(admin)
    db.flush()
    seed_role_permissions(db)
    seed_role_permissions(db)
    for code in ("domestic_report:write", "domestic_skip:write"):
        permission = db.query(ArkPermission).filter_by(code=code).one()
        assert permission.module == "domestic"
        assert permission.kind == "action"
        assert db.query(ArkRolePermission).filter_by(
            role_id=admin.id, permission_id=permission.id,
        ).count() == 0


@pytest.mark.parametrize("permissions,status", [
    (["domestic_report:write"], 200), (["domestic_skip:write"], 403),
    (["domestic:write"], 403),
])
def test_report_operator_can_load_workers_without_order_write(db, permissions, status):
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "roles": [], "permissions": permissions,
    }
    with TestClient(app) as client:
        assert client.get("/api/domestic/process-workers?process_id=1").status_code == status
