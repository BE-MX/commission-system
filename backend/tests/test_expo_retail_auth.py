from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.expo import retail_auth


GRANT = "0e68f8e0-c464-4c10-8b4f-e4e45200f90c"


@pytest.fixture(autouse=True)
def clear_grant_cache():
    retail_auth._cache.clear()
    yield
    retail_auth._cache.clear()


def test_valid_mall_grant_is_scoped_to_retail_phone(monkeypatch):
    monkeypatch.setattr(
        retail_auth,
        "get_settings",
        lambda: SimpleNamespace(EXPO_RETAIL_GRANT_INTROSPECTION_URL="https://mall.example/introspect"),
    )

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "active": True,
                "subject": "retail:13900009000",
                "expiresAt": "2099-01-01T00:00:00.000Z",
            }

    monkeypatch.setattr(retail_auth.httpx, "get", lambda *args, **kwargs: Response())
    grant = retail_auth.require_retail_tryon_grant(f"Retail {GRANT}")
    assert grant.phone == "13900009000"
    assert grant.subject == "retail:13900009000"


@pytest.mark.parametrize("authorization", [None, "Bearer token", "Retail bad-token"])
def test_internal_or_malformed_credentials_cannot_enter_retail_router(authorization):
    with pytest.raises(HTTPException) as exc:
        retail_auth.require_retail_tryon_grant(authorization)
    assert exc.value.status_code == 401


def test_generation_claim_conflict_becomes_customer_service_block(monkeypatch):
    monkeypatch.setattr(
        retail_auth,
        "get_settings",
        lambda: SimpleNamespace(EXPO_RETAIL_GRANT_INTROSPECTION_URL="https://mall.example/introspect"),
    )

    class Response:
        status_code = 409

    monkeypatch.setattr(retail_auth.httpx, "post", lambda *args, **kwargs: Response())
    grant = retail_auth.RetailGrant(GRANT, "retail:13900009000", "13900009000", "2099-01-01")
    with pytest.raises(HTTPException) as exc:
        retail_auth.claim_retail_tryon_generation(grant, "expo-session:12")
    assert exc.value.status_code == 409
    assert "联系专属客服" in exc.value.detail
