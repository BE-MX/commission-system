"""HTTP contract tests for the internal customer image API."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db


NOW = datetime(2026, 8, 7, 8, 0, 0)


def _row(**overrides):
    values = {
        "id": 1,
        "name": "Catalog Wig",
        "category": "wig",
        "description": "Template",
        "fixed_prompt": "private fixed prompt",
        "output_prompt": "private output prompt",
        "config_version": 1,
        "is_published": True,
        "sort": 0,
        "customer_id": "C1",
        "customer_name_snapshot": "Acme",
        "created_by": 7,
        "token_hash": "never-return-this",
        "token_suffix": "abc123",
        "starts_at": NOW,
        "expires_at": datetime(2026, 8, 14, 8, 0, 0),
        "quota_total": 5,
        "quota_used": 1,
        "revoked_at": None,
        "created_at": NOW,
        "invite_id": 2,
        "product_id": 1,
        "product_name_snapshot": "Catalog Wig",
        "status": "queued",
        "error_code": None,
        "error_message": None,
        "billing_certainty": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "estimated_cost_microusd": None,
        "finished_at": None,
        "prompt_snapshot": "never-return-prompt",
        "pricing_snapshot": {"never": "return"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def api(monkeypatch):
    from app.customer_image import router as module
    from app.customer_image import service

    app = FastAPI()
    app.include_router(module.router, prefix="/api/customer-image")
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7",
        "roles": [],
        "permissions": [
            "customer_image:read",
            "customer_image:write",
            "customer_image:admin",
        ],
    }
    product = _row()
    invite = _row(id=2)
    generation = _row(id=3, invite_id=2)
    monkeypatch.setattr(service, "list_products", lambda *_a, **_k: [product])
    monkeypatch.setattr(service, "list_product_options", lambda *_a, **_k: [])
    monkeypatch.setattr(service, "create_product", lambda *_a, **_k: product)
    monkeypatch.setattr(service, "update_product", lambda *_a, **_k: product)
    monkeypatch.setattr(service, "delete_product", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "publish_product", lambda *_a, **_k: product)
    monkeypatch.setattr(service, "list_available_customers", lambda *_a, **_k: [{"id": "C1"}])
    monkeypatch.setattr(service, "create_invite", lambda *_a, **_k: (invite, "plain-token"))
    monkeypatch.setattr(service, "list_invites", lambda *_a, **_k: [invite])
    monkeypatch.setattr(service, "revoke_invite", lambda *_a, **_k: invite)
    monkeypatch.setattr(service, "list_generations", lambda *_a, **_k: [generation])
    return TestClient(app), app, service


PRODUCT = {
    "name": "Catalog Wig",
    "category": "wig",
    "fixed_prompt": "Keep logo exact",
    "output_prompt": "Create catalog image",
    "options": [],
}


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/customer-image/customers", {}),
        ("get", "/api/customer-image/products", {}),
        ("post", "/api/customer-image/products", {"json": PRODUCT}),
        ("put", "/api/customer-image/products/1", {"json": PRODUCT}),
        ("delete", "/api/customer-image/products/1", {}),
        ("post", "/api/customer-image/products/1/publish", {}),
        ("get", "/api/customer-image/invites", {}),
        ("post", "/api/customer-image/invites", {"json": {"customer_id": "C1", "product_ids": [1], "expires_at": "2099-01-01T00:00:00Z", "quota_total": 5}}),
        ("post", "/api/customer-image/invites/2/revoke", {}),
        ("get", "/api/customer-image/generations", {}),
    ],
)
def test_every_internal_endpoint_returns_ok_envelope(api, method, path, kwargs):
    client, *_ = api
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"code", "message", "data"}


def test_create_invite_returns_plaintext_url_once_and_never_token_hash(api):
    client, *_ = api
    created = client.post(
        "/api/customer-image/invites",
        json={"customer_id": "C1", "product_ids": [1], "expires_at": "2099-01-01T00:00:00Z", "quota_total": 5},
    ).json()["data"]
    assert created["invite_url"] == "https://leshine.work/create/plain-token"
    assert "token_hash" not in str(created)
    assert "token_suffix" not in str(created)

    listed = client.get("/api/customer-image/invites").json()["data"]
    assert listed[0]["token_suffix"] == "abc123"
    assert "token_hash" not in str(listed)
    assert "plain-token" not in str(listed)


def test_generation_list_does_not_expose_prompts_or_pricing(api):
    body = api[0].get("/api/customer-image/generations").json()["data"]
    rendered = str(body)
    assert "prompt_snapshot" not in rendered
    assert "pricing_snapshot" not in rendered
    assert "never-return" not in rendered


def test_non_admin_product_reader_does_not_receive_internal_prompts(api):
    client, app, _service = api
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7",
        "roles": [],
        "permissions": ["customer_image:read"],
    }

    response = client.get("/api/customer-image/products")

    assert response.status_code == 200
    product = response.json()["data"][0]
    assert "fixed_prompt" not in product
    assert "output_prompt" not in product


def test_scope_conflict_maps_to_409(api, monkeypatch):
    client, _, service = api
    monkeypatch.setattr(
        service,
        "list_available_customers",
        lambda *_a, **_k: (_ for _ in ()).throw(service.CustomerScopeConflictError("bind OKKI")),
    )
    response = client.get("/api/customer-image/customers")
    assert response.status_code == 409
    assert "bind OKKI" in response.text
