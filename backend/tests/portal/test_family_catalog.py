from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_catalog import priced_catalog, catalog, managed, portal_metadata, auth_context  # noqa: F401
from app.core.time import beijing_now
from app.portal import catalog_service, family_catalog_service as service, image_service, pricing
from app.portal.errors import PortalError
from app.portal.inventory import InventoryObservation
from app.portal.models import CatalogGrant, ColorSwatch, ProductFamily


@pytest.fixture
def family_catalog(priced_catalog):
    ctx, items, principal = priced_catalog
    family = ProductFamily(site_id=ctx.site.id, code="genius_weft_20g", display_name="Genius Weft 20g/piece",
        sale_unit="pack", unit_weight_grams=Decimal("20"), min_qty=1, step_qty=1,
        out_of_stock_below=Decimal("30"), allowed_grades=["standard", "super"], sort_order=10,
        status="enabled", row_version=1)
    ctx.db.add(family)
    ctx.db.flush()
    items[0].family_id, items[0].grade = family.id, "super"
    items[1].family_id, items[1].grade = family.id, "standard"
    items[1].standard_json = {**items[1].standard_json, "color": "9ATP9A/613", "length": "18"}
    for item in items:
        item.safety_buffer = Decimal("600")  # 30 packs x 20 g
    swatch = ColorSwatch(site_id=ctx.site.id, color_key="9atp9a-613", color_code="#9ATP9A/613",
        display_name="Rose Golden", image_asset_id="7:" + "a" * 43, status="enabled", row_version=1)
    ctx.db.add(swatch)
    ctx.db.commit()
    return ctx, items, principal, family, swatch


def observe(monkeypatch, quantities):
    now = beijing_now() - timedelta(seconds=1)
    monkeypatch.setattr(catalog_service, "load_observations", lambda db, rows: {
        key: InventoryObservation(Decimal(value), "g", now, "fixture") for key, value in quantities.items()})


def test_family_list_groups_only_visible_grades(family_catalog):
    ctx, items, principal, family, _ = family_catalog
    result = service.list_families(ctx.db, principal)
    assert result["ungrouped_count"] == 0
    [entry] = result["items"]
    assert entry["code"] == "genius_weft_20g" and entry["variant_count"] == 2
    assert entry["grades"] == ["standard", "super"] and entry["lengths"] == ["18", "20"]
    assert entry["image_url"].startswith("/api/portal/v1/catalog/swatches/")
    family.allowed_grades = ["super"]
    ctx.db.commit()
    result = service.list_families(ctx.db, principal)
    assert result["items"][0]["variant_count"] == 1 and result["ungrouped_count"] == 1
    family.status = "disabled"
    ctx.db.commit()
    assert service.list_families(ctx.db, principal) == {"items": [], "ungrouped_count": 2,
        "catalog_version": ctx.access.catalog_version}


def test_family_detail_projects_variants_with_alias_price_and_swatch(family_catalog, monkeypatch):
    ctx, items, principal, family, swatch = family_catalog
    observe(monkeypatch, {items[0].public_id: "3000", items[1].public_id: "1000"})
    result = service.family_detail(ctx.db, principal, "genius_weft_20g")
    assert result["grades"] == ["standard", "super"] and result["unit_weight_grams"] == "20"
    standard, superior = result["variants"]
    assert standard["grade"] == "standard" and standard["color_code"] == "#9ATP9A/613"
    assert standard["color_label"] == "Rose Golden" and standard["color_type"] == "balayage"
    assert standard["swatch_url"] == f"/api/portal/v1/catalog/swatches/{swatch.public_id}/image?version=1&size=thumb"
    # Low-stock threshold does not reserve units: 1000/20=50; 3000/20 is banded.
    assert standard["stock_display"] == "50" and superior["stock_display"] == "100+"
    assert superior["unit_price"] == "27.0000" and superior["swatch_url"] is None
    assert not {"product_id", "sku_id", "standard_json", "safety_buffer"} & superior.keys()


@pytest.mark.parametrize("quantity,state,display", [("600", "available", "30"), ("599", "unavailable", None),
    ("1980", "available", "99"), ("2000", "available", "100+")])
def test_stock_display_gates_below_threshold_and_bands(family_catalog, monkeypatch, quantity, state, display):
    ctx, items, principal, *_ = family_catalog
    observe(monkeypatch, {items[0].public_id: quantity})
    row = catalog_service.detail(ctx.db, principal, items[0].public_id)
    assert (row["availability"], row["stock_display"]) == (state, display)


def test_availability_polling_never_resolves_price(family_catalog, monkeypatch):
    ctx, items, principal, *_ = family_catalog
    observe(monkeypatch, {items[0].public_id: "800"})
    def forbidden(*args, **kwargs):
        raise AssertionError("polling must not price")
    monkeypatch.setattr(pricing, "resolve", forbidden)
    result = service.family_availability(ctx.db, principal, "genius_weft_20g")
    states = {entry["item_id"]: (entry["availability"], entry["stock_display"]) for entry in result["items"]}
    assert states == {items[0].public_id: ("available", "40"), items[1].public_id: ("unknown", None)}
    assert all("unit_price" not in entry for entry in result["items"])


def test_unknown_disabled_or_ungranted_family_is_not_found(family_catalog):
    ctx, items, principal, family, _ = family_catalog
    for code in ("k_tip",):
        with pytest.raises(PortalError) as error:
            service.family_detail(ctx.db, principal, code)
        assert error.value.status == 404
    for grant in ctx.db.scalars(select(CatalogGrant)):
        grant.status = "disabled"
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        service.family_detail(ctx.db, principal, "genius_weft_20g")
    assert error.value.status == 404


def test_swatch_image_requires_a_granted_item_in_that_color(family_catalog, monkeypatch):
    ctx, items, principal, family, swatch = family_catalog
    monkeypatch.setattr(image_service.auth_service, "authenticate", lambda db, token: (principal, None))
    monkeypatch.setattr(image_service, "approved_ticket", lambda db, reference: {"reference": reference})
    assert image_service.swatch_ticket(ctx.db, "t", swatch.public_id, 1) == {"reference": swatch.image_asset_id}
    for version, change in ((2, None), (1, "disable"), (1, "revoke")):
        if change == "disable":
            swatch.status = "disabled"
        if change == "revoke":
            swatch.status = "enabled"
            ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == items[1].id)).status = "disabled"
        ctx.db.commit()
        with pytest.raises(PortalError) as error:
            image_service.swatch_ticket(ctx.db, "t", swatch.public_id, version)
        assert error.value.status == 404
    with pytest.raises(PortalError):
        image_service.swatch_ticket(ctx.db, "t", uuid4(), 1)


def test_family_http_routes_are_customer_scoped(family_catalog, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    from test_auth_service import send_code, verify
    ctx, items, *_ = family_catalog
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
            base = "/api/portal/v1/catalog/families"
            assert (await client.get(base)).status_code == 401
            client.cookies.set("__Host-portal_session", token)
            listed = await client.get(base)
            assert listed.status_code == 200 and listed.json()["data"]["items"][0]["code"] == "genius_weft_20g"
            detail = await client.get(base + "/genius_weft_20g")
            assert detail.status_code == 200 and len(detail.json()["data"]["variants"]) == 2
            assert (await client.get(base + "/genius_weft_20g/availability")).status_code == 200
            assert (await client.get(base + "/Bad-Code")).status_code == 422
            assert (await client.get(base + "/k_tip")).status_code == 404
            # Flat item route still resolves UUIDs only.
            assert (await client.get("/api/portal/v1/catalog/" + items[0].public_id)).status_code == 200
    asyncio.run(scenario())


@pytest.mark.parametrize("repeat", [1, 100])
def test_family_price_queries_are_bounded_and_match_single_item(family_catalog, monkeypatch, repeat):
    from sqlalchemy import event
    ctx, items, principal, *_ = family_catalog
    observe(monkeypatch, {})
    expected = {row.public_id: catalog_service.with_price(ctx.db, principal, row, {}) for row in items}
    original = catalog_service.projected_items
    def repeated(*args, **kwargs):
        return [(row, dict(item)) for row, item in original(*args, **kwargs)] * repeat
    monkeypatch.setattr(catalog_service, "projected_items", repeated)
    queries = []
    def record(conn, cursor, statement, parameters, context, many):
        if any(table in statement for table in ('ark_std_prices', 'ark_price_color_types', 'ark_customer_price_rules')):
            queries.append(statement)
    event.listen(ctx.db.get_bind(), 'before_cursor_execute', record)
    try:
        result = service.family_detail(ctx.db, principal, 'genius_weft_20g')
    finally:
        event.remove(ctx.db.get_bind(), 'before_cursor_execute', record)
    assert len(result['variants']) == len(items) * repeat
    for item in result['variants']:
        assert item['unit_price'] == expected[item['item_id']]['unit_price']
        assert item['price_status'] == expected[item['item_id']]['price_status']
    assert len(queries) <= 3, f'{len(queries)} pricing queries for {len(items)} variants'


@pytest.mark.parametrize('case', ['normal', 'fixed', 'missing', 'ambiguous', 'exact_color', 'negative', 'currency', 'namespace', 'bad_rule', 'duplicate_color', 'untyped_color'])
def test_browse_prices_match_authoritative_resolver_and_refresh(family_catalog, case):
    from app.invoice.models import StdPrice, CustomerPriceRule, PriceColorType
    from app.portal.browse_pricing import BrowsePrices
    ctx, items, principal, *_ = family_catalog
    if case == 'fixed':
        ctx.db.get(CustomerPriceRule, 1).adjust_type = 'fixed'
    elif case == 'missing':
        ctx.db.delete(ctx.db.get(StdPrice, 1))
    elif case == 'ambiguous':
        ctx.db.add(StdPrice(id=2, product_kind='hair', series_grade='Standard', length='20',
            weight_unit='20g', color_type='solid', price=Decimal('10'), currency='USD'))
    elif case == 'exact_color':
        ctx.db.add(PriceColorType(color_code='1', color_type='piano'))
    elif case == 'negative':
        ctx.db.get(CustomerPriceRule, 1).adjust_value = Decimal('-200')
    elif case == 'currency':
        ctx.db.get(StdPrice, 1).currency = 'EUR'
    elif case == 'namespace':
        items[0].source_namespace = 'other'
    elif case == 'duplicate_color':
        ctx.db.add_all([PriceColorType(color_code='1', color_type='solid'), PriceColorType(color_code='#1', color_type='piano')])
    elif case == 'untyped_color':
        items[0].standard_json = {**items[0].standard_json, 'color': 'unknown'}
        ctx.db.get(StdPrice, 1).color_type = None
    elif case == 'bad_rule':
        ctx.db.get(CustomerPriceRule, 1).adjust_type = 'unknown'
    ctx.db.commit()
    browse = BrowsePrices(ctx.db, principal.access, items)
    for row in items:
        expected = catalog_service.with_price(ctx.db, principal, row, {})
        assert catalog_service.with_price(ctx.db, principal, row, {}, browse=browse) == expected
    # A new request must observe a price change (no process/session cache).
    if case == 'normal':
        ctx.db.get(StdPrice, 1).price = Decimal('40')
        ctx.db.commit()
        fresh = BrowsePrices(ctx.db, principal.access, items)
        assert catalog_service.with_price(ctx.db, principal, items[0], {}, browse=fresh)['unit_price'] == '36.0000'


def test_browse_colors_chunk_large_inputs(family_catalog):
    from types import SimpleNamespace
    from app.portal.browse_pricing import BrowsePrices
    ctx, _, principal, *_ = family_catalog
    items = [SimpleNamespace(standard_json={'color': str(value)}) for value in range(450)]
    snapshot = BrowsePrices(ctx.db, principal.access, items)
    assert len(snapshot.colors) == 450
    assert all(snapshot.color_type(str(value)) == 'solid' for value in range(450))


def test_family_without_price_permission_does_not_read_prices(family_catalog, monkeypatch):
    from sqlalchemy import event
    ctx, _, principal, *_ = family_catalog
    ctx.access.can_view_price = ctx.access.can_order = False
    observe(monkeypatch, {})
    def guard(conn, cursor, statement, parameters, context, many):
        assert 'ark_std_prices' not in statement and 'ark_customer_price_rules' not in statement
    event.listen(ctx.db.get_bind(), 'before_cursor_execute', guard)
    try:
        result = service.family_detail(ctx.db, principal, 'genius_weft_20g')
        assert all('unit_price' not in item for item in result['variants'])
    finally:
        event.remove(ctx.db.get_bind(), 'before_cursor_execute', guard)
