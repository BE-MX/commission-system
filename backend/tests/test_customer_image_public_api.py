"""HTTP contract tests for invitation-authenticated customer image APIs."""

from datetime import datetime, timedelta
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import get_db
from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageInvite,
    CustomerImageInviteProduct,
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductAsset,
    CustomerImageProductOption,
)
from app.customer_image.token_service import issue_invite_token


def _png(color: str = "red") -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="PNG")
    return output.getvalue()


def _invite(db, *, customer="Acme", creator_id=7, starts=None, expires=None, revoked_at=None):
    now = datetime.utcnow()
    row = CustomerImageInvite(
        customer_id=customer.lower(),
        customer_name_snapshot=customer,
        created_by=creator_id,
        okki_salesperson_id_snapshot="1007",
        token_hash="",
        token_suffix="",
        starts_at=starts or now - timedelta(minutes=1),
        expires_at=expires or now + timedelta(days=1),
        quota_total=5,
        quota_used=2,
        revoked_at=revoked_at,
    )
    token, row = issue_invite_token(db, row)
    db.commit()
    db.refresh(row)
    return row, token


def _product(db, *, published=True, name="Catalog Wig"):
    product = CustomerImageProduct(
        name=name,
        category="wig",
        description="Visible description",
        fixed_prompt="hidden fixed prompt",
        output_prompt="hidden output prompt",
        is_published=published,
        created_by=7,
    )
    db.add(product)
    db.flush()
    option = CustomerImageProductOption(
        product_id=product.id,
        key="length",
        label="Length",
        control_type="single_choice",
        required=True,
        default_value="18",
    )
    db.add(option)
    db.flush()
    db.add(CustomerImageOptionValue(
        option_id=option.id,
        value="18",
        label="18 inch",
        prompt_fragment="hidden value prompt",
        is_active=True,
    ))
    db.commit()
    return product


@pytest.fixture
def public_api(db, tmp_path, monkeypatch):
    from app.customer_image import public_router

    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    public_router.logo_rate_limiter.clear()
    app = FastAPI()
    app.add_middleware(public_router.PublicSecurityHeadersMiddleware)
    app.include_router(public_router.router, prefix="/api/customer-image/public")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), db, tmp_path


def _assert_security_headers(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Invite {token}"}


@pytest.mark.parametrize("headers", [None, {}, {"Authorization": "Bearer abc"}, {"Authorization": "Invite"}])
def test_auth_rejects_missing_or_malformed_credentials_identically(public_api, headers):
    client, _db, _tmp = public_api
    response = client.get("/api/customer-image/public/context", headers=headers)
    assert response.status_code == 401
    assert response.json() == {
        "detail": "This invitation is unavailable. Please request a new link from your sales contact."
    }
    _assert_security_headers(response)


@pytest.mark.parametrize("state", ["invalid", "future", "expired", "revoked"])
def test_auth_rejects_every_unavailable_token_with_the_same_error(public_api, state):
    client, db, _tmp = public_api
    now = datetime.utcnow()
    if state == "invalid":
        token = "not-a-real-token"
    else:
        invite, token = _invite(
            db,
            starts=now + timedelta(hours=1) if state == "future" else now - timedelta(days=2),
            expires=now - timedelta(hours=1) if state == "expired" else now + timedelta(days=1),
            revoked_at=now if state == "revoked" else None,
        )
        assert invite.id
    response = client.get("/api/customer-image/public/context", headers=_auth(token))
    assert response.status_code == 401
    assert response.json()["detail"] == "This invitation is unavailable. Please request a new link from your sales contact."


def test_context_and_catalog_only_expose_invite_bound_published_data(public_api):
    client, db, _tmp = public_api
    invite, token = _invite(db)
    visible = _product(db)
    unbound = _product(db, name="Other Customer Product")
    unpublished = _product(db, published=False, name="Draft")
    db.add_all([
        CustomerImageInviteProduct(invite_id=invite.id, product_id=visible.id),
        CustomerImageInviteProduct(invite_id=invite.id, product_id=unpublished.id),
    ])
    db.commit()

    context = client.get("/api/customer-image/public/context", headers=_auth(token))
    catalog = client.get("/api/customer-image/public/products", headers=_auth(token))

    assert context.status_code == catalog.status_code == 200
    for response in (context, catalog):
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert context.json()["data"] == {
        "brand_name": "莱莎产品效果图",
        "customer_display_name": "Acme",
        "expires_at": invite.expires_at.isoformat(),
        "quota": {"total": 5, "used": 2, "remaining": 3},
        "current_logo": None,
        "visible_product_count": 1,
    }
    assert [row["id"] for row in catalog.json()["data"]] == [visible.id]
    rendered = catalog.text
    for secret in ("hidden fixed prompt", "hidden output prompt", "hidden value prompt", "storage_path", "token_hash"):
        assert secret not in rendered
    assert unbound.id not in [row["id"] for row in catalog.json()["data"]]


def test_unpublishing_product_hides_it_immediately(public_api):
    client, db, _tmp = public_api
    invite, token = _invite(db)
    product = _product(db)
    db.add(CustomerImageInviteProduct(invite_id=invite.id, product_id=product.id))
    db.commit()
    assert len(client.get("/api/customer-image/public/products", headers=_auth(token)).json()["data"]) == 1
    product.is_published = False
    db.commit()
    assert client.get("/api/customer-image/public/products", headers=_auth(token)).json()["data"] == []


def test_public_access_uses_invitation_scope_not_internal_owner_scope(public_api):
    client, db, _tmp = public_api
    invite, token = _invite(db, creator_id=99)
    product = _product(db)
    db.add(CustomerImageInviteProduct(invite_id=invite.id, product_id=product.id))
    db.commit()

    response = client.get("/api/customer-image/public/products", headers=_auth(token))

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == [product.id]


def test_product_content_requires_bound_published_product_and_current_asset(public_api):
    client, db, tmp_path = public_api
    invite, token = _invite(db)
    product = _product(db)
    other = _product(db, name="Other")
    db.add(CustomerImageInviteProduct(invite_id=invite.id, product_id=product.id))
    path = tmp_path / "cover.png"
    path.write_bytes(_png())
    cover = CustomerImageProductAsset(
        product_id=product.id, role="cover", storage_path="cover.png", mime_type="image/png",
        file_size=path.stat().st_size, width=32, height=24, sha256="a" * 64,
    )
    wrong = CustomerImageProductAsset(
        product_id=other.id, role="cover", storage_path="cover.png", mime_type="image/png",
        file_size=path.stat().st_size, width=32, height=24, sha256="b" * 64,
    )
    db.add_all([cover, wrong])
    db.commit()
    url = f"/api/customer-image/public/products/{product.id}/assets/{cover.id}/content"
    response = client.get(url, headers=_auth(token))
    assert response.status_code == 200
    assert response.content == _png()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(
        f"/api/customer-image/public/products/{product.id}/assets/{wrong.id}/content", headers=_auth(token)
    ).status_code == 404
    cover.retired_at = datetime.utcnow()
    db.commit()
    assert client.get(url, headers=_auth(token)).status_code == 404


def test_logo_replacement_preserves_old_asset_and_switches_current_pointer(public_api):
    client, db, _tmp = public_api
    invite, token = _invite(db)
    first = client.post(
        "/api/customer-image/public/logo", headers=_auth(token), files={"file": ("one.png", _png("red"), "image/png")}
    )
    second = client.post(
        "/api/customer-image/public/logo", headers=_auth(token), files={"file": ("two.png", _png("blue"), "image/png")}
    )
    assert first.status_code == second.status_code == 200
    first_id = first.json()["data"]["id"]
    second_id = second.json()["data"]["id"]
    db.expire_all()
    assert db.get(CustomerImageInvite, invite.id).current_logo_asset_id == second_id
    assert db.get(CustomerImageAsset, first_id) is not None
    old = client.get(f"/api/customer-image/public/assets/{first_id}/content", headers=_auth(token))
    assert old.status_code == 200
    with Image.open(BytesIO(old.content)) as image:
        assert image.size == (32, 24)
        assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)


def test_invite_asset_content_is_invite_scoped(public_api):
    client, db, tmp_path = public_api
    invite, token = _invite(db)
    other, _other_token = _invite(db, customer="Other")
    path = tmp_path / "other.png"
    path.write_bytes(_png())
    asset = CustomerImageAsset(
        invite_id=other.id, asset_type="generated", storage_path="other.png", mime_type="image/png",
        file_size=path.stat().st_size, width=32, height=24, sha256="c" * 64,
    )
    db.add(asset)
    db.commit()
    assert client.get(f"/api/customer-image/public/assets/{asset.id}/content", headers=_auth(token)).status_code == 404


def test_logo_write_rate_limit_keys_by_invite_and_trusted_real_ip(public_api, monkeypatch):
    from app.customer_image import public_router

    client, db, _tmp = public_api
    invite, token = _invite(db)
    monkeypatch.setattr(public_router.logo_rate_limiter, "limit", 1)
    headers = {**_auth(token), "X-Real-IP": "203.0.113.8"}
    assert client.post(
        "/api/customer-image/public/logo", headers=headers, files={"file": ("one.png", _png(), "image/png")}
    ).status_code == 200
    limited = client.post(
        "/api/customer-image/public/logo", headers=headers, files={"file": ("two.png", _png(), "image/png")}
    )
    assert limited.status_code == 429
    _assert_security_headers(limited)
    assert limited.json()["detail"] == "Too many logo uploads. Please wait one minute and try again."
    assert client.post(
        "/api/customer-image/public/logo",
        headers={**_auth(token), "X-Real-IP": "203.0.113.9"},
        files={"file": ("three.png", _png(), "image/png")},
    ).status_code == 200
    assert str(invite.token_hash) not in limited.text


def test_framework_422_and_public_404_include_security_headers(public_api):
    client, db, _tmp = public_api
    _invite_row, token = _invite(db)

    missing_file = client.post("/api/customer-image/public/logo", headers=_auth(token))
    missing_route = client.get("/api/customer-image/public/not-a-route", headers=_auth(token))

    assert missing_file.status_code == 400
    assert missing_route.status_code == 404
    _assert_security_headers(missing_file)
    _assert_security_headers(missing_route)


def test_unhandled_public_500_includes_security_headers(db, monkeypatch):
    from app.customer_image import public_router, service

    invite, token = _invite(db)
    app = FastAPI()
    app.add_middleware(public_router.PublicSecurityHeadersMiddleware)
    app.include_router(public_router.router, prefix="/api/customer-image/public")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(service, "list_public_products", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/customer-image/public/context", headers=_auth(token))

    assert response.status_code == 500
    _assert_security_headers(response)


def test_public_header_middleware_does_not_change_non_public_responses():
    from app.customer_image import public_router

    app = FastAPI()
    app.add_middleware(public_router.PublicSecurityHeadersMiddleware)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert "cache-control" not in response.headers
    assert "referrer-policy" not in response.headers
    assert "x-content-type-options" not in response.headers


def test_logo_upload_reads_at_most_limit_plus_one_byte():
    from app.customer_image.public_router import read_upload_content

    class TrackingBytesIO(BytesIO):
        requested_size = None

        def read(self, size=-1):
            self.requested_size = size
            return super().read(size)

    stream = TrackingBytesIO(b"1234")
    assert read_upload_content(stream, 4) == b"1234"
    assert stream.requested_size == 5


def test_oversized_logo_returns_413_before_decode_or_storage(public_api, monkeypatch):
    from app.customer_image import file_service, public_router

    client, db, tmp_path = public_api
    _invite_row, token = _invite(db)
    monkeypatch.setattr(file_service, "effective_max_upload_bytes", lambda: 4)
    decode_called = False

    def unexpected_decode(*_args):
        nonlocal decode_called
        decode_called = True
        raise AssertionError("oversized upload reached decoder")

    monkeypatch.setattr(file_service, "normalize_upload", unexpected_decode)
    response = client.post(
        "/api/customer-image/public/logo",
        headers=_auth(token),
        files={"file": ("logo.png", b"12345", "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Logo image cannot exceed 4 bytes."
    _assert_security_headers(response)
    assert decode_called is False
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.parametrize("token", [None, "invalid"])
def test_unavailable_invite_does_not_parse_multipart(public_api, monkeypatch, token):
    from starlette.requests import Request

    client, _db, _tmp = public_api
    form_calls = 0
    original_form = Request.form

    def track_form(self, **kwargs):
        nonlocal form_calls
        form_calls += 1
        return original_form(self, **kwargs)

    monkeypatch.setattr(Request, "form", track_form)
    response = client.post(
        "/api/customer-image/public/logo",
        headers=_auth(token) if token else {},
        files={"file": ("large.bin", b"x" * 4096, "application/octet-stream")},
    )

    assert response.status_code == 401
    assert form_calls == 0


def test_rate_limit_rejects_before_second_multipart_parse(public_api, monkeypatch):
    from app.customer_image import public_router
    from starlette.requests import Request

    client, db, _tmp = public_api
    _invite_row, token = _invite(db)
    monkeypatch.setattr(public_router.logo_rate_limiter, "limit", 1)
    form_calls = 0
    original_form = Request.form

    def track_form(self, **kwargs):
        nonlocal form_calls
        form_calls += 1
        return original_form(self, **kwargs)

    monkeypatch.setattr(Request, "form", track_form)
    headers = {**_auth(token), "X-Real-IP": "198.51.100.7"}
    first = client.post(
        "/api/customer-image/public/logo",
        headers=headers,
        files={"file": ("one.png", _png(), "image/png")},
    )
    second = client.post(
        "/api/customer-image/public/logo",
        headers=headers,
        files={"file": ("two.png", b"x" * 4096, "application/octet-stream")},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert form_calls == 1


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"content": b"not multipart", "headers": {"Content-Type": "multipart/form-data; boundary=broken"}},
        {"files": [("file", ("one.png", _png(), "image/png")), ("file", ("two.png", _png(), "image/png"))]},
        {"files": {"other": ("one.png", _png(), "image/png")}},
    ],
)
def test_valid_invite_rejects_malformed_or_non_unique_file_form(public_api, request_kwargs):
    client, db, _tmp = public_api
    _invite_row, token = _invite(db)
    headers = {**request_kwargs.pop("headers", {}), **_auth(token)}
    response = client.post("/api/customer-image/public/logo", headers=headers, **request_kwargs)
    assert response.status_code == 400
    _assert_security_headers(response)


def test_logo_commit_failure_removes_new_files_and_keeps_pointer(public_api, monkeypatch):
    client, db, tmp_path = public_api
    invite, token = _invite(db)
    original_commit = db.commit

    def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db, "commit", fail_commit)
    response = client.post(
        "/api/customer-image/public/logo",
        headers=_auth(token),
        files={"file": ("logo.png", _png(), "image/png")},
    )
    assert response.status_code == 500
    _assert_security_headers(response)
    monkeypatch.setattr(db, "commit", original_commit)
    db.expire_all()
    assert db.get(CustomerImageInvite, invite.id).current_logo_asset_id is None
    assert list(tmp_path.rglob("*.png")) == []
