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
)
from app.customer_image.schemas import CustomerImageInviteCreate
from app.auth.models import ArkUserExternalBinding
from sqlalchemy import text


EXPECTED = {
    ("get", "/customers"): "customer_image:write",
    ("get", "/products"): "customer_image:read",
    ("post", "/products"): "customer_image:admin",
    ("put", "/products/{product_id}"): "customer_image:admin",
    ("delete", "/products/{product_id}"): "customer_image:admin",
    ("post", "/products/{product_id}/publish"): "customer_image:admin",
    ("post", "/products/{product_id}/unpublish"): "customer_image:admin",
    ("get", "/products/{product_id}/assets"): "customer_image:admin",
    ("post", "/products/{product_id}/assets/upload"): "customer_image:admin",
    ("post", "/products/{product_id}/assets/library"): "customer_image:admin",
    ("get", "/products/{product_id}/assets/{asset_id}/content"): "customer_image:admin",
    ("get", "/library-assets"): "customer_image:admin",
    ("get", "/library-assets/{asset_id}/content"): "customer_image:admin",
    ("get", "/invites"): "customer_image:read",
    ("post", "/invites"): "customer_image:write",
    ("post", "/invites/{invite_id}/revoke"): "customer_image:write",
    ("get", "/generations"): "customer_image:read",
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
        calls = [item for item in ast.walk(node) if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "require_permission"]
        assert len(calls) == 1, node.name
        actual[(route.func.attr, route.args[0].value)] = calls[0].args[0].value
    assert actual == EXPECTED


@pytest.mark.parametrize("method,path,kwargs", [
        ("get", "/customers", {}), ("get", "/products", {}),
        ("post", "/products", {"json": {}}), ("put", "/products/1", {"json": {}}),
        ("delete", "/products/1", {}),
        ("post", "/products/1/publish", {}), ("get", "/invites", {}),
        ("post", "/products/1/unpublish", {}),
        ("get", "/products/1/assets", {}),
        ("post", "/products/1/assets/upload", {"data": {"role": "cover", "position": "0"}, "files": {"file": ("x.png", b"x", "image/png")}}),
        ("post", "/products/1/assets/library", {"json": {"source_asset_id": 1, "role": "cover", "position": 0}}),
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
    assert [row.id for row in list_invites(db, 7, False)] == [own.id]
    assert [row.request_id for row in list_generations(db, 7, False)] == ["own"]
    assert {row.id for row in list_invites(db, 99, True)} == {own.id, other.id}


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
        text("INSERT INTO lsordertest.customer_info (company_id, company_name) VALUES ('C7', 'Owned')")
    )
    db.add(ArkUserExternalBinding(ark_user_id=7, provider="okki", external_account_id="1007", binding_status="active", is_primary=True))
    from app.models.customer import CustomerCommissionSnapshot
    db.add(CustomerCommissionSnapshot(customer_id="C7", salesperson_id="1007", is_current=True, source="auto"))
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


def test_admin_invite_snapshots_customers_current_okki_owner_without_own_binding(db):
    from app.customer_image.service import create_invite
    from app.models.customer import CustomerCommissionSnapshot

    db.execute(text("INSERT INTO lsordertest.customer_info (company_id, company_name) VALUES ('CA', 'Admin Customer')"))
    db.add(CustomerCommissionSnapshot(customer_id="CA", salesperson_id="2008", is_current=True, source="auto"))
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
