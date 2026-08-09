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
        "role": "cover",
        "position": 0,
        "mime_type": "image/png",
        "file_size": 123,
        "width": 12,
        "height": 8,
        "retired_at": None,
        "values": [SimpleNamespace(
            id=12, value="18", label="18 inch", prompt_fragment="hidden value prompt",
            color_hex=None, pantone_code=None, sort=0, is_active=True,
        )],
        "key": "length",
        "label": "Length",
        "control_type": "single_choice",
        "required": True,
        "default_value": "18",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def api(monkeypatch):
    from app.customer_image import router as module
    from app.customer_image import service
    from app.design_image import library_service

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
    product.options = [_row(id=11)]
    invite = _row(id=2)
    generation = _row(id=3, invite_id=2)
    asset = _row(id=4, product_id=1)
    public_library = _row(id=9, scope="public", owner_user_id=8, title="Public")
    private_library = _row(id=10, scope="private", owner_user_id=7, title="Mine")
    monkeypatch.setattr(service, "list_products", lambda *_a, **_k: [product])
    monkeypatch.setattr(service, "list_current_product_covers", lambda *_a, **_k: {1: asset})
    monkeypatch.setattr(service, "get_current_product_cover", lambda *_a, **_k: asset)
    monkeypatch.setattr(service, "create_product", lambda *_a, **_k: product)
    monkeypatch.setattr(service, "update_product", lambda *_a, **_k: product)
    monkeypatch.setattr(service, "delete_product", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "publish_product", lambda *_a, **_k: product)
    monkeypatch.setattr(service, "unpublish_product", lambda *_a, **_k: _row(is_published=False))
    monkeypatch.setattr(service, "list_current_product_assets", lambda *_a, **_k: [asset])
    monkeypatch.setattr(service, "get_current_product_asset", lambda *_a, **_k: asset)
    monkeypatch.setattr(service, "retire_product_reference", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "reorder_product_references", lambda *_a, **_k: [asset])
    monkeypatch.setattr(service, "get_product", lambda *_a, **_k: product)
    monkeypatch.setattr(
        library_service,
        "list_library_assets",
        lambda _db, _owner, scope: [public_library] if scope == "public" else [private_library],
    )
    monkeypatch.setattr(service, "list_available_customers", lambda *_a, **_k: [{"id": "C1"}])
    monkeypatch.setattr(service, "create_invite", lambda *_a, **_k: (invite, "plain-token"))
    monkeypatch.setattr(service, "list_invites", lambda *_a, **_k: ([invite], 1))
    monkeypatch.setattr(service, "revoke_invite", lambda *_a, **_k: invite)
    monkeypatch.setattr(service, "list_generations", lambda *_a, **_k: ([generation], 1))
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
        ("post", "/api/customer-image/products/1/unpublish", {}),
        ("get", "/api/customer-image/products/1/assets", {}),
        ("delete", "/api/customer-image/products/1/references/4", {}),
        ("put", "/api/customer-image/products/1/references/order", {"json": {"asset_ids": [4]}}),
        ("get", "/api/customer-image/library-assets", {}),
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

    listed = client.get("/api/customer-image/invites").json()["data"]["items"]
    assert listed[0]["token_suffix"] == "abc123"
    assert "token_hash" not in str(listed)
    assert "plain-token" not in str(listed)


def test_generation_list_does_not_expose_prompts_or_pricing(api):
    body = api[0].get("/api/customer-image/generations").json()["data"]["items"]
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
    assert "prompt_fragment" not in str(product)
    assert product["cover"] == {
        "id": 4,
        "mime_type": "image/png",
        "file_size": 123,
        "width": 12,
        "height": 8,
        "content_url": "/api/customer-image/products/1/cover",
    }


def test_write_only_salesperson_can_read_safe_products_and_owned_invites(api):
    client, app, _service = api
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["customer_image:write"],
    }

    products = client.get("/api/customer-image/products")
    invites = client.get("/api/customer-image/invites")
    customers = client.get("/api/customer-image/customers?search=Acme")
    created = client.post(
        "/api/customer-image/invites",
        json={"customer_id": "C1", "product_ids": [1], "expires_at": "2099-01-01T00:00:00Z", "quota_total": 2},
    )
    revoked = client.post("/api/customer-image/invites/2/revoke")

    assert products.status_code == invites.status_code == customers.status_code == 200
    assert created.status_code == revoked.status_code == 200
    rendered = products.text
    assert "private fixed prompt" not in rendered
    assert "private output prompt" not in rendered
    assert "hidden value prompt" not in rendered
    assert "storage_path" not in rendered


def test_safe_cover_endpoint_returns_only_current_cover_binary(api, monkeypatch):
    client, app, service = api
    from app.customer_image import file_service
    import io

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["customer_image:write"],
    }
    cover = _row(id=4, product_id=1, role="cover", retired_at=None)
    captured = []
    stream = io.BytesIO(b"safe-cover")
    monkeypatch.setattr(service, "get_current_product_cover", lambda _db, product_id, **_kwargs: cover)
    monkeypatch.setattr(
        file_service,
        "open_product_asset_content",
        lambda _db, product_id, asset_id: captured.append((product_id, asset_id)) or stream,
    )

    response = client.get("/api/customer-image/products/1/cover")

    assert response.status_code == 200
    assert response.content == b"safe-cover"
    assert response.headers["cache-control"] == "private, no-store"
    assert captured == [(1, 4)]
    assert response.is_success
    assert stream.closed is True


def test_product_asset_json_endpoints_never_return_storage_path(api, monkeypatch):
    client, _app, service = api
    from app.customer_image import file_service

    asset = _row(id=4, storage_path="private/secret.png")
    monkeypatch.setattr(file_service, "replace_product_asset_from_upload", lambda *_a, **_k: asset)
    monkeypatch.setattr(file_service, "replace_product_asset_from_library", lambda *_a, **_k: asset)

    listed = client.get("/api/customer-image/products/1/assets")
    uploaded = client.post(
        "/api/customer-image/products/1/assets/upload",
        data={"role": "cover", "position": "0"},
        files={"file": ("cover.png", b"png", "image/png")},
    )
    copied = client.post(
        "/api/customer-image/products/1/assets/library",
        json={"source_asset_id": 9, "role": "reference", "position": 0},
    )
    for response in (listed, uploaded, copied):
        assert response.status_code == 200, response.text
        assert set(response.json()) == {"code", "message", "data"}
        assert "storage_path" not in response.text


def test_customer_image_admin_without_design_image_read_can_browse_library(api):
    client, app, _service = api
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7",
        "roles": [],
        "permissions": ["customer_image:admin"],
    }

    response = client.get("/api/customer-image/library-assets")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [(item["id"], item["scope"]) for item in items] == [(10, "private"), (9, "public")]
    assert "storage_path" not in response.text


def test_customer_image_library_thumbnail_is_private_binary(api, monkeypatch):
    client, app, _service = api
    from app.design_image import library_service, service as design_service
    import io

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["customer_image:admin"]
    }
    captured = []
    stream = io.BytesIO(b"thumb")
    monkeypatch.setattr(
        library_service,
        "open_library_asset_content",
        lambda _db, owner, asset_id, thumbnail: captured.append((owner, asset_id, thumbnail))
        or design_service.AssetContent(stream, "image/png", ".png"),
    )

    response = client.get("/api/customer-image/library-assets/10/content?thumbnail=true")

    assert response.status_code == 200
    assert response.content == b"thumb"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert captured == [(7, 10, True)]
    assert stream.closed is True


def test_product_asset_content_is_private_binary(api, monkeypatch):
    client, _app, _service = api
    from app.customer_image import file_service
    import io

    stream = io.BytesIO(b"png")
    monkeypatch.setattr(file_service, "open_product_asset_content", lambda *_a, **_k: stream)
    response = client.get("/api/customer-image/products/1/assets/4/content")
    assert response.status_code == 200
    assert response.content == b"png"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert stream.closed is True


def test_missing_library_or_product_asset_maps_to_404(api, monkeypatch):
    client, _app, _service = api
    from app.customer_image import file_service

    monkeypatch.setattr(
        file_service,
        "replace_product_asset_from_library",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("library asset not found")),
    )
    copied = client.post(
        "/api/customer-image/products/1/assets/library",
        json={"source_asset_id": 999, "role": "cover", "position": 0},
    )
    monkeypatch.setattr(
        file_service,
        "open_product_asset_content",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("product asset not found")),
    )
    content = client.get("/api/customer-image/products/1/assets/999/content")
    assert copied.status_code == 404
    assert content.status_code == 404


def test_admin_product_response_keeps_all_prompt_fragments(api):
    product = api[0].get("/api/customer-image/products").json()["data"][0]
    assert product["fixed_prompt"] == "private fixed prompt"
    assert product["output_prompt"] == "private output prompt"
    assert product["options"][0]["values"][0]["prompt_fragment"] == "hidden value prompt"


def test_list_pagination_has_hard_caps_and_page_envelope(api):
    client, *_ = api
    for path in ("invites", "generations"):
        body = client.get(f"/api/customer-image/{path}?page=2&page_size=100").json()["data"]
        assert set(body) == {"items", "total", "page", "page_size"}
        assert body["page"] == 2
        assert body["page_size"] == 100
        assert client.get(f"/api/customer-image/{path}?page_size=101").status_code == 422
    assert client.get("/api/customer-image/customers").json()["data"] == []


@pytest.mark.parametrize("path", ["products", "invites", "generations"])
def test_admin_permission_alone_can_read_management_lists(api, path):
    client, app, _service = api
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["customer_image:admin"]
    }

    assert client.get(f"/api/customer-image/{path}").status_code == 200


def test_scope_conflict_maps_to_409(api, monkeypatch):
    client, _, service = api
    monkeypatch.setattr(
        service,
        "list_available_customers",
        lambda *_a, **_k: (_ for _ in ()).throw(service.CustomerScopeConflictError("bind OKKI")),
    )
    response = client.get("/api/customer-image/customers?search=Acme")
    assert response.status_code == 409
    assert "bind OKKI" in response.text


def test_image_errors_map_to_precise_statuses(api, monkeypatch):
    client, _app, _service = api
    from app.customer_image import file_service

    cases = [
        (file_service.shared_files.ImageValidationError("bad image"), 400),
        (file_service.shared_files.ImageStorageError("storage failed"), 503),
        (OSError("disk failed"), 503),
    ]
    for error, expected in cases:
        monkeypatch.setattr(
            file_service,
            "replace_product_asset_from_upload",
            lambda *_a, _error=error, **_k: (_ for _ in ()).throw(_error),
        )
        response = client.post(
            "/api/customer-image/products/1/assets/upload",
            data={"role": "cover", "position": "0"},
            files={"file": ("cover.png", b"png", "image/png")},
        )
        assert response.status_code == expected
