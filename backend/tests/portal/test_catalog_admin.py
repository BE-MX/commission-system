from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text

from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context
from app.core.time import beijing_now
from app.portal import catalog_admin_service as service, sku_source
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CatalogGrant, CatalogItem, Quote
from app.portal.schemas import CatalogImport, CatalogUpdate


@pytest.fixture
def source(managed, monkeypatch):
    ctx = managed
    ctx.settings.PORTAL_OKKI_NAMESPACE = "okki:test"
    monkeypatch.setattr(service, "get_settings", lambda: ctx.settings)
    monkeypatch.setattr(sku_source, "get_settings", lambda: ctx.settings)
    monkeypatch.setattr(sku_source.product_service, "_schema", lambda: "main")
    ctx.db.execute(text("CREATE TABLE okki_products (product_id INTEGER, product_name TEXT, model TEXT, color TEXT, size TEXT, unit TEXT, disable_flag INTEGER)"))
    ctx.db.execute(text("CREATE TABLE okki_product_skus (product_id INTEGER, sku_id INTEGER, disable_flag INTEGER)"))
    ctx.db.execute(text("INSERT INTO okki_products VALUES (101,'Straight/20/1','ST','1','20','20g',0)"))
    ctx.db.execute(text("INSERT INTO okki_product_skus VALUES (101,201,0)"))
    ctx.db.commit()
    return ctx


def body(**overrides):
    fingerprint = sku_source.content_hash({"source_namespace": "okki:test", "product_id": "101", "sku_id": "201", "product_kind": "hair",
        "attributes": {"product_name": "Straight/20/1", "model": "ST", "color": "1", "model_key": "ST", "color_key": "1", "length": "20", "weight": "20g", "price_unit": "20g", "product_display": "Straight"}})
    return CatalogImport.model_validate({"product_id": "101", "sku_id": "201", "product_kind": "hair",
        "display_name": "Straight", "color_name": "Natural Black", "inventory_unit": "g",
        "sale_unit": "pack", "conversion_factor": "20", "safety_buffer": "10",
        "min_qty": 2, "step_qty": 2, "reason": "verified standard SKU", "standard_fingerprint": fingerprint, **overrides})


def update(status="published", **overrides):
    values = body().model_dump(exclude={"product_id", "sku_id", "product_kind", "standard_fingerprint"})
    return CatalogUpdate.model_validate({**values, "status": status, **overrides})


def imported(ctx):
    result = service.import_item(ctx.db, 1, 0, body())
    ctx.db.commit()
    return result


def test_import_is_draft_and_repeat_cannot_duplicate(source):
    ctx = source
    first = imported(ctx)
    assert first["status"] == "draft" and first["row_version"] == 1
    assert first["standard_json"]["price_unit"] == "20g"
    with pytest.raises(PortalError) as caught:
        service.import_item(ctx.db, 1, 0, body())
    assert caught.value.code == "VERSION_CONFLICT"
    assert ctx.db.scalar(select(func.count()).select_from(CatalogItem)) == 1
    assert service.list_items(ctx.db, 1, status="published")["total"] == 0


def test_publish_revalidates_source_and_cas(source):
    ctx = source
    first = imported(ctx)
    result = service.update_item(ctx.db, 1, first["id"], 1, update())
    ctx.db.commit()
    assert result["status"] == "published" and result["row_version"] == 2
    with pytest.raises(PortalError) as caught:
        service.update_item(ctx.db, 1, first["id"], 1, update("disabled"))
    assert caught.value.code == "VERSION_CONFLICT"
    ctx.db.rollback()
    ctx.db.execute(text("UPDATE okki_products SET unit='25g'"))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.update_item(ctx.db, 1, first["id"], 2, update())
    assert caught.value.code == "SKU_CHANGED"
    ctx.db.rollback()
    preview = service.inspect_source(ctx.db, 1, product_id="101", sku_id="201", product_kind="hair")
    refreshed = service.import_item(ctx.db, 1, 2, body(conversion_factor="25", standard_fingerprint=preview["source"]["standard_fingerprint"]))
    ctx.db.commit()
    assert refreshed["id"] == first["id"] and refreshed["status"] == "draft"
    assert refreshed["standard_json"]["price_unit"] == "25g"


def test_disable_still_works_when_mirror_unavailable(source):
    ctx = source
    first = imported(ctx)
    ctx.db.execute(text("DROP TABLE okki_product_skus"))
    ctx.db.commit()
    result = service.update_item(ctx.db, 1, first["id"], 1, update("disabled"))
    ctx.db.commit()
    assert result["status"] == "disabled"


def test_change_invalidates_valid_quote_and_versions_not_history(source):
    ctx = source
    first = imported(ctx)
    item = ctx.db.scalar(select(CatalogItem))
    ctx.db.add(CatalogGrant(access_id=ctx.access.id, catalog_item_id=item.id))
    quotes = []
    for status in ("valid", "consumed"):
        row = Quote(access_id=ctx.access.id, account_id=ctx.account.id, membership_id=ctx.member.id,
            status=status, expires_at=beijing_now()+timedelta(minutes=15), authority_versions_json={},
            input_hash="a"*64, result_hash="b"*64, currency="USD", product_amount="60",
            lines_json=[{"kept": True}], delivery_json={}, payment_terms_snapshot={})
        ctx.db.add(row)
        quotes.append(row)
    ctx.db.commit()
    previous = ctx.access.catalog_version
    result = service.update_item(ctx.db, 1, first["id"], 1, update())
    ctx.db.commit()
    assert result["affected_customers"] == result["expired_quotes"] == 1
    assert ctx.access.catalog_version == previous + 1
    assert [row.status for row in quotes] == ["expired", "consumed"]
    assert all(row.lines_json == [{"kept": True}] for row in quotes)
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=="catalog_updated")) == 1


def test_failed_transaction_rolls_back_item_and_audit(source):
    ctx = source
    service.import_item(ctx.db, 1, 0, body())
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(CatalogItem)) == 0
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=="catalog_imported")) == 0


def test_live_permission_required_before_source_read(source, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized caller reached product source")
    monkeypatch.setattr(sku_source, "load_snapshot", forbidden)
    with pytest.raises(PortalError) as caught:
        service.import_item(source.db, 3, 0, body())
    assert caught.value.status == 403


@pytest.mark.parametrize("values", [{"conversion_factor": "0"}, {"safety_buffer": "-1"},
    {"conversion_factor": 20.0}, {"conversion_factor": "100000000"},
    {"min_qty": 3}, {"step_qty": True}, {"inventory_unit": "g\nunit"},
    {"display_name": "<script>"}, {"unit_price": "1.00"}, {"standard_json": {}}])
def test_configuration_rejects_ambiguous_units_and_injected_price(values):
    with pytest.raises(ValidationError):
        body(**values)


def test_unknown_item_not_found(source):
    with pytest.raises(PortalError) as caught:
        service.update_item(source.db, 1, uuid4(), 1, update())
    assert caught.value.status == 404


def test_admin_http_contract(source):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx = source
    app = FastAPI()
    app.include_router(router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    claims = {"sub": "1"}
    app.dependency_overrides[get_current_user] = lambda: claims

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/portal/admin/v1/catalog"
            assert (await client.post(path+"/import", json=body().model_dump())).status_code == 428
            response = await client.post(path+"/import", json=body().model_dump(), headers={"If-Match": '"0"'})
            assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
            item = response.json()["data"]
            response = await client.patch(path+"/"+item["id"], json=update().model_dump(), headers={"If-Match": '"1"'})
            assert response.status_code == 200 and response.json()["data"]["status"] == "published"
            response = await client.get(path, params={"status": "published"})
            assert response.json()["data"]["total"] == 1
            assert (await client.get(path, params={"page_size": 101})).status_code == 422
            claims["sub"] = "3"
            assert (await client.get(path)).status_code == 403
    asyncio.run(scenario())


def two_granted(ctx):
    first = imported(ctx)
    ctx.db.execute(text("INSERT INTO okki_products VALUES (102,'Other/20/1','OT','1','20','20g',0)"))
    ctx.db.execute(text("INSERT INTO okki_product_skus VALUES (102,202,0)"))
    ctx.db.commit()
    inspected = service.inspect_source(ctx.db, 1, product_id="102", sku_id="202", product_kind="hair")
    second = service.import_item(ctx.db, 1, 0, body(product_id="102", sku_id="202", display_name="Other", standard_fingerprint=inspected["source"]["standard_fingerprint"]))
    ctx.db.commit()
    for row in (first, second):
        item = ctx.db.scalar(select(CatalogItem).where(CatalogItem.public_id == row["id"]))
        ctx.db.add(CatalogGrant(access_id=ctx.access.id, catalog_item_id=item.id))
    ctx.db.commit()
    service.update_item(ctx.db, 1, first["id"], 1, update())
    ctx.db.commit()
    service.update_item(ctx.db, 1, second["id"], 1, update(display_name="Other"))
    ctx.db.commit()
    return first, second


@pytest.mark.parametrize("operation", ["disable", "reimport"])
def test_withdrawal_ignores_only_obsolete_aliases(source, operation):
    from copy import deepcopy
    from app.portal import mapping_service, catalog_service
    from app.portal.access_policy import customer_principal
    from app.portal.models import MappingRevision
    from app.portal.schemas import MappingInput
    ctx = source
    first, second = two_granted(ctx)
    mapping_service.publish(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
        MappingInput(base_version=0, entries=[{"kind": "sku", "source_key": first["id"],
            "item_id": first["id"], "display_value": "Customer A"}]))
    ctx.db.commit()
    original = deepcopy(ctx.db.scalar(select(MappingRevision)).snapshot_json)
    if operation == "disable":
        service.update_item(ctx.db, 1, first["id"], 2, update("disabled"))
    else:
        service.import_item(ctx.db, 1, 2, body())
    ctx.db.commit()
    ctx.access.can_view_price = ctx.access.can_order = False
    ctx.db.commit()
    principal = customer_principal(ctx.db, ctx.account.id, ctx.member.id)
    result = catalog_service.list_catalog(ctx.db, principal)
    assert result["total"] == 1 and result["items"][0]["item_id"] == second["id"]
    assert catalog_service.detail(ctx.db, principal, second["id"])["item_id"] == second["id"]
    assert ctx.db.scalar(select(MappingRevision)).snapshot_json == original


def test_published_configuration_conflict_rolls_back(source):
    ctx = source
    first, second = two_granted(ctx)
    previous = ctx.access.catalog_version
    audit_count = ctx.db.scalar(select(func.count()).select_from(AuditEvent))
    with pytest.raises(PortalError) as caught:
        service.update_item(ctx.db, 1, second["id"], 2, update(display_name="Straight"))
    assert caught.value.code == "MAPPING_CONFLICT"
    ctx.db.rollback()
    item = ctx.db.scalar(select(CatalogItem).where(CatalogItem.public_id == second["id"]))
    assert item.display_name == "Other" and item.row_version == 2
    assert ctx.access.catalog_version == previous
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent)) == audit_count
