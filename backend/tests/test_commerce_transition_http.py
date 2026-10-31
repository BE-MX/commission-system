"""HTTP authorization uses real roles and invoice delegation scope in SQLite."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.commerce_transition.router import router
from app.core.database import get_db
from tests.test_commerce_transition_authority import install, invoice


def client_for(db, permissions, *, role_name="transition_test", stale_permissions=None):
    user = ArkUser(username=role_name, password_hash="isolated-not-a-real-password", real_name="Test")
    role = ArkRole(name=role_name, label=role_name)
    role.permissions = [ArkPermission(code=code, module=code.split(":")[0],
                                      action=code.split(":")[1], label=code) for code in permissions]
    user.roles = [role]
    db.add(user)
    db.flush()
    actor = user.id
    claims = {"sub": str(actor), "roles": [role_name], "permissions": stale_permissions or permissions}
    db.commit()
    app = FastAPI()
    app.include_router(router, prefix="/api/commerce-transition")

    def isolated_db():
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = lambda: claims
    return TestClient(app), actor


def test_invoice_writer_can_read_non_sensitive_status(db):
    install(db)
    client, _actor = client_for(db, ["invoice:write"])
    response = client.get("/api/commerce-transition/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["phase"] == "transition" and data["capabilities"]["local_new_orders"] is True
    assert data["capabilities"]["default_route"] == "legacy"
    assert "writers" not in data and "inventory_evidence" not in data
    assert client.get("/api/commerce-transition/writers").status_code == 403


def test_stale_jwt_admin_cannot_read_management_evidence(db):
    install(db)
    client, _actor = client_for(db, ["invoice:write"], stale_permissions=["commerce_transition:admin"])
    assert client.get("/api/commerce-transition/writers").status_code == 403


def test_authority_read_respects_current_invoice_scope(db):
    install(db)
    own = invoice(db, "OWN", confirmed=False)
    hidden = invoice(db, "HIDDEN", confirmed=False)
    own_id, hidden_id = own.id, hidden.id
    client, actor = client_for(db, ["invoice:read", "commerce_transition:read"])
    own.created_by, own.sales_user_id = actor, actor
    hidden.created_by, hidden.sales_user_id = actor + 999, actor + 999
    db.commit()
    response = client.get(f"/api/commerce-transition/invoices/{own_id}/authority")
    assert response.status_code == 200
    assert response.json()["data"]["authority_epoch"] == 1
    assert client.get(f"/api/commerce-transition/invoices/{hidden_id}/authority").status_code == 404


def test_superadmin_economic_boundary_still_rejects_confirmed_route_change(db):
    install(db)
    row = invoice(db)
    row_id = row.id
    client, _actor = client_for(db, [], role_name="super_admin")
    response = client.post(f"/api/commerce-transition/invoices/{row_id}/route", json={
        "route": "local", "expected_authority_epoch": 1, "evidence": {"caller": "admin"}})
    assert response.status_code == 409
    assert "已生效" in response.json()["detail"]


def test_live_revoked_write_permission_cannot_change_draft(db):
    install(db)
    row = invoice(db, confirmed=False)
    row_id = row.id
    client, _actor = client_for(db, ["invoice:write"],
                               stale_permissions=["invoice:write", "commerce_transition:write"])
    response = client.post(f"/api/commerce-transition/invoices/{row_id}/route", json={
        "route": "local", "expected_authority_epoch": 1, "evidence": {"pilot": "test"}})
    assert response.status_code == 403


@pytest.mark.parametrize(("path", "body"), [
    ("/writers", {"writer_key": "empty-proof", "protocol_version": 1, "state": "compatible", "evidence": {}}),
    ("/writers", {"writer_key": "audit-only", "protocol_version": 1, "state": "compatible", "evidence": {"recorded_by": 123}}),
    ("/policy", {"phase": "transition", "expected_version": 3, "inventory_evidence": {}}),
    ("/bank-domains", {"subject_key": "legal", "account_key": "bank", "channel": "statement",
                        "legacy_identity_complete": True, "enforced": True, "evidence": {}}),
])
def test_server_audit_identity_cannot_turn_empty_evidence_into_attestation(db, path, body):
    install(db)
    client, _actor = client_for(db, ["commerce_transition:admin"])
    response = client.post("/api/commerce-transition" + path, json=body)
    assert response.status_code in {409, 422}
