"""Exact authorization and owner-scope contract for customer image management."""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.customer_image.models import (
    CustomerImageGeneration,
    CustomerImageInvite,
    CustomerImageInviteProduct,
    CustomerImageProduct,
    CustomerImageProductAsset,
)
from app.customer_image.schemas import CustomerImageInviteCreate
from app.auth.models import ArkUserExternalBinding
from sqlalchemy import text


EXPECTED = {
    ("get", "/customers"): ("require_permission", ("customer_image:write",)),
    ("get", "/products"): ("require_any_permission", ("customer_image:read", "customer_image:write", "customer_image:admin")),
    ("get", "/products/{product_id}/cover"): ("require_any_permission", ("customer_image:read", "customer_image:write", "customer_image:admin")),
    ("post", "/products"): ("require_permission", ("customer_image:admin",)),
    ("put", "/products/{product_id}"): ("require_permission", ("customer_image:admin",)),
    ("delete", "/products/{product_id}"): ("require_permission", ("customer_image:admin",)),
    ("post", "/products/{product_id}/publish"): ("require_permission", ("customer_image:admin",)),
    ("post", "/products/{product_id}/unpublish"): ("require_permission", ("customer_image:admin",)),
    ("get", "/products/{product_id}/assets"): ("require_permission", ("customer_image:admin",)),
    ("post", "/products/{product_id}/assets/upload"): ("require_permission", ("customer_image:admin",)),
    ("post", "/products/{product_id}/assets/library"): ("require_permission", ("customer_image:admin",)),
    ("post", "/products/{product_id}/references/upload"): ("require_permission", ("customer_image:admin",)),
    ("post", "/products/{product_id}/references/library"): ("require_permission", ("customer_image:admin",)),
    ("delete", "/products/{product_id}/references/{asset_id}"): ("require_permission", ("customer_image:admin",)),
    ("put", "/products/{product_id}/references/order"): ("require_permission", ("customer_image:admin",)),
    ("get", "/products/{product_id}/assets/{asset_id}/content"): ("require_permission", ("customer_image:admin",)),
    ("get", "/library-assets"): ("require_permission", ("customer_image:admin",)),
    ("get", "/library-assets/{asset_id}/content"): ("require_permission", ("customer_image:admin",)),
    ("get", "/invites"): ("require_any_permission", ("customer_image:read", "customer_image:write", "customer_image:admin")),
    ("post", "/invites"): ("require_permission", ("customer_image:write",)),
    ("post", "/invites/{invite_id}/revoke"): ("require_permission", ("customer_image:write",)),
    ("get", "/generations"): ("require_any_permission", ("customer_image:read", "customer_image:admin")),
}


def test_router_has_exact_permission_dependency_per_endpoint():
    source = (Path(__file__).parents[1] / "app/customer_image/router.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    actual = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route = next((item for item in node.decorator_list if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and isinstance(item.func.value, ast.Name) and item.func.value.id == "router"), None)
        if route is None:
            continue
        calls = [
            item for item in ast.walk(node)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id in {"require_permission", "require_any_permission"}
        ]
        assert len(calls) == 1, node.name
        actual[(route.func.attr, route.args[0].value)] = (
            calls[0].func.id,
            tuple(argument.value for argument in calls[0].args),
        )
    assert actual == EXPECTED


@pytest.mark.parametrize("method,path,kwargs", [
        ("get", "/customers", {}), ("get", "/products", {}), ("get", "/products/1/cover", {}),
        ("post", "/products", {"json": {}}), ("put", "/products/1", {"json": {}}),
        ("delete", "/products/1", {}),
        ("post", "/products/1/publish", {}), ("get", "/invites", {}),
        ("post", "/products/1/unpublish", {}),
        ("get", "/products/1/assets", {}),
        ("post", "/products/1/assets/upload", {"data": {"role": "cover", "position": "0"}, "files": {"file": ("x.png", b"x", "image/png")}}),
        ("post", "/products/1/assets/library", {"json": {"source_asset_id": 1, "role": "cover", "position": 0}}),
        ("post", "/products/1/references/upload", {"files": {"file": ("x.png", b"x", "image/png")}}),
        ("post", "/products/1/references/library", {"json": {"source_asset_id": 1}}),
        ("delete", "/products/1/references/1", {}),
        ("put", "/products/1/references/order", {"json": {"asset_ids": [1]}}),
        ("get", "/products/1/assets/1/content", {}),
        ("get", "/library-assets", {}),
        ("get", "/library-assets/1/content", {}),
    ("post", "/invites", {"json": {}}), ("post", "/invites/1/revoke", {}),
    ("get", "/generations", {}),
])
def test_wrong_permission_is_rejected_before_business_validation(method, path, kwargs):
    from app.customer_image.router import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "7", "roles": [], "permissions": ["customer_image:wrong"]}
    response = getattr(TestClient(app), method)(path, **kwargs)
    assert response.status_code == 403


def _invite(db, *, owner, suffix):
    now = datetime.now(UTC).replace(tzinfo=None)
    row = CustomerImageInvite(
        customer_id=f"C{owner}", customer_name_snapshot=f"Customer {owner}", created_by=owner,
        okki_salesperson_id_snapshot=str(owner), token_hash=suffix * 32, token_suffix=suffix,
        starts_at=now, expires_at=now + timedelta(days=1), quota_total=2,
    )
    db.add(row)
    db.flush()
    return row


def test_non_admin_invite_and_generation_lists_are_created_by_scoped(db):
    from app.customer_image.service import list_generations, list_invites
    product = CustomerImageProduct(name="P", category="wig", fixed_prompt="x", output_prompt="y", created_by=1)
    db.add(product)
    db.flush()
    own = _invite(db, owner=7, suffix="aaaaaa")
    other = _invite(db, owner=8, suffix="bbbbbb")
    db.add_all([
        CustomerImageGeneration(invite_id=own.id, product_id=product.id, logo_asset_id=1, request_id="own", product_name_snapshot="P", config_version_snapshot=1, option_snapshot={}, prompt_snapshot="x", reference_asset_ids=[], preset_name="p"),
        CustomerImageGeneration(invite_id=other.id, product_id=product.id, logo_asset_id=1, request_id="other", product_name_snapshot="P", config_version_snapshot=1, option_snapshot={}, prompt_snapshot="x", reference_asset_ids=[], preset_name="p"),
    ])
    db.commit()
    assert [row.id for row in list_invites(db, 7, False, 1, 20)[0]] == [own.id]
    assert [row.request_id for row in list_generations(db, 7, False, 1, 20)[0]] == ["own"]
    assert {row.id for row in list_invites(db, 99, True, 1, 20)[0]} == {own.id, other.id}


def test_invite_and_generation_pagination_never_returns_over_page_size(db):
    from app.customer_image.service import list_generations, list_invites
    product = CustomerImageProduct(name="P", category="wig", fixed_prompt="x", output_prompt="y", created_by=1)
    db.add(product)
    db.flush()
    for index in range(5):
        invite = _invite(db, owner=7, suffix=f"a{index:05d}")
        db.add(CustomerImageGeneration(invite_id=invite.id, product_id=product.id, logo_asset_id=1, request_id=f"r{index}", product_name_snapshot="P", config_version_snapshot=1, option_snapshot={}, prompt_snapshot="x", reference_asset_ids=[], preset_name="p"))
    db.commit()
    invites, invite_total = list_invites(db, 7, False, 1, 2)
    generations, generation_total = list_generations(db, 7, False, 2, 2)
    assert len(invites) == len(generations) == 2
    assert invite_total == generation_total == 5


def test_non_admin_cross_owner_revoke_is_404(db):
    from app.customer_image.service import CustomerImageNotFoundError, revoke_invite
    other = _invite(db, owner=8, suffix="cccccc")
    db.commit()
    with pytest.raises(CustomerImageNotFoundError):
        revoke_invite(db, other.id, 7, False)
    assert other.revoked_at is None


def test_create_invite_persists_only_digest_and_published_product_links(db):
    from app.customer_image.service import create_invite
    db.execute(
        text(
            "INSERT INTO lsordertest.customer_info "
            "(company_id, company_name, owner_user_ids) "
            "VALUES ('C7', 'Owned', '[1007]')"
        )
    )
    db.add(ArkUserExternalBinding(ark_user_id=7, provider="okki", external_account_id="1007", binding_status="active", is_primary=True))
    product = CustomerImageProduct(name="P", category="wig", fixed_prompt="x", output_prompt="y", created_by=1, is_published=True)
    db.add(product)
    db.commit()

    invite, plaintext = create_invite(
        db,
        creator_id=7,
        is_admin=False,
        payload=CustomerImageInviteCreate(customer_id="C7", product_ids=[product.id], expires_at="2099-01-01T00:00:00Z", quota_total=3),
    )

    assert plaintext not in repr(invite.__dict__)
    assert invite.token_hash != plaintext
    assert invite.token_suffix == plaintext[-6:]
    assert [link.product_id for link in db.query(CustomerImageInviteProduct).all()] == [product.id]


def test_admin_invite_snapshots_customers_live_okki_owner_without_own_binding(db):
    from app.customer_image.service import create_invite

    db.execute(text(
        "INSERT INTO lsordertest.customer_info "
        "(company_id, company_name, owner_user_ids) "
        "VALUES ('CA', 'Admin Customer', '[2008]')"
    ))
    product = CustomerImageProduct(name="P", category="wig", fixed_prompt="x", output_prompt="y", created_by=1, is_published=True)
    db.add(product)
    db.commit()

    invite, _plaintext = create_invite(
        db,
        creator_id=99,
        is_admin=True,
        payload=CustomerImageInviteCreate(customer_id="CA", product_ids=[product.id], expires_at="2099-01-01T00:00:00Z", quota_total=1),
    )

    assert invite.okki_salesperson_id_snapshot == "2008"


def test_unpublish_hides_product_state_and_asset_list_excludes_retired(db):
    from app.customer_image.service import list_current_product_assets, unpublish_product
    from app.customer_image.models import CustomerImageProductAsset

    product = CustomerImageProduct(name="P", category="wig", fixed_prompt="x", output_prompt="y", created_by=1, is_published=True)
    db.add(product)
    db.flush()
    current = CustomerImageProductAsset(product_id=product.id, role="cover", position=0, storage_path="current.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="a" * 64)
    retired = CustomerImageProductAsset(product_id=product.id, role="cover", position=1, storage_path="retired.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="b" * 64, retired_at=datetime.now(UTC).replace(tzinfo=None))
    db.add_all([current, retired])
    db.commit()

    assert unpublish_product(db, product.id).is_published is False
    assert [row.id for row in list_current_product_assets(db, product.id)] == [current.id]


def test_safe_cover_queries_exclude_reference_retired_and_non_primary_assets(db):
    from app.customer_image.models import CustomerImageProductAsset
    from app.customer_image.service import (
        CustomerImageNotFoundError,
        get_current_product_cover,
        list_current_product_covers,
    )

    first = CustomerImageProduct(name="First", category="box", fixed_prompt="x", output_prompt="y", created_by=1, is_published=True)
    second = CustomerImageProduct(name="Second", category="box", fixed_prompt="x", output_prompt="y", created_by=1)
    db.add_all([first, second])
    db.flush()
    primary = CustomerImageProductAsset(product_id=first.id, role="cover", position=0, storage_path="primary.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="a" * 64)
    extra = CustomerImageProductAsset(product_id=first.id, role="cover", position=1, storage_path="extra.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="b" * 64)
    reference = CustomerImageProductAsset(product_id=first.id, role="reference", position=0, storage_path="reference.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="c" * 64)
    retired = CustomerImageProductAsset(product_id=second.id, role="cover", position=0, storage_path="retired.png", mime_type="image/png", file_size=1, width=1, height=1, sha256="d" * 64, retired_at=datetime.now(UTC).replace(tzinfo=None))
    db.add_all([primary, extra, reference, retired])
    db.commit()

    assert list_current_product_covers(db, [first.id, second.id]) == {first.id: primary}
    assert get_current_product_cover(db, first.id).id == primary.id
    with pytest.raises(CustomerImageNotFoundError):
        get_current_product_cover(db, second.id)


def test_real_db_non_admin_cannot_list_or_open_draft_product(db, monkeypatch):
    from app.customer_image import file_service
    from app.customer_image.router import router
    import io

    published = CustomerImageProduct(
        name="Published", category="box", fixed_prompt="x", output_prompt="y",
        created_by=1, is_published=True,
    )
    draft = CustomerImageProduct(
        name="Draft", category="box", fixed_prompt="x", output_prompt="y",
        created_by=1, is_published=False,
    )
    db.add_all([published, draft])
    db.flush()
    db.add_all([
        CustomerImageProductAsset(
            product_id=published.id, role="cover", position=0,
            storage_path="published.png", mime_type="image/png", file_size=1,
            width=1, height=1, sha256="a" * 64,
        ),
        CustomerImageProductAsset(
            product_id=draft.id, role="cover", position=0,
            storage_path="draft.png", mime_type="image/png", file_size=1,
            width=1, height=1, sha256="b" * 64,
        ),
    ])
    db.commit()
    monkeypatch.setattr(file_service, "open_product_asset_content", lambda *_a, **_k: io.BytesIO(b"cover"))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "7", "roles": [], "permissions": ["customer_image:write"],
    }
    client = TestClient(app)

    listed = client.get("/products").json()["data"]
    assert [row["name"] for row in listed] == ["Published"]
    assert client.get(f"/products/{published.id}/cover").status_code == 200
    assert client.get(f"/products/{draft.id}/cover").status_code == 404

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "roles": [], "permissions": ["customer_image:admin"],
    }
    assert {row["name"] for row in client.get("/products").json()["data"]} == {"Published", "Draft"}
    assert client.get(f"/products/{draft.id}/cover").status_code == 200
