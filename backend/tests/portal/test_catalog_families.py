from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text

from test_admin_service import managed, portal_metadata  # noqa: F401
from test_auth_service import auth_context  # noqa: F401
from test_catalog_admin import body, imported, source, update  # noqa: F401
from app.portal import catalog_admin_service, family_service as service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CatalogGrant, CatalogItem, ColorSwatch, ProductFamily
from app.portal.schemas import FamilyAssign, FamilyUpdate, SwatchUpdate


@pytest.fixture
def families(source):
    from app.invoice.models import PriceColorType
    PriceColorType.__table__.create(source.db.get_bind(), checkfirst=True)
    service.seed_defaults(source.db, 1, "seed defaults")
    source.db.commit()
    return source


def family(ctx, code):
    return ctx.db.scalar(select(ProductFamily).where(ProductFamily.code == code))


def family_body(row, **overrides):
    values = {"display_name": row.display_name, "unit_weight_grams": format(row.unit_weight_grams, "f"),
              "min_qty": row.min_qty, "step_qty": row.step_qty,
              "out_of_stock_below": format(row.out_of_stock_below, "f"), "allowed_grades": list(row.allowed_grades),
              "sort_order": row.sort_order, "status": row.status, "reason": "adjust family", **overrides}
    return FamilyUpdate.model_validate(values)


def assign(ctx, item_ids, code="genius_weft_20g", grade="super"):
    result = service.assign_items(ctx.db, 1, FamilyAssign.model_validate(
        {"item_ids": item_ids, "family_code": code, "grade": grade, "reason": "group sku"}))
    ctx.db.commit()
    return result


def piece_item(ctx):
    """Default fixture SKU uses pack/g; families sell by piece, so import one in pieces."""
    return service_import(ctx, sale_unit="piece", inventory_unit="piece", conversion_factor="1",
                          min_qty=1, step_qty=1, safety_buffer="0")


def service_import(ctx, **overrides):
    result = catalog_admin_service.import_item(ctx.db, 1, 0, body(**overrides))
    ctx.db.commit()
    return result


def test_seed_creates_seven_defaults_once_and_never_overwrites(families):
    ctx = families
    rows = ctx.db.scalars(select(ProductFamily).order_by(ProductFamily.sort_order)).all()
    assert [row.code for row in rows] == [spec["code"] for spec in service.DEFAULT_FAMILIES]
    invisible = family(ctx, "invisible_tape_hair")
    assert invisible.allowed_grades == ["super"] and invisible.status == "disabled"
    tape = family(ctx, "tape_hair")
    assert (tape.min_qty, tape.step_qty, tape.out_of_stock_below) == (10, 10, Decimal("80"))
    assert all(row.allowed_grades == ["standard", "super"] for row in rows if row.code != "invisible_tape_hair")
    tape.display_name = "Customized Tape"
    ctx.db.commit()
    again = service.seed_defaults(ctx.db, 1, "seed again")
    ctx.db.commit()
    assert again["created"] == [] and family(ctx, "tape_hair").display_name == "Customized Tape"
    assert ctx.db.scalar(select(func.count()).select_from(ProductFamily)) == 7


def test_assign_inherits_rules_and_converts_buffer_to_inventory_units(families):
    ctx = families
    grams = service_import(ctx, sale_unit="piece", inventory_unit="g", conversion_factor="20")
    result = assign(ctx, [grams["id"]])
    assert result["assigned"] == 1
    item = ctx.db.scalar(select(CatalogItem))
    assert item.grade == "super" and item.family_id == family(ctx, "genius_weft_20g").id
    # 30 pieces below which the item is out of stock = 600 g in inventory units.
    assert (item.min_qty, item.step_qty, item.safety_buffer) == (1, 1, Decimal("600"))
    listed = catalog_admin_service.list_items(ctx.db, 1, family="genius_weft_20g")
    assert listed["total"] == 1 and listed["items"][0]["family_code"] == "genius_weft_20g"
    assert catalog_admin_service.list_items(ctx.db, 1, family="unassigned")["total"] == 0
    counts = next(row for row in service.list_families(ctx.db, 1)["items"] if row["code"] == "genius_weft_20g")
    assert counts["item_counts"]["super"] == {"total": 1, "published": 0}


def test_assign_rejects_sale_unit_mismatch_atomically(families):
    ctx = families
    good = piece_item(ctx)
    ctx.db.execute(text("INSERT INTO okki_products VALUES (102,'Other/20/1','OT','2','20','20g',0)"))
    ctx.db.execute(text("INSERT INTO okki_product_skus VALUES (102,202,0)"))
    ctx.db.commit()
    preview = catalog_admin_service.inspect_source(ctx.db, 1, product_id="102", sku_id="202", product_kind="hair")
    bad = service_import(ctx, product_id="102", sku_id="202", display_name="Other",
                         standard_fingerprint=preview["source"]["standard_fingerprint"])
    with pytest.raises(PortalError) as caught:
        service.assign_items(ctx.db, 1, FamilyAssign.model_validate(
            {"item_ids": [good["id"], bad["id"]], "family_code": "genius_weft_20g", "grade": "standard", "reason": "x"}))
    assert caught.value.code == "INVALID_INPUT"
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(CatalogItem).where(CatalogItem.family_id.is_not(None))) == 0


def test_family_update_propagates_and_invalidates_granted_customers(families):
    ctx = families
    item_id = piece_item(ctx)["id"]
    assign(ctx, [item_id])
    item = ctx.db.scalar(select(CatalogItem))
    ctx.db.add(CatalogGrant(access_id=ctx.access.id, catalog_item_id=item.id))
    ctx.db.commit()
    previous = ctx.access.catalog_version
    row = family(ctx, "genius_weft_20g")
    result = service.update_family(ctx.db, 1, "genius_weft_20g", row.row_version,
                                   family_body(row, out_of_stock_below="40", min_qty=2, step_qty=2))
    ctx.db.commit()
    assert result["updated_items"] == 1 and result["affected_customers"] == 1
    assert ctx.access.catalog_version == previous + 1
    item = ctx.db.scalar(select(CatalogItem).execution_options(populate_existing=True))
    assert (item.min_qty, item.step_qty, item.safety_buffer) == (2, 2, Decimal("40"))
    with pytest.raises(PortalError) as caught:
        service.update_family(ctx.db, 1, "genius_weft_20g", 1, family_body(row))
    assert caught.value.code == "VERSION_CONFLICT"


def test_item_edit_cannot_escape_family_rules(families):
    ctx = families
    item_id = piece_item(ctx)["id"]
    assign(ctx, [item_id])
    current = catalog_admin_service.get_item(ctx.db, 1, item_id)
    edited = catalog_admin_service.update_item(ctx.db, 1, item_id, current["row_version"], update(
        "draft", sale_unit="piece", inventory_unit="piece", conversion_factor="1",
        min_qty=5, step_qty=5, safety_buffer="0"))
    ctx.db.commit()
    assert (edited["min_qty"], edited["step_qty"], edited["safety_buffer"]) == (1, 1, "30.000000")
    with pytest.raises(PortalError) as caught:
        catalog_admin_service.update_item(ctx.db, 1, item_id, edited["row_version"], update(
            "draft", sale_unit="pack", inventory_unit="piece", conversion_factor="1", safety_buffer="0"))
    assert caught.value.code == "INVALID_INPUT"


def test_clear_assignment_keeps_item_rules(families):
    ctx = families
    item_id = piece_item(ctx)["id"]
    assign(ctx, [item_id])
    result = service.assign_items(ctx.db, 1, FamilyAssign.model_validate(
        {"item_ids": [item_id], "family_code": None, "grade": None, "reason": "ungroup"}))
    ctx.db.commit()
    item = ctx.db.scalar(select(CatalogItem))
    assert result["assigned"] == 1 and item.family_id is None and item.grade is None
    assert item.safety_buffer == Decimal("30")
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(
        AuditEvent.action == "catalog_family_assigned")) == 2


@pytest.mark.parametrize("values", [{"family_code": "genius_weft_20g", "grade": None},
    {"family_code": None, "grade": "super"}, {"grade": "premium"}, {"item_ids": []},
    {"family_code": "Bad-Code"}])
def test_assign_schema_rejects_partial_or_invalid(values):
    base = {"item_ids": [str(uuid4())], "family_code": "genius_weft_20g", "grade": "super", "reason": "x"}
    with pytest.raises(ValidationError):
        FamilyAssign.model_validate({**base, **values})


@pytest.mark.parametrize("values", [{"min_qty": 3, "step_qty": 2}, {"unit_weight_grams": "0"},
    {"allowed_grades": []}, {"allowed_grades": ["super", "super"]}, {"display_name": "<b>"}])
def test_family_schema_rejects_invalid(values):
    base = {"display_name": "Tape", "unit_weight_grams": "2.5", "min_qty": 10, "step_qty": 10,
            "out_of_stock_below": "80", "allowed_grades": ["standard"], "sort_order": 0,
            "status": "enabled", "reason": "x"}
    with pytest.raises(ValidationError):
        FamilyUpdate.model_validate({**base, **values})


@pytest.mark.parametrize("left,right", [("#9ATP9A/613", "9atp9a-613"), ("#2 ", "2"),
    ("#P2-8 ", "p2/8"), ("#Cookies Cream", "cookies cream")])
def test_color_key_unifies_file_and_pi_spellings(left, right):
    assert service.color_key(left) == service.color_key(right)


def test_sync_registers_catalog_colors_and_update_keeps_identity(families):
    ctx = families
    imported(ctx)
    first = service.sync_swatches(ctx.db, 1, "register colors")
    ctx.db.commit()
    assert first["created"] == ["1"]
    assert service.sync_swatches(ctx.db, 1, "again")["created"] == []
    listed = service.list_swatches(ctx.db, 1)
    swatch = listed["items"][0]
    assert swatch["color_code"] == "#1" and swatch["item_count"] == 1 and listed["unregistered_colors"] == []
    labels = SwatchUpdate.model_validate({"asset_id": None, "keep_image": True, "color_code": "#1",
        "display_name": "Jet Black", "status": "enabled", "reason": "label"})
    result = service.update_swatch(ctx.db, 1, swatch["id"], swatch["row_version"], labels)
    ctx.db.commit()
    assert result["display_name"] == "Jet Black" and result["row_version"] == 2
    with pytest.raises(PortalError) as caught:
        service.update_swatch(ctx.db, 1, swatch["id"], 2, labels.model_copy(update={"color_code": "#1B"}))
    assert caught.value.code == "INVALID_INPUT"


def test_swatch_image_change_requires_asset_permission(families, monkeypatch):
    ctx = families
    imported(ctx)
    service.sync_swatches(ctx.db, 1, "register")
    ctx.db.commit()
    row = ctx.db.scalar(select(ColorSwatch))
    denied = []
    def employee(db, actor_id, permission):
        if permission == "asset:admin":
            denied.append(permission)
            raise PortalError("ACTION_FORBIDDEN", "Denied", 403)
        return {"id": actor_id, "roles": ["sales"], "permissions": {permission}}
    monkeypatch.setattr(service.admin, "employee_principal", employee)
    remove = SwatchUpdate.model_validate({"asset_id": None, "color_code": "#1", "status": "enabled", "reason": "x"})
    with pytest.raises(PortalError) as caught:
        service.update_swatch(ctx.db, 1, row.public_id, row.row_version, remove)
    assert caught.value.status == 403 and denied == ["asset:admin"]


def test_admin_http_contract_for_families(families):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx = families
    app = FastAPI()
    app.include_router(router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    claims = {"sub": "1"}
    app.dependency_overrides[get_current_user] = lambda: claims
    item_id = piece_item(ctx)["id"]

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            base = "/api/portal/admin/v1"
            listed = (await client.get(base + "/catalog-families")).json()["data"]["items"]
            assert len(listed) == 7
            target = next(row for row in listed if row["code"] == "k_tip")
            payload = {key: target[key] for key in service.FAMILY_FIELDS} | {"reason": "tune"}
            assert (await client.patch(base + "/catalog-families/k_tip", json=payload)).status_code == 428
            response = await client.patch(base + "/catalog-families/k_tip", json=payload,
                                          headers={"If-Match": f'"{target["row_version"]}"'})
            assert response.status_code == 200 and response.json()["data"]["row_version"] == target["row_version"] + 1
            response = await client.post(base + "/catalog-families/assign", json={
                "item_ids": [item_id], "family_code": "genius_weft_50g", "grade": "standard", "reason": "group"})
            assert response.status_code == 200 and response.json()["data"]["assigned"] == 1
            assert (await client.get(base + "/catalog", params={"family": "genius_weft_50g"})).json()["data"]["total"] == 1
            assert (await client.get(base + "/catalog", params={"family": "Bad"})).status_code == 422
            claims["sub"] = "3"
            assert (await client.get(base + "/catalog-families")).status_code == 403
    asyncio.run(scenario())
