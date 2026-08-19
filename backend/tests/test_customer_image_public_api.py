"""HTTP contract tests for invitation-authenticated customer image APIs."""

from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.ai.models import AiPreset, AiProvider
from app.core.database import get_db
from app.customer_image.models import (
    CustomerImageAsset,
    CustomerImageGeneration,
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


def _ready_generation_context(db):
    invite, token = _invite(db)
    product = _product(db)
    db.add(CustomerImageInviteProduct(invite_id=invite.id, product_id=product.id))
    logo = CustomerImageAsset(
        invite_id=invite.id,
        asset_type="logo",
        storage_path="customer-logo/hidden-logo.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="d" * 64,
    )
    reference = CustomerImageProductAsset(
        product_id=product.id,
        role="reference",
        storage_path="customer-product/hidden-reference.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="e" * 64,
    )
    provider = AiProvider(
        name="Customer portal provider",
        provider_type="direct",
        api_base="https://images.example.test/v1",
        api_key="encrypted-provider-secret",
        api_type="openai",
        is_enabled=True,
    )
    db.add_all([logo, reference, provider])
    db.flush()
    invite.current_logo_asset_id = logo.id
    db.add(AiPreset(
        preset_name="design_image_generation",
        provider_id=provider.id,
        model="gpt-image-2",
        parameters={
            "size": "1536x1024",
            "quality": "high",
            "download_hosts": ["cdn.example.test"],
            "rate_card": {"output_image_per_million": "40"},
        },
        is_enabled=True,
    ))
    db.commit()
    return invite, token, product


@pytest.fixture
def public_api(db, tmp_path, monkeypatch):
    from app.customer_image import public_router

    monkeypatch.setattr("app.design_image.file_service._storage_root", lambda: tmp_path)
    public_router.logo_rate_limiter.clear()
    public_router.generation_rate_limiter.clear()
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
    assert catalog.json()["data"][0]["config_version"] == visible.config_version
    rendered = catalog.text
    for secret in ("hidden fixed prompt", "hidden output prompt", "hidden value prompt", "storage_path", "token_hash"):
        assert secret not in rendered
    assert unbound.id not in [row["id"] for row in catalog.json()["data"]]


def test_generation_submit_returns_202_and_replay_is_safe(public_api):
    client, db, _tmp = public_api
    invite, token, product = _ready_generation_context(db)
    payload = {
        "product_id": product.id,
        "config_version": product.config_version,
        "request_id": "browser-request-1",
        "selections": {"length": "18"},
        "requirement": "  Put it on a clean studio background.  ",
    }

    first = client.post(
        "/api/customer-image/public/generations", headers=_auth(token), json=payload
    )
    replay = client.post(
        "/api/customer-image/public/generations", headers=_auth(token), json=payload
    )

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert first.json()["data"] == {
        "id": first.json()["data"]["id"],
        "product_id": product.id,
        "product_name": "Catalog Wig",
        "status": "queued",
        "selections": [
            {"key": "length", "label": "Length", "value": "18", "value_label": "18 inch"}
        ],
        "result_url": None,
        "error_message": None,
        "created_at": first.json()["data"]["created_at"],
        "started_at": None,
        "finished_at": None,
    }
    db.expire_all()
    assert db.get(CustomerImageInvite, invite.id).quota_used == 3
    assert db.query(CustomerImageGeneration).count() == 1
    for hidden in (
        "clean studio background",
        "hidden fixed prompt",
        "hidden output prompt",
        "hidden value prompt",
        "hidden-logo.png",
        "hidden-reference.png",
        "provider_id",
        "pricing_snapshot",
        "encrypted-provider-secret",
    ):
        assert hidden not in first.text


def test_generation_list_and_detail_are_newest_first_invite_scoped_and_safe(public_api):
    client, db, _tmp = public_api
    invite, token, product = _ready_generation_context(db)
    payload = {
        "product_id": product.id,
        "config_version": product.config_version,
        "selections": {"length": "18"},
    }
    first = client.post(
        "/api/customer-image/public/generations",
        headers=_auth(token),
        json={**payload, "request_id": "history-1", "requirement": "private one"},
    ).json()["data"]
    second = client.post(
        "/api/customer-image/public/generations",
        headers=_auth(token),
        json={**payload, "request_id": "history-2", "requirement": "private two"},
    ).json()["data"]
    output = CustomerImageAsset(
        invite_id=invite.id,
        asset_type="generated",
        storage_path="customer-output/secret-result.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="f" * 64,
    )
    db.add(output)
    db.flush()
    first_row = db.get(CustomerImageGeneration, first["id"])
    first_row.status = "succeeded"
    first_row.output_asset_id = output.id
    first_row.error_message = "raw provider detail must never appear"
    db.commit()

    history = client.get(
        "/api/customer-image/public/generations", headers=_auth(token)
    )
    detail = client.get(
        f"/api/customer-image/public/generations/{first['id']}", headers=_auth(token)
    )
    other_invite, other_token = _invite(db, customer="Other")
    assert other_invite.id != invite.id
    wrong_owner = client.get(
        f"/api/customer-image/public/generations/{first['id']}", headers=_auth(other_token)
    )

    assert history.status_code == detail.status_code == 200
    assert [row["id"] for row in history.json()["data"]] == [second["id"], first["id"]]
    assert detail.json()["data"]["result_url"] == (
        f"/api/customer-image/public/assets/{output.id}/content"
    )
    assert detail.json()["data"]["error_message"] is None
    assert wrong_owner.status_code == 404
    rendered = history.text + detail.text
    for hidden in (
        "private one",
        "private two",
        "raw provider detail",
        "secret-result.png",
        "prompt_snapshot",
        "parameters_snapshot",
        "pricing_snapshot",
    ):
        assert hidden not in rendered


def test_generation_submission_returns_only_stable_actionable_errors(public_api):
    client, db, _tmp = public_api
    invite, token, product = _ready_generation_context(db)
    payload = {
        "product_id": product.id,
        "config_version": product.config_version + 1,
        "request_id": "stale-product",
        "selections": {"length": "18"},
    }

    stale = client.post(
        "/api/customer-image/public/generations", headers=_auth(token), json=payload
    )
    invite.current_logo_asset_id = None
    db.commit()
    no_logo = client.post(
        "/api/customer-image/public/generations",
        headers=_auth(token),
        json={**payload, "config_version": product.config_version, "request_id": "no-logo"},
    )
    db.refresh(invite)
    logo = db.query(CustomerImageAsset).filter(
            CustomerImageAsset.invite_id == invite.id,
            CustomerImageAsset.asset_type == "logo",
        ).one()
    invite.current_logo_asset_id = logo.id
    invite.quota_used = invite.quota_total
    db.commit()
    exhausted = client.post(
        "/api/customer-image/public/generations",
        headers=_auth(token),
        json={**payload, "config_version": product.config_version, "request_id": "no-quota"},
    )

    assert (stale.status_code, stale.json()["detail"]) == (
        409,
        "Product settings changed. Please choose again.",
    )
    assert (no_logo.status_code, no_logo.json()["detail"]) == (
        409,
        "Upload a logo before generating.",
    )
    assert (exhausted.status_code, exhausted.json()["detail"]) == (
        409,
        "Generation quota is exhausted.",
    )
    rendered = stale.text + no_logo.text + exhausted.text
    for hidden in (
        "prompt",
        "provider",
        "storage_path",
        "token_hash",
        "encrypted-provider-secret",
    ):
        assert hidden not in rendered


def test_generation_rate_limit_precedes_quota_and_isolates_invite_and_ip(
    public_api, monkeypatch
):
    from app.customer_image import public_router

    client, db, _tmp = public_api
    invite, token, product = _ready_generation_context(db)
    other_invite, other_token = _invite(db, customer="Other")
    other_logo = CustomerImageAsset(
        invite_id=other_invite.id,
        asset_type="logo",
        storage_path="customer-logo/other.png",
        mime_type="image/png",
        file_size=10,
        width=32,
        height=24,
        sha256="9" * 64,
    )
    db.add(other_logo)
    db.flush()
    other_invite.current_logo_asset_id = other_logo.id
    db.add(CustomerImageInviteProduct(invite_id=other_invite.id, product_id=product.id))
    db.commit()
    monkeypatch.setattr(public_router.generation_rate_limiter, "limit", 1)
    payload = {
        "product_id": product.id,
        "config_version": product.config_version,
        "selections": {"length": "18"},
    }
    first_ip = {**_auth(token), "X-Real-IP": "203.0.113.20"}

    accepted = client.post(
        "/api/customer-image/public/generations",
        headers=first_ip,
        json={**payload, "request_id": "limited-1"},
    )
    limited = client.post(
        "/api/customer-image/public/generations",
        headers=first_ip,
        json={**payload, "request_id": "limited-2"},
    )
    other_ip = client.post(
        "/api/customer-image/public/generations",
        headers={**_auth(token), "X-Real-IP": "203.0.113.21"},
        json={**payload, "request_id": "limited-3"},
    )
    other_invite_response = client.post(
        "/api/customer-image/public/generations",
        headers={**_auth(other_token), "X-Real-IP": "203.0.113.20"},
        json={**payload, "request_id": "limited-4"},
    )

    assert accepted.status_code == other_ip.status_code == other_invite_response.status_code == 202
    assert limited.status_code == 429
    assert limited.json()["detail"] == (
        "Too many generation requests. Please wait one minute and try again."
    )
    _assert_security_headers(limited)
    db.expire_all()
    assert db.get(CustomerImageInvite, invite.id).quota_used == 4
    assert db.get(CustomerImageInvite, other_invite.id).quota_used == 3
    assert db.query(CustomerImageGeneration).count() == 3


def test_dynamic_requirement_limit_returns_stable_400_without_quota_use(
    public_api, monkeypatch
):
    from app.customer_image import service

    client, db, _tmp = public_api
    invite, token, product = _ready_generation_context(db)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            CUSTOMER_IMAGE_PRESET_NAME="design_image_generation",
            CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS=5,
        ),
    )

    response = client.post(
        "/api/customer-image/public/generations",
        headers=_auth(token),
        json={
            "product_id": product.id,
            "config_version": product.config_version,
            "request_id": "requirement-too-long",
            "selections": {"length": "18"},
            "requirement": "123456",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Additional requirement is too long."
    _assert_security_headers(response)
    db.expire_all()
    assert db.get(CustomerImageInvite, invite.id).quota_used == 2
    assert db.query(CustomerImageGeneration).count() == 0


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


def test_public_logo_upload_does_not_enable_dieline_documents(public_api):
    client, db, _tmp_path = public_api
    _invite_row, token = _invite(db)

    response = client.post(
        "/api/customer-image/public/logo",
        headers=_auth(token),
        files={"file": ("dieline.pdf", b"%PDF-1.7\n", "application/pdf")},
    )

    assert response.status_code == 400
    assert "MIME" in response.text
    _assert_security_headers(response)


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
