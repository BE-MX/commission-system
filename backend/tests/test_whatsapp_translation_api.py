import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient

from app.auth.models import ArkUser

from app.main import app
from app.whatsapp_translation import router as translation_router


PUBLIC = {
    ("GET", "/api/whatsapp-translation/health"),
    ("POST", "/api/whatsapp-translation/pairings"),
    ("POST", "/api/whatsapp-translation/pairings/exchange"),
}
JWT_WRITE = {
    ("POST", "/api/whatsapp-translation/pairings/inspect"),
    ("POST", "/api/whatsapp-translation/pairings/approve"),
    ("POST", "/api/whatsapp-translation/pairings/reject"),
    ("GET", "/api/whatsapp-translation/devices/me"),
    ("DELETE", "/api/whatsapp-translation/devices/me/{device_id}"),
    ("GET", "/api/whatsapp-translation/usage/me"),
}
DEVICE = {
    ("GET", "/api/whatsapp-translation/session"),
    ("GET", "/api/whatsapp-translation/capabilities"),
    ("POST", "/api/whatsapp-translation/translate"),
}
ADMIN = {
    ("GET", "/api/whatsapp-translation/admin/devices"),
    ("DELETE", "/api/whatsapp-translation/admin/devices/{device_id}"),
    ("GET", "/api/whatsapp-translation/admin/usage"),
    ("GET", "/api/whatsapp-translation/admin/health"),
}


@pytest.fixture(autouse=True)
def reset_limiters():
    translation_router.pairing_create_limiter.clear()
    translation_router.pairing_exchange_limiter.clear()
    yield
    translation_router.pairing_create_limiter.clear()
    translation_router.pairing_exchange_limiter.clear()


def test_openapi_exposes_only_approved_route_family():
    paths = app.openapi()["paths"]
    actual = {
        (method.upper(), path)
        for path in paths
        if path.startswith("/api/whatsapp-translation")
        for method in paths[path]
        if method.upper() != "OPTIONS"
    }
    assert actual == PUBLIC | JWT_WRITE | DEVICE | ADMIN


def test_public_pairing_create_is_rate_limited_before_db(monkeypatch):
    reached = {"database": False}

    def fail_create(*args, **kwargs):
        reached["database"] = True
        return SimpleNamespace(model_dump=lambda mode="json": {
            "device_code": "code", "authorize_url": "https://leshine.work", "expires_at": "2026-01-01T00:00:00"
        })

    monkeypatch.setattr(translation_router, "create_pairing", fail_create)
    for _ in range(30):
        response = client_post(
            "/api/whatsapp-translation/pairings",
            json={
                "proposed_token_hash": "a" * 64,
                "device_name": "Device",
                "browser_name": "Chrome",
                "browser_version": "140.0.0.0",
                "extension_version": "1.0.0",
            },
        )
        assert response.status_code == 200
    reached["database"] = False
    limited = client_post(
        "/api/whatsapp-translation/pairings",
        json={
            "proposed_token_hash": "a" * 64,
            "device_name": "Device",
            "browser_name": "Chrome",
            "browser_version": "140.0.0.0",
            "extension_version": "1.0.0",
        },
    )
    assert limited.status_code == 429
    assert limited.json()["data"]["error_code"] == "rate_limited"
    assert limited.headers["Cache-Control"] == "no-store"
    assert reached["database"] is False


def test_public_exchange_is_rate_limited_before_db(monkeypatch):
    reached = {"database": False}

    def fail_exchange(*args, **kwargs):
        reached["database"] = True
        return SimpleNamespace(model_dump=lambda mode="json": {
            "status": "pending", "device_id": None, "expires_at": "2026-01-01T00:00:00"
        })

    monkeypatch.setattr(translation_router, "exchange_pairing", fail_exchange)
    for _ in range(30):
        response = client_post(
            "/api/whatsapp-translation/pairings/exchange",
            json={"device_code": "a" * 43},
        )
        assert response.status_code == 200
    reached["database"] = False
    limited = client_post(
        "/api/whatsapp-translation/pairings/exchange",
        json={"device_code": "a" * 43},
    )
    assert limited.status_code == 429
    assert limited.json()["data"]["error_code"] == "rate_limited"
    assert reached["database"] is False


def test_public_health_is_available_without_authentication():
    response = client_get("/api/whatsapp-translation/health")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["data"] == {
        "status": "ok",
        "min_extension_version": "1.0.0",
    }


def test_device_route_rejects_ark_jwt_like_unauthenticated_request():
    response = client_get("/api/whatsapp-translation/session")
    assert response.status_code == 401
    assert response.json()["data"]["error_code"] == "invalid_bearer"


def test_jwt_route_requires_authentication():
    response = client_get("/api/whatsapp-translation/devices/me")
    assert response.status_code in {401, 403}


def test_session_and_translate_set_no_store(monkeypatch):
    from app.whatsapp_translation.auth import DeviceIdentity

    identity = DeviceIdentity(
        user_id=1,
        device_id=1,
        real_name="worker",
        extension_version="1.0.0",
        expires_at="2099-01-01T00:00:00",
        is_admin=False,
    )
    app.dependency_overrides[translation_router.device_identity] = lambda: identity
    try:
        response = client_get("/api/whatsapp-translation/session")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert "token" not in response.text.lower()
    finally:
        app.dependency_overrides.clear()


def test_management_permission_is_rechecked_from_database(db, monkeypatch):
    from app.whatsapp_translation.errors import WhatsAppTranslationError

    user = ArkUser(username="stale_jwt_worker", password_hash="test", real_name="stale_jwt_worker")
    db.add(user)
    db.commit()
    current_user = {"sub": str(user.id)}
    monkeypatch.setattr(translation_router, "get_live_user_authorization", lambda _db, _user_id: ([], []))

    with pytest.raises(WhatsAppTranslationError) as denied:
        translation_router._live_translation_actor(
            db,
            current_user,
            "whatsapp_translation:write",
        )

    assert denied.value.error_code == "permission_denied"


def test_device_capabilities_set_no_store(monkeypatch):
    from app.whatsapp_translation.auth import DeviceIdentity

    identity = DeviceIdentity(
        user_id=1,
        device_id=1,
        real_name="worker",
        extension_version="1.0.0",
        expires_at="2099-01-01T00:00:00",
        is_admin=False,
    )
    app.dependency_overrides[translation_router.device_identity] = lambda: identity
    try:
        response = client_get("/api/whatsapp-translation/capabilities")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


def client_get(path, **kwargs):
    return TestClient(app).get(path, **kwargs)


def client_post(path, **kwargs):
    return TestClient(app).post(path, **kwargs)
