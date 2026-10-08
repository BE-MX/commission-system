from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select

from test_mapping_service import catalog, managed, portal_metadata, auth_context, body
from app.core.time import beijing_now
from app.invoice.models import StdPrice, PriceColorType, CustomerPriceRule
from app.portal import catalog_service as service, mapping_service, pricing
from app.portal.access_policy import customer_principal
from app.portal.errors import PortalError
from app.portal.inventory import InventoryObservation
from app.portal.models import CatalogGrant


@pytest.fixture
def priced_catalog(catalog, monkeypatch):
    ctx, items = catalog
    metadata = MetaData()
    for model in (StdPrice, PriceColorType, CustomerPriceRule):
        Table(model.__tablename__, metadata, *(Column(c.name, Integer() if c.primary_key else c.type,
            primary_key=c.primary_key, nullable=c.nullable) for c in model.__table__.columns))
    metadata.create_all(ctx.db.get_bind())
    ctx.db.add(StdPrice(id=1, product_kind="hair", series_grade="Standard Straight", length="20",
        weight_unit="20g", color_type="solid", price=Decimal("30.0000"), currency="USD"))
    ctx.db.add(CustomerPriceRule(id=1, customer_id="1", adjust_type="percent", adjust_value=Decimal("-10"), enabled=1))
    for item in items:
        item.standard_json = {**item.standard_json, "product_display": "Standard Straight", "price_unit": "20g", "color": "1"}
    ctx.db.commit()
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(PORTAL_INVENTORY_MAX_AGE_SECONDS=120))
    monkeypatch.setattr(pricing, "get_settings", lambda: SimpleNamespace(PORTAL_OKKI_NAMESPACE="okki:test"))
    principal = customer_principal(ctx.db, ctx.account.id, ctx.member.id)
    return ctx, items, principal


def test_catalog_uses_current_mapping_and_customer_rule(priced_catalog):
    ctx, items, principal = priced_catalog
    mapping_service.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    ctx.db.commit()
    result = service.list_catalog(ctx.db, principal, keyword="Midnight")
    assert result["total"] == 1
    row = result["items"][0]
    assert row["model_name"] == "Silk Collection" and row["color_name"] == "Midnight"
    assert row["unit_price"] == "27.0000" and row["availability"] == "unknown"
    assert result["facets"]["colors"] == ["Midnight"]
    assert service.list_catalog(ctx.db, principal, keyword="Standard Straight")["total"] == 0
    assert not {"product_id", "sku_id", "quantity", "standard_price", "rule", "source_namespace"} & row.keys()


def test_unauthorized_price_is_neither_computed_nor_returned(priced_catalog, monkeypatch):
    ctx, items, principal = priced_catalog
    ctx.access.can_view_price = ctx.access.can_order = False
    def forbidden(*args):
        raise AssertionError("Price service called without price permission")
    monkeypatch.setattr(pricing, "resolve", forbidden)
    row = service.detail(ctx.db, principal, items[0].public_id)
    assert "unit_price" not in row and "price_status" not in row


def test_revoked_item_hidden_from_list_detail_and_facets(priced_catalog):
    ctx, items, principal = priced_catalog
    grant = ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == items[0].id))
    grant.status = "disabled"
    ctx.db.commit()
    view = service.list_catalog(ctx.db, principal)
    assert view["total"] == 1 and view["facets"]["colors"] == ["Brown"]
    for identifier in (items[0].public_id, str(uuid4())):
        with pytest.raises(PortalError) as error:
            service.detail(ctx.db, principal, identifier)
        assert error.value.status == 404


@pytest.mark.parametrize("change", ["missing", "negative", "currency", "namespace", "metadata"])
def test_invalid_price_is_unavailable_not_free(priced_catalog, change):
    ctx, items, principal = priced_catalog
    if change == "missing":
        ctx.db.delete(ctx.db.get(StdPrice, 1))
    elif change == "negative":
        ctx.db.get(CustomerPriceRule, 1).adjust_value = Decimal("-150")
    elif change == "currency":
        ctx.db.get(StdPrice, 1).currency = "EUR"
    elif change == "namespace":
        items[0].source_namespace = "okki:other"
    else:
        items[0].standard_json = {"model_key": "model:101", "color_key": "color:1", "length": "20", "weight": "20"}
    ctx.db.commit()
    row = service.detail(ctx.db, principal, items[0].public_id)
    assert row["unit_price"] is None and row["price_status"] == "unavailable"


@pytest.mark.parametrize("case,expected", [("fresh", "available"), ("empty", "unavailable"),
    ("stale", "unknown"), ("future", "unknown"), ("unit", "unknown"), ("negative", "unknown")])
def test_inventory_displays_only_verified_status(priced_catalog, monkeypatch, case, expected):
    ctx, items, principal = priced_catalog
    observed = beijing_now() + timedelta(seconds=60 if case == "future" else -121 if case == "stale" else -1)
    observation = InventoryObservation(Decimal("-1" if case == "negative" else "0" if case == "empty" else "40"),
        "kg" if case == "unit" else "g", observed, "isolated-fixture")
    monkeypatch.setattr(service, "load_observations", lambda db, rows: {items[0].public_id: observation})
    result = service.list_catalog(ctx.db, principal, in_stock_only=True)
    assert result["total"] == (1 if expected == "available" else 0)
    row = service.detail(ctx.db, principal, items[0].public_id)
    assert row["availability"] == expected
    assert (row["inventory_observed_at"] is None) is (expected == "unknown")


def test_catalog_http_authentication_validation_and_revocation(priced_catalog, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    from test_auth_service import send_code, verify
    ctx, items, _ = priced_catalog
    challenge, code = send_code(ctx)
    _, _, token = verify(ctx, challenge, code)
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
            base_url="https://orders.example.com", headers={"X-Real-IP": "203.0.113.1"}) as client:
            assert (await client.get("/api/portal/v1/catalog")).status_code == 401
            client.cookies.set("__Host-portal_session", token)
            response = await client.get("/api/portal/v1/catalog?page_size=1&page=2&sort=name")
            assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
            result = response.json()["data"]
            assert result["total"] == 2 and len(result["items"]) == 1
            assert (await client.get("/api/portal/v1/catalog?sort=price")).status_code == 422
            assert (await client.get("/api/portal/v1/catalog/" + str(uuid4()))).status_code == 404
            ctx.access.status = "suspended"
            ctx.db.commit()
            assert (await client.get("/api/portal/v1/catalog/" + items[0].public_id)).status_code == 401
    asyncio.run(scenario())


def test_same_number_in_other_namespace_never_reads_customer_price(priced_catalog, monkeypatch):
    ctx, items, principal = priced_catalog
    ctx.access.okki_namespace = items[0].source_namespace = "okki:another"
    def forbidden(*args):
        raise AssertionError("Cross-source customer rule queried")
    monkeypatch.setattr(pricing.price_service, "get_customer_rule_row", forbidden)
    with pytest.raises(PortalError) as error:
        pricing.resolve(ctx.db, ctx.access, items[0], "USD")
    assert error.value.code == "PRICE_UNAVAILABLE"


def test_accessory_rule_change_changes_fingerprint_even_when_amount_equal(priced_catalog, monkeypatch):
    ctx, items, principal = priced_catalog
    item = items[0]
    item.product_kind = "accessory"
    monkeypatch.setattr(pricing.accessory_price_service, "resolve_configured_price", lambda *a, **k:
        {"standard_price": Decimal("30.0000"), "customer_price": Decimal("27.0000"), "currency": "USD"})
    first = pricing.resolve(ctx.db, ctx.access, item, "USD")
    rule = ctx.db.get(CustomerPriceRule, 1)
    rule.adjust_type, rule.adjust_value = "fixed", Decimal("-3")
    second = pricing.resolve(ctx.db, ctx.access, item, "USD")
    assert first.amount == second.amount and first.fingerprint != second.fingerprint
