"""Invoice deletion grants are independent of write/admin, using isolated SQLite."""
from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission
from app.auth.service import seed_role_permissions
from app.core.database import get_db
from app.invoice import cancellation_execution, cancellation_service, deletion_service, lifecycle_remote, okki_client
from app.invoice.models import Invoice
from app.invoice.router import router
from tests.authority_helpers import seed_authority


@pytest.fixture
def order(db):
    invoice = Invoice(invoice_no="DELETE-GRANT-1", order_type="stock", created_by=1,
        sales_user_id=1, customer_id="101", customer_name="Test customer",
        invoice_date=date(2026, 10, 9), currency="USD", total_amount=100,
        sync_status="not_synced", status="draft")
    db.add(invoice)
    db.commit()
    return invoice


def api(db, user):
    app = FastAPI()
    app.include_router(router, prefix="/api/invoice")
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.mark.parametrize("codes", [[], ["invoice:write"], ["invoice:admin"], ["invoice:write", "invoice:admin"]])
@pytest.mark.parametrize("endpoint", ["local", "preview", "related", "lifecycle"])
def test_old_grants_cannot_delete(db, order, codes, endpoint, monkeypatch):
    seed_authority(db, 1, *codes)
    user = {"sub": "1", "roles": [], "permissions": codes}
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected deletion must not read or modify remote documents")
    monkeypatch.setattr(deletion_service, "preview", forbidden)
    monkeypatch.setattr(deletion_service, "run", forbidden)
    monkeypatch.setattr(cancellation_execution, "remove_authorized", forbidden)
    path = f"/api/invoice/invoices/{order.id}"
    with api(db, user) as client:
        if endpoint == "local":
            response = client.delete(path)
        elif endpoint == "preview":
            response = client.get(path + "/deletion")
        elif endpoint == "related":
            response = client.post(path + "/deletion", json={"expected_version": "a" * 64, "confirmed": True})
        else:
            response = client.post(path + "/lifecycle", json={"action": "remove", "reason": "Test reviewed deletion", "confirmed": True})
    assert response.status_code == 403
    assert db.get(Invoice, order.id) is not None


@pytest.mark.parametrize("portal_enabled", [False, True])
def test_delete_only_grant_can_remove_own_unsynced_invoice(db, order, monkeypatch, portal_enabled):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "PORTAL_ENABLED", portal_enabled)
    seed_authority(db, 1, "invoice:delete")
    identity = order.id
    with api(db, {"sub": "1", "roles": [], "permissions": ["invoice:delete"]}) as client:
        assert client.delete(f"/api/invoice/invoices/{identity}").status_code == 200
    assert db.get(Invoice, identity) is None


@pytest.mark.parametrize("actor,codes,expected", [(1, ["invoice:write"], 403), (2, ["invoice:delete"], 404), (2, ["invoice:delete", "invoice:read_all"], 200)])
def test_local_delete_rechecks_live_grant_and_scope(db, order, actor, codes, expected):
    seed_authority(db, actor, *codes)
    identity = order.id
    with api(db, {"sub": str(actor), "roles": [], "permissions": ["invoice:delete", "invoice:read_all"]}) as client:
        assert client.delete(f"/api/invoice/invoices/{identity}").status_code == expected
    assert (db.get(Invoice, identity) is None) == (expected == 200)


def test_super_admin_keeps_existing_bypass(db, order):
    seed_authority(db, 1, roles=("super_admin",))
    identity = order.id
    with api(db, {"sub": "1", "roles": ["super_admin"], "permissions": []}) as client:
        assert client.delete(f"/api/invoice/invoices/{identity}").status_code == 200


@pytest.mark.parametrize("actor,live_codes,expected", [(1, ["invoice:delete"], 200), (1, ["invoice:admin"], 403), (2, ["invoice:delete"], 404)])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_related_deletion_checks_live_grant_and_invoice_scope(db, order, monkeypatch, actor, live_codes, expected, method):
    seed_authority(db, actor, *live_codes)
    seen = []
    def result(*args):
        seen.append(args[2])
        return {"status": "blocked"}
    monkeypatch.setattr(deletion_service, "preview", result)
    monkeypatch.setattr(deletion_service, "run", result)
    user = {"sub": str(actor), "roles": [], "permissions": ["invoice:delete", "invoice:admin"]}
    with api(db, user) as client:
        path = f"/api/invoice/invoices/{order.id}/deletion"
        response = client.request(method, path, **({"json": {"expected_version": "a" * 64, "confirmed": True}} if method == "POST" else {}))
    assert response.status_code == expected
    assert bool(seen) == (expected == 200)
    if seen:
        assert seen[0]["permissions"] == ["invoice:delete"]  # Forward current grants, not JWT extras.


def test_old_lifecycle_executor_requires_live_delete_grant(db, order):
    identity = order.id
    seed_authority(db, 1, "invoice:admin")
    db.rollback()
    with pytest.raises(HTTPException) as error:
        cancellation_execution.remove_authorized(db, identity,
            {"sub": "1", "roles": [], "permissions": ["invoice:admin", "invoice:delete"]})
    assert error.value.status_code == 403


@pytest.mark.parametrize("codes,expected", [(["invoice:admin"], 403), (["invoice:admin", "invoice:delete"], 200)])
def test_disabled_portal_legacy_remove_uses_live_delete_grant(db, order, monkeypatch, codes, expected):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "PORTAL_ENABLED", False)
    seed_authority(db, 1, *codes)
    calls = []
    monkeypatch.setattr(cancellation_service, "remove_remote", lambda *args: calls.append(args[0]) or {"status": "remote_deleted"})
    user = {"sub": "1", "roles": [], "permissions": ["invoice:admin", "invoice:delete"]}
    with api(db, user) as client:
        response = client.post(f"/api/invoice/invoices/{order.id}/lifecycle",
            json={"action": "remove", "reason": "Test reviewed deletion", "confirmed": True})
    assert response.status_code == expected
    assert bool(calls) == (expected == 200)


def test_legacy_executor_rechecks_delete_after_remote_evidence(db, order, monkeypatch):
    seed_authority(db, 1, "invoice:admin", "invoice:delete")
    identity = order.id
    order.status = "cancel_pending"
    order.cancellation = {"status": "pending"}
    db.commit()
    monkeypatch.setattr(okki_client, "ensure_access_token", lambda *args: "test-token")
    def inspect(db, captured):
        permission = db.query(ArkPermission).filter_by(code="invoice:delete").one()
        db.query(ArkRolePermission).filter_by(permission_id=permission.id).delete()
        db.commit()
        return {"remote_exists": True, "outbounds": [], "remote_receipt_count": 0}
    def forbidden(*args, **kwargs):
        pytest.fail("Delete revoked during evidence capture must prevent the external request")
    monkeypatch.setattr(cancellation_service, "inspect", inspect)
    monkeypatch.setattr(lifecycle_remote, "request", forbidden)
    with pytest.raises(HTTPException) as error:
        cancellation_execution.remove_authorized(db, identity,
            {"sub": "1", "roles": [], "permissions": ["invoice:admin", "invoice:delete"]})
    assert error.value.status_code == 403


@pytest.mark.parametrize("code,module,label", [
    ("invoice:delete", "invoice", "删除订单发票及关联单据"),
    ("receipt:delete", "receipt", "删除订单关联回款单"),
])
def test_delete_permission_seed_is_idempotent_and_not_inherited(db, code, module, label):
    db.add_all([ArkRole(name="admin", label="Admin"), ArkRole(name="sales", label="Sales")])
    db.commit()
    seed_authority(db, 1, "invoice:write", "invoice:admin", "receipt:write", "receipt:admin")
    seed_role_permissions(db)
    seed_role_permissions(db)
    permission = db.query(ArkPermission).filter_by(code=code).one()
    assert (permission.module, permission.action, permission.kind, permission.label) == (
        module, "delete", "action", label)
    assert db.query(ArkRolePermission).filter_by(permission_id=permission.id).count() == 0
    admin = db.query(ArkRole).filter_by(name="admin").one()
    db.add(ArkRolePermission(role_id=admin.id, permission_id=permission.id))
    db.commit()
    seed_role_permissions(db)
    assert db.query(ArkRolePermission).filter_by(role_id=admin.id, permission_id=permission.id).count() == 1
