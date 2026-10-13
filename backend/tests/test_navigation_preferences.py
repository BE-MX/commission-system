"""SQLite-only personal navigation HTTP round trips and ownership validation."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser, ArkRole, ArkPermission
from app.auth.utils import create_access_token
from app.core.database import get_db
from app.system.models import NavigationPreference
from app.system.navigation_schemas import NavigationPrefs
from app.system.navigation_service import get_preferences, save_preferences
from app.system.navigation_access import load_access_manifest as real_load_access_manifest
from app.system.router import router

PATH = "/api/system/navigation-preferences"


@pytest.fixture(autouse=True)
def navigation_policy(monkeypatch):
    policy = {key: [{}] for key in ["Dashboard", "Other", "A", "B", "old", "new", "failed"]}
    policy.update({"InvoiceManage": [{"permission": "invoice:read"}], "Tracking": [{"permission": "tracking:read"}], "Admin": [{"permission": "user:admin"}], "Announcement": [{"anyPermission": ["announcement:read", "announcement:write"]}], "GroupRestricted": [{"permission": "invoice:read"}, {"permission": "user:admin"}]})
    monkeypatch.setattr("app.system.navigation_access.load_access_manifest", lambda: policy)


def user(db, name):
    permissions = []
    for code in ["invoice:read", "tracking:read"]:
        permission = db.query(ArkPermission).filter_by(code=code).first()
        if permission is None:
            module, action = code.split(":")
            permission = ArkPermission(code=code, module=module, action=action, label=code)
        permissions.append(permission)
    role = ArkRole(name=f"nav-{name}", label=name, permissions=permissions)
    row = ArkUser(username=name, real_name=name, password_hash="test-hash", roles=[role])
    db.add(row)
    db.commit()
    return row


@contextmanager
def client(db, owner=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/system")
    app.dependency_overrides[get_db] = lambda: db
    headers = {}
    if owner:
        token = create_access_token({"sub": str(owner.id), "username": owner.username, "roles": [], "permissions": []})
        headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app, headers=headers) as http:
        yield http


def test_http_order_refresh_remove_and_user_isolation(db):
    alice, bob = user(db, "nav-alice"), user(db, "nav-bob")
    with client(db, alice) as http:
        assert http.get(PATH).json()["data"] == {"items": []}
        assert http.put(PATH, json={"items": ["Dashboard", "InvoiceManage", "Tracking"]}).status_code == 200
        assert http.put(PATH, json={"items": ["Tracking", "Dashboard", "InvoiceManage"]}).json()["data"]["items"][0] == "Tracking"
    db.expire_all()
    with client(db, alice) as http:
        assert http.get(PATH).json()["data"]["items"] == ["Tracking", "Dashboard", "InvoiceManage"]
        assert http.put(PATH, json={"items": ["Dashboard"]}).status_code == 200
    with client(db, bob) as http:
        assert http.get(PATH).json()["data"]["items"] == []
        assert http.put(PATH, json={"items": ["Other"]}).status_code == 200
    assert get_preferences(db, alice.id)["items"] == ["Dashboard"]
    assert get_preferences(db, bob.id)["items"] == ["Other"]
    assert db.query(NavigationPreference).count() == 2
    with client(db, alice) as http:
        assert http.put(PATH, json={"items": []}).status_code == 200
        assert http.get(PATH).json()["data"]["items"] == []


def test_http_auth_and_owner_spoof_rejected(db):
    alice = user(db, "nav-owner")
    with client(db) as http:
        assert http.get(PATH).status_code in (401, 403)
        assert http.put(PATH, json={"items": []}).status_code in (401, 403)
    with client(db, alice) as http:
        assert http.put(PATH, json={"items": [], "user_id": 999}).status_code == 422
        assert http.put(PATH, json={"items": "bad"}).status_code == 422
        assert http.put(PATH, json={"items": ["a" * 101]}).status_code == 422
        assert http.put(PATH, json={"items": [str(i) for i in range(201)]}).status_code == 422
        assert http.put(PATH, json={"items": ["  "]}).status_code == 422
        assert http.put(PATH, json={"items": [" A ", "A", "B"]}).json()["data"] == {"items": ["A", "B"]}


def test_http_rejects_unknown_or_inaccessible_route_and_group(db):
    alice = user(db, "nav-no-admin")
    with client(db, alice) as http:
        for key in ["Admin", "Announcement", "GroupRestricted", "Unknown"]:
            assert http.put(PATH, json={"items": ["Dashboard", key]}).status_code == 403
            assert http.get(PATH).json()["data"]["items"] == []
        assert http.put(PATH, json={"items": ["Dashboard", "InvoiceManage"]}).status_code == 200


def test_revoked_live_permission_blocks_stale_jwt_and_preserves_hidden_saved_items(db):
    alice = user(db, "nav-revoked")
    token = create_access_token({"sub": str(alice.id), "roles": ["super_admin"], "permissions": ["user:admin", "invoice:read"]})
    with client(db, alice) as http:
        assert http.put(PATH, json={"items": ["InvoiceManage"]}).status_code == 200
        alice.roles = []
        db.commit()
        http.headers["Authorization"] = f"Bearer {token}"
        assert http.put(PATH, json={"items": ["InvoiceManage", "Admin"]}).status_code == 403
        # An existing inaccessible favorite can remain stored but cannot grant access.
        assert http.put(PATH, json={"items": ["Dashboard", "InvoiceManage"]}).status_code == 200
        assert http.put(PATH, json={"items": ["Dashboard"]}).status_code == 200
        assert http.put(PATH, json={"items": ["Dashboard", "InvoiceManage"]}).status_code == 403
        assert http.get(PATH).json()["data"]["items"] == ["Dashboard"]


def test_disabled_account_cannot_save_preferences(db):
    alice = user(db, "nav-disabled")
    with client(db, alice) as http:
        alice.is_active = False
        db.commit()
        assert http.put(PATH, json={"items": ["Dashboard"]}).status_code == 403


@pytest.mark.parametrize("contents", [None, '{}', '{"favorite_access":{"A":[{"anyPermission":"all"}]}}'])
def test_missing_or_invalid_manifest_blocks_additions(db, monkeypatch, tmp_path, contents):
    from app.system import navigation_access
    # Restore the real loader so this test covers missing and malformed files.
    monkeypatch.setattr(navigation_access, "load_access_manifest", real_load_access_manifest)
    path = tmp_path / "nav-manifest.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(navigation_access, "MANIFEST_PATH", path)
    alice = user(db, "nav-manifest")
    with client(db, alice) as http:
        assert http.put(PATH, json={"items": ["Dashboard"]}).status_code == 503
        assert http.get(PATH).json()["data"]["items"] == []


def test_backend_policy_is_source_bound_and_does_not_require_frontend_dist(monkeypatch, tmp_path):
    from app.system import navigation_access
    from fastapi import HTTPException
    manifest = tmp_path / "backend" / "navigation_access_manifest.json"
    source = tmp_path / "frontend" / "src" / "config" / "navigation.js"
    manifest.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    manifest.write_text(navigation_access.MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    source.write_text(navigation_access.SOURCE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(navigation_access, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(navigation_access, "SOURCE_PATH", source)
    assert not (tmp_path / "frontend" / "dist").exists()
    assert "InvoiceManage" in real_load_access_manifest()
    source.write_text(source.read_text(encoding="utf-8") + "\n// changed navigation\n", encoding="utf-8")
    with pytest.raises(HTTPException) as caught:
        real_load_access_manifest()
    assert caught.value.status_code == 503


def test_insert_race_recovers_and_commit_failure_rolls_back(db, monkeypatch):
    alice = user(db, "nav-race")
    save_preferences(db, alice.id, NavigationPrefs(items=["old"]))
    real_commit = db.commit
    calls = 0

    def commit():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate"))
        real_commit()

    monkeypatch.setattr(db, "commit", commit)
    assert save_preferences(db, alice.id, NavigationPrefs(items=["new"])) == {"items": ["new"]}
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        save_preferences(db, alice.id, NavigationPrefs(items=["failed"]))
    assert get_preferences(db, alice.id) == {"items": ["new"]}


def test_actual_duplicate_insert_recovers_existing_user_row(db, monkeypatch):
    alice = user(db, "nav-duplicate")
    save_preferences(db, alice.id, NavigationPrefs(items=["old"]))
    owner_id = alice.id
    db.expunge_all()
    real_get = db.get
    first = True

    def stale_read(model, key):
        nonlocal first
        if model is NavigationPreference and first:
            first = False
            return None
        return real_get(model, key)

    monkeypatch.setattr(db, "get", stale_read)
    assert save_preferences(db, owner_id, NavigationPrefs(items=["new"])) == {"items": ["new"]}
    assert db.query(NavigationPreference).count() == 1


@pytest.mark.parametrize("utc_time, expected", [
    (datetime(2026, 10, 12, 15, 59), datetime(2026, 10, 12, 23, 59)),
    (datetime(2026, 10, 12, 16, 0), datetime(2026, 10, 13, 0, 0)),
])
def test_navigation_audit_time_uses_beijing_across_midnight(db, utc_time, expected):
    from app.core.time import BEIJING_TIMEZONE
    from datetime import timezone
    alice = user(db, "nav-clock")
    # Source clock is UTC, regardless of the host's configured local timezone.
    with patch("app.core.time.datetime") as clock:
        clock.now.return_value = utc_time.replace(tzinfo=timezone.utc).astimezone(BEIJING_TIMEZONE)
        save_preferences(db, alice.id, NavigationPrefs(items=["A"]))
        assert db.get(NavigationPreference, alice.id).created_at == expected
        assert db.get(NavigationPreference, alice.id).updated_at == expected
        clock.now.return_value += timedelta(minutes=2)
        save_preferences(db, alice.id, NavigationPrefs(items=["B"]))
        assert db.get(NavigationPreference, alice.id).updated_at == expected + timedelta(minutes=2)
        assert clock.now.call_args.args == (BEIJING_TIMEZONE,)
