"""Collector isolation and current-authority regression checks (SQLite only)."""
from datetime import timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from tests.test_integration_admin import _setup
from app.alibaba_feed.auth import resolve_feed_principal
from app.alibaba_feed.models import AlibabaFeedSource
from app.alibaba_feed.source_service import SourceCreate, SourcePatch, create_source, update_source
from app.auth.models import ArkPermission, ArkUser, ArkRolePermission
from app.core.time import beijing_now
from app.integration.auth import IntegrationAuthError, resolve_submission_principal
from app.integration.models import IntegrationApp
from app.integration.schemas import IntegrationAppCreate
from app.integration.service import create_app, rotate_app_token


@pytest.fixture
def feed():
    client, api, db, engine, role, _ = _setup()
    AlibabaFeedSource.__table__.create(engine)
    for action in ("read", "write"):
        role.permissions.append(ArkPermission(code=f"alibaba_feed:{action}", module="alibaba_feed", action=action, label=action))
    db.commit()
    request = IntegrationAppCreate(name="Feed", owner_user_id=1, scopes=["alibaba_feed:read", "alibaba_feed:write"])
    issued = create_app(db, request, created_by=99)
    source = create_source(db, SourceCreate(source_account_uid="shop-a", integration_app_id=issued["id"], name="Shop A"))
    yield db, issued, source, role
    db.close()
    engine.dispose()


def enable(db, source):
    return update_source(db, "shop-a", SourcePatch(expected_version=source["version"], consent_state="authorized", ingest_enabled=True))


def test_feed_default_disabled_and_no_invoice_scope(feed):
    db, issued, source, _ = feed
    assert source["ingest_enabled"] is False
    with pytest.raises(IntegrationAuthError):
        resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:write")
    enable(db, source)
    principal = resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:write")
    assert principal.source_account_uid == "shop-a"
    with pytest.raises(IntegrationAuthError):
        resolve_submission_principal(db, issued["token"], required_scope="invoice:write")
    with pytest.raises(ValidationError):
        IntegrationAppCreate(name="Bad", owner_user_id=1, scopes=["invoice:write", "alibaba_feed:write"])
    assert IntegrationAppCreate(name="Default", owner_user_id=1).scopes == ["invoice:write"]


@pytest.mark.parametrize("change", ["revoked", "expired", "inactive_owner", "removed_permission", "removed_scope"])
def test_current_revocation_rechecked(feed, change):
    db, issued, source, role = feed
    enable(db, source)
    resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:write")
    row = db.get(IntegrationApp, issued["id"])
    if change == "revoked":
        row.is_active = False
    elif change == "expired":
        row.expires_at = beijing_now() - timedelta(seconds=1)
    elif change == "inactive_owner":
        db.get(ArkUser, 1).is_active = False
    elif change == "removed_permission":
        permission = db.query(ArkPermission).filter_by(code="alibaba_feed:write").one()
        db.query(ArkRolePermission).filter_by(role_id=role.id, permission_id=permission.id).delete()
    else:
        row.scopes = ["alibaba_feed:read"]
    db.commit()
    with pytest.raises(IntegrationAuthError):
        resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:write")


def test_rotate_keeps_source_and_optimistic_update(feed):
    db, issued, source, _ = feed
    active = enable(db, source)
    before = resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:read")
    rotated = rotate_app_token(db, issued["id"], current_token_suffix=issued["token"][-6:])
    with pytest.raises(IntegrationAuthError):
        resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:read")
    after = resolve_feed_principal(db, rotated["token"], required_scope="alibaba_feed:read")
    assert (after.source_id, after.generation) == (before.source_id, before.generation)
    with pytest.raises(HTTPException) as error:
        update_source(db, "shop-a", SourcePatch(expected_version=1, name="Stale"))
    assert error.value.status_code == 409
    assert SourcePatch(expected_version=active["version"], crm_shared=True).crm_shared is True
    with pytest.raises(ValidationError):
        SourcePatch(expected_version=active["version"], source_account_uid="shop-b")


@pytest.mark.parametrize("change", ["rotate", "revoke", "permission"])
def test_post_upload_recheck_rejects_changed_authority(feed, change):
    from app.alibaba_feed.auth import recheck_feed_principal
    from app.alibaba_feed.errors import FeedError
    db, issued, source, role = feed
    enable(db, source)
    principal = resolve_feed_principal(db, issued["token"], required_scope="alibaba_feed:write")
    db.rollback()  # Request releases preflight locks while the body streams.
    if change == "rotate":
        rotate_app_token(db, issued["id"], current_token_suffix=issued["token"][-6:])
    elif change == "revoke":
        db.get(IntegrationApp, issued["id"]).is_active = False
        db.commit()
    else:
        permission = db.query(ArkPermission).filter_by(code="alibaba_feed:write").one()
        db.query(ArkRolePermission).filter_by(role_id=role.id, permission_id=permission.id).delete()
        db.commit()
    with pytest.raises(FeedError):
        recheck_feed_principal(db, principal, required_scope="alibaba_feed:write")


def test_source_cannot_reuse_other_binding_or_enable_external_use(feed):
    db, issued, source, _ = feed
    with pytest.raises(HTTPException) as error:
        create_source(db, SourceCreate(source_account_uid="shop-b", integration_app_id=issued["id"], name="Other"))
    assert error.value.status_code == 409
    row = db.query(AlibabaFeedSource).filter_by(source_account_uid="shop-a").one()
    assert not row.crm_shared and not row.ai_egress_allowed


def test_collector_token_cannot_administer_sources(feed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.alibaba_feed.source_router import router
    from app.core.database import get_db
    db, issued, _, _ = feed
    app = FastAPI()
    app.include_router(router, prefix="/api/alibaba-feed")
    app.dependency_overrides[get_db] = lambda: db
    response = TestClient(app).patch("/api/alibaba-feed/sources/shop-a", headers={"Authorization": "Bearer " + issued["token"]}, json={"expected_version": 1, "ingest_enabled": True})
    assert response.status_code in {401, 403}


def test_management_http_current_admin_validation_and_conflict(feed):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.alibaba_feed.source_router import router
    from app.core.database import get_db
    db, issued, source, _ = feed
    app = FastAPI()
    app.include_router(router, prefix="/api/alibaba-feed")
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    # JWT claims are not sufficient without the corresponding current authority.
    app.dependency_overrides[get_current_user] = lambda: {"sub": "99", "roles": ["super_admin"], "permissions": ["alibaba_feed:admin"]}
    denied = client.patch("/api/alibaba-feed/sources/shop-a", json={"expected_version": 1, "name": "Changed"})
    assert denied.status_code == 403
    assert denied.json()["data"]["error_code"] == "SOURCE_SCOPE_DENIED"
    app.dependency_overrides[get_current_user] = lambda: {"sub": "2"}
    updated = client.patch("/api/alibaba-feed/sources/shop-a", json={"expected_version": 1, "name": "Changed"})
    assert updated.status_code == 200
    stale = client.patch("/api/alibaba-feed/sources/shop-a", json={"expected_version": 1, "name": "ExternalSecret"})
    assert stale.status_code == 409
    assert stale.json()["data"]["error_code"] == "SOURCE_VERSION_CONFLICT"
    invalid = client.patch("/api/alibaba-feed/sources/shop-a", json={"expected_version": 2, "ExternalSecret": "SensitiveValue", "crm_shared": True})
    assert invalid.status_code == 422
    assert "ExternalSecret" not in invalid.text and "SensitiveValue" not in invalid.text
    db.get(ArkUser, 2).is_active = False
    db.commit()
    inactive = client.patch("/api/alibaba-feed/sources/shop-a", json={"expected_version": 2, "name": "Changed"})
    assert inactive.status_code == 403
