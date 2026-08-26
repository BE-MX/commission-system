"""Integration App administration and site-token authentication contracts."""

from datetime import timedelta
import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import (
    ArkPermission,
    ArkRole,
    ArkRolePermission,
    ArkUser,
    ArkUserRole,
)
from app.auth.service import seed_role_permissions
from app.auth.utils import create_access_token, hash_token
from app.core.database import Base, get_db
from app.core.response import ok
from app.core.time import beijing_now
from app.integration.auth import require_integration_scope
from app.integration.models import IntegrationApp
from app.integration.router import router as integration_router


TABLES = [
    ArkUser.__table__,
    ArkRole.__table__,
    ArkPermission.__table__,
    ArkUserRole.__table__,
    ArkRolePermission.__table__,
    IntegrationApp.__table__,
]


def _setup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    db = sessionmaker(bind=engine)()

    invoice_write = ArkPermission(
        id=1,
        code="invoice:write",
        module="invoice",
        action="write",
        label="Invoice write",
    )
    writer_role = ArkRole(
        id=1,
        name="invoice_writer",
        label="Invoice writer",
        permissions=[invoice_write],
    )
    super_role = ArkRole(id=2, name="super_admin", label="Super admin")
    operator = ArkUser(
        id=99,
        username="operator",
        real_name="Operator",
        password_hash="test",
    )
    writer = ArkUser(
        id=1,
        username="writer",
        real_name="Writer User",
        password_hash="test",
        roles=[writer_role],
    )
    super_user = ArkUser(
        id=2,
        username="root-user",
        real_name="Root User",
        password_hash="test",
        roles=[super_role],
    )
    plain = ArkUser(
        id=3,
        username="plain",
        real_name="Plain User",
        password_hash="test",
    )
    inactive = ArkUser(
        id=4,
        username="inactive",
        real_name="Inactive User",
        password_hash="test",
        is_active=False,
        roles=[writer_role],
    )
    deleted = ArkUser(
        id=5,
        username="deleted",
        real_name="Deleted User",
        password_hash="test",
        deleted_at=beijing_now(),
        roles=[writer_role],
    )
    db.add_all([operator, writer, super_user, plain, inactive, deleted])
    db.commit()

    app = FastAPI()
    app.include_router(integration_router, prefix="/api/integrations")

    @app.get("/site-protected")
    def site_protected(
        principal=Depends(require_integration_scope("invoice:write")),
    ):
        return ok(
            {
                "actor_user_id": principal.actor_user_id,
                "sales_user_id": principal.sales_user_id,
                "idempotency_namespace": principal.idempotency_namespace,
                "scopes": sorted(principal.scopes),
            }
        )

    @app.get("/internal-protected")
    def internal_protected(
        _: dict = Depends(require_permission("invoice:write")),
    ):
        return ok({"accepted": True})

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "99",
        "roles": [],
        "permissions": ["integration:admin"],
    }
    return TestClient(app), app, db, engine, writer_role, invoice_write


def _issue(client: TestClient, *, owner_user_id: int = 1, name: str = "Order site") -> dict:
    response = client.post(
        "/api/integrations/admin/apps",
        json={"name": name, "owner_user_id": owner_user_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_issue_returns_plaintext_once_and_persists_only_sha256():
    client, _, db, engine, _, _ = _setup()
    try:
        issued = _issue(client, name="  Sales portal  ")
        token = issued["token"]
        assert token.startswith("ark_live_")
        assert len(issued["public_id"]) <= 32
        assert issued["scopes"] == ["invoice:write"]
        assert issued["name"] == "Sales portal"

        row = db.query(IntegrationApp).filter(IntegrationApp.id == issued["id"]).one()
        assert row.token_hash == hash_token(token)
        assert len(row.token_hash) == 64
        assert row.token_suffix == token[-6:]
        assert token not in json.dumps(row.__dict__, default=str)

        listed = client.get("/api/integrations/admin/apps")
        assert listed.status_code == 200, listed.text
        listed_json = listed.json()
        item = listed_json["data"]["items"][0]
        assert "token" not in item
        assert "token_hash" not in item
        assert token not in listed.text

        unknown = client.post(
            "/api/integrations/admin/apps",
            json={"name": "Unknown field", "owner_user_id": 1, "scope": "invoice:write"},
        )
        assert unknown.status_code == 422
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_rotate_updates_same_app_and_invalidates_old_token_immediately():
    client, _, db, engine, _, _ = _setup()
    try:
        issued = _issue(client)
        old_token = issued["token"]
        accepted = client.get("/site-protected", headers=_bearer(old_token))
        assert accepted.status_code == 200, accepted.text

        rotated = client.post(f"/api/integrations/admin/apps/{issued['id']}/rotate")
        assert rotated.status_code == 200, rotated.text
        data = rotated.json()["data"]
        new_token = data["token"]
        assert data["id"] == issued["id"]
        assert new_token.startswith("ark_live_")
        assert new_token != old_token

        assert client.get("/site-protected", headers=_bearer(old_token)).status_code == 401
        assert client.get("/site-protected", headers=_bearer(new_token)).status_code == 200
        db.expire_all()
        row = db.query(IntegrationApp).filter(IntegrationApp.id == issued["id"]).one()
        assert row.token_hash == hash_token(new_token)
        assert row.token_hash != hash_token(old_token)
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_revoked_and_disabled_apps_fail_authentication_and_rotate_is_blocked():
    client, _, db, engine, _, _ = _setup()
    try:
        issued = _issue(client)
        token = issued["token"]
        revoked = client.delete(f"/api/integrations/admin/apps/{issued['id']}")
        assert revoked.status_code == 200, revoked.text
        assert client.delete(f"/api/integrations/admin/apps/{issued['id']}").status_code == 200
        assert client.get("/site-protected", headers=_bearer(token)).status_code == 401
        assert client.post(f"/api/integrations/admin/apps/{issued['id']}/rotate").status_code == 409

        second = _issue(client, name="Disabled site")
        row = db.query(IntegrationApp).filter(IntegrationApp.id == second["id"]).one()
        row.is_active = False
        db.commit()
        assert client.get("/site-protected", headers=_bearer(second["token"])).status_code == 401
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_owner_state_expiry_permission_and_scope_are_rechecked_on_every_request():
    client, _, db, engine, writer_role, invoice_write = _setup()
    try:
        issued = _issue(client)
        token = issued["token"]
        row = db.query(IntegrationApp).filter(IntegrationApp.id == issued["id"]).one()
        owner = db.query(ArkUser).filter(ArkUser.id == 1).one()

        owner.is_active = False
        db.commit()
        assert client.get("/site-protected", headers=_bearer(token)).status_code == 401
        owner.is_active = True
        db.commit()

        owner.deleted_at = beijing_now()
        db.commit()
        assert client.get("/site-protected", headers=_bearer(token)).status_code == 401
        owner.deleted_at = None
        db.commit()

        row.expires_at = beijing_now() - timedelta(seconds=1)
        db.commit()
        assert client.get("/site-protected", headers=_bearer(token)).status_code == 401
        row.expires_at = None
        db.commit()

        writer_role.permissions.remove(invoice_write)
        db.commit()
        db.expire_all()
        assert client.get("/site-protected", headers=_bearer(token)).status_code == 403
        writer_role = db.query(ArkRole).filter(ArkRole.id == 1).one()
        invoice_write = db.query(ArkPermission).filter(ArkPermission.id == 1).one()
        writer_role.permissions.append(invoice_write)
        db.commit()

        row = db.query(IntegrationApp).filter(IntegrationApp.id == issued["id"]).one()
        row.scopes = []
        db.commit()
        assert client.get("/site-protected", headers=_bearer(token)).status_code == 403
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_jwt_and_site_tokens_cannot_cross_authentication_boundaries():
    client, app, _, engine, _, _ = _setup()
    try:
        issued = _issue(client)
        app.dependency_overrides.pop(get_current_user)
        assert client.get(
            "/internal-protected",
            headers=_bearer(issued["token"]),
        ).status_code == 401

        jwt_token = create_access_token(
            {
                "sub": "1",
                "roles": [],
                "permissions": ["invoice:write"],
            }
        )
        assert client.get("/site-protected", headers=_bearer(jwt_token)).status_code == 401
    finally:
        client.close()
        engine.dispose()


def test_all_admin_endpoints_require_integration_admin_permission():
    client, app, _, engine, _, _ = _setup()
    try:
        issued = _issue(client)
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": "99",
            "roles": [],
            "permissions": [],
        }
        requests = [
            client.get("/api/integrations/admin/user-candidates"),
            client.get("/api/integrations/admin/apps"),
            client.post(
                "/api/integrations/admin/apps",
                json={"name": "Blocked", "owner_user_id": 1},
            ),
            client.post(f"/api/integrations/admin/apps/{issued['id']}/rotate"),
            client.delete(f"/api/integrations/admin/apps/{issued['id']}"),
        ]
        assert [response.status_code for response in requests] == [403, 403, 403, 403, 403]
    finally:
        client.close()
        engine.dispose()


def test_candidates_include_only_active_users_and_report_current_eligibility():
    client, _, _, engine, _, _ = _setup()
    try:
        response = client.get("/api/integrations/admin/user-candidates", params={"q": "user"})
        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert [item["username"] for item in items] == ["plain", "root-user", "writer"]
        eligible = {item["username"]: item["has_invoice_write"] for item in items}
        assert eligible == {"plain": False, "root-user": True, "writer": True}
        assert all(set(item) == {"user_id", "username", "real_name", "has_invoice_write"} for item in items)

        assert client.post(
            "/api/integrations/admin/apps",
            json={"name": "Plain owner", "owner_user_id": 3},
        ).status_code == 400
        assert client.post(
            "/api/integrations/admin/apps",
            json={"name": "Inactive owner", "owner_user_id": 4},
        ).status_code == 400
        assert client.post(
            "/api/integrations/admin/apps",
            json={"name": "Missing owner", "owner_user_id": 404},
        ).status_code == 404
        assert _issue(client, owner_user_id=2, name="Super owner")["owner_user_id"] == 2
    finally:
        client.close()
        engine.dispose()


def test_permission_seed_registers_integration_admin_metadata():
    client, _, db, engine, _, _ = _setup()
    try:
        seed_role_permissions(db)
        permission = db.query(ArkPermission).filter(
            ArkPermission.code == "integration:admin"
        ).one()
        assert permission.module == "integration"
        assert permission.action == "admin"
        assert "接入凭证" in permission.label
    finally:
        client.close()
        db.close()
        engine.dispose()


def test_full_application_registers_integration_admin_paths():
    from app.routers import register_routers

    app = FastAPI()
    register_routers(app)
    paths = {route.path for route in app.routes}
    assert {
        "/api/integrations/admin/user-candidates",
        "/api/integrations/admin/apps",
        "/api/integrations/admin/apps/{app_id}/rotate",
        "/api/integrations/admin/apps/{app_id}",
    }.issubset(paths)
