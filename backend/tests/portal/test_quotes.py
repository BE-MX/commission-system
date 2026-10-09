from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from test_catalog import priced_catalog, catalog, managed, portal_metadata, auth_context
from test_auth_service import send_code, verify
from app.core.time import beijing_now
from app.invoice.models import CustomerPriceRule
from app.portal import quote_service as service, sku_source, catalog_service, auth_service, mapping_service
from app.portal.errors import PortalError
from app.portal.inventory import InventoryObservation
from app.portal.models import Account, AuditEvent, CatalogGrant, Membership, Quote
from app.portal.schemas import QuoteInput, MappingInput


@pytest.fixture
def quoting(priced_catalog, monkeypatch):
    ctx, items, _ = priced_catalog
    ctx.settings.PORTAL_WRITES_ENABLED = True
    ctx.settings.PORTAL_INVENTORY_MAX_AGE_SECONDS = 120
    ctx.settings.PORTAL_OKKI_NAMESPACE = "okki:test"
    monkeypatch.setattr(service, "get_settings", lambda: ctx.settings)
    monkeypatch.setattr(sku_source, "get_settings", lambda: ctx.settings)
    monkeypatch.setattr(sku_source.product_service, "_schema", lambda: "main")
    ctx.db.execute(text("CREATE TABLE okki_products (product_id INTEGER, product_name TEXT, model TEXT, color TEXT, size TEXT, unit TEXT, disable_flag INTEGER)"))
    ctx.db.execute(text("CREATE TABLE okki_product_skus (product_id INTEGER, sku_id INTEGER, disable_flag INTEGER)"))
    for number, item in enumerate(items, start=1):
        item.product_id = str(100+number)
        ctx.db.execute(text("INSERT INTO okki_products VALUES (:pid,'Standard Straight/20','ST',:color,'20','20g',0)"), {"pid": 100+number, "color": str(number)})
        ctx.db.execute(text("INSERT INTO okki_product_skus VALUES (:pid,:sku,0)"), {"pid": 100+number, "sku": number})
        snapshot = sku_source.load_snapshot(ctx.db, namespace="okki:test", product_id=item.product_id,
                                           sku_id=item.sku_id, product_kind="hair")
        item.standard_json = snapshot["standard_json"]
        item.standard_fingerprint = snapshot["standard_fingerprint"]
    ctx.site.policy_json = {"payment_terms": [{"code": "prepaid", "display_text": "Payment before shipment", "deposit_percent": "100.00"}], "default_payment_term_code": "prepaid"}
    ctx.db.commit()
    challenge, code = send_code(ctx)
    _, session, token = verify(ctx, challenge, code)
    ctx.session_token, ctx.session_csrf = token, auth_service._csrf(session)
    ctx.items = items
    ctx.observations = {item.public_id: InventoryObservation(Decimal("1000"), "g", beijing_now(), "test-mirror-observation") for item in items}
    monkeypatch.setattr(catalog_service, "load_observations", lambda db, rows: ctx.observations)
    return ctx


def body(ctx, **overrides):
    return QuoteInput.model_validate({"items": [{"item_id": ctx.items[0].public_id, "quantity": 3}],
        "delivery": {"contact_name": "Buyer", "phone": "+44 10000000", "address_line1": "10 Example Street", "city": "London", "country_code": "GB"},
        "customer_po": "PO-1", "remark": "Please review", **overrides})


def create(ctx):
    result = service.create(ctx.db, ctx.session_token, ctx.session_csrf, body(ctx))
    ctx.db.commit()
    return result


def test_server_price_snapshot_private_evidence_and_pending_fees(quoting):
    ctx = quoting
    mapping_service.publish(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
        MappingInput(base_version=0, entries=[{"kind": "sku", "source_key": ctx.items[0].public_id,
            "item_id": ctx.items[0].public_id, "display_value": "Silk Collection"}]))
    ctx.db.commit()
    result = create(ctx)
    assert result["product_amount"] == "81.00" and result["total_amount"] is None
    assert result["fees"]["shipping_amount"] is None and result["fees"]["status"] == "pending"
    line = result["items"][0]
    assert line["unit_price"] == "27.0000" and line["display_snapshot"]["model_name"] == "Silk Collection"
    assert not {"standard_snapshot", "inventory_snapshot", "price_fingerprint"} & line.keys()
    quote = ctx.db.scalar(select(Quote))
    assert quote.lines_json[0]["standard_snapshot"]["standard_json"]["product_display"] == "Standard Straight"
    assert quote.authority_versions_json["mapping"] == 1
    audit = ctx.db.scalar(select(AuditEvent).where(AuditEvent.action=="quote.created"))
    assert audit.safe_diff_json == {"line_count": 1}
    assert "Example Street" not in str(audit.safe_diff_json)


def test_read_does_not_reprice_or_replace_historical_snapshot(quoting, monkeypatch):
    ctx = quoting
    first = create(ctx)
    ctx.db.get(CustomerPriceRule, 1).adjust_value = Decimal("-50")
    ctx.items[0].display_name = "New label"
    ctx.db.commit()
    monkeypatch.setattr(service.pricing, "resolve", lambda *args: pytest.fail("Historical read repriced"))
    assert service.detail(ctx.db, ctx.session_token, first["quote_id"]) == first


def test_quote_hash_survives_second_precision_database_round_trip(quoting, monkeypatch):
    ctx = quoting
    observed = beijing_now().replace(microsecond=654321)
    monkeypatch.setattr(service, "beijing_now", lambda: observed)
    # Move injected observations before the controlled clock without changing units.
    ctx.observations = {key: InventoryObservation(value.quantity, value.unit,
        observed-timedelta(seconds=1), value.source) for key, value in ctx.observations.items()}
    result = create(ctx)
    row = ctx.db.scalar(select(Quote))
    assert row.expires_at.microsecond == 0
    ctx.db.expire(row)
    assert service.view(row)["content_hash"] == result["content_hash"]


@pytest.mark.parametrize("problem", ["unknown", "stale", "unit", "insufficient", "future"])
def test_inventory_failure_cannot_persist_quote(quoting, problem):
    ctx = quoting
    if problem == "unknown":
        ctx.observations.clear()
    else:
        ctx.observations[ctx.items[0].public_id] = InventoryObservation(
            Decimal("10") if problem == "insufficient" else Decimal("1000"),
            "piece" if problem == "unit" else "g",
            beijing_now()+timedelta(seconds={"stale": -121, "future": 60}.get(problem, 0)), "test-mirror")
    with pytest.raises(PortalError) as caught:
        create(ctx)
    assert caught.value.code in {"INVENTORY_UNAVAILABLE", "STOCK_CHANGED"}
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Quote)) == 0


@pytest.mark.parametrize("problem", ["revoked_grant", "changed_sku", "no_order", "no_price", "policy"])
def test_quote_rejects_changed_authority_or_source(quoting, problem):
    ctx = quoting
    if problem == "revoked_grant":
        ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id==ctx.items[0].id)).status = "disabled"
    elif problem == "changed_sku":
        ctx.db.execute(text("UPDATE okki_products SET size='22' WHERE product_id=101"))
    elif problem == "no_order":
        ctx.access.can_order = False
    elif problem == "no_price":
        ctx.access.can_order = ctx.access.can_view_price = False
    else:
        ctx.site.policy_json = {}
    ctx.db.commit()
    with pytest.raises(PortalError):
        create(ctx)
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Quote)) == 0


def test_quote_is_private_even_to_second_account_in_same_company(quoting):
    ctx = quoting
    first = create(ctx)
    second = Account(email_normalized="second@example.com", email_display="second@example.com", contact_name="Second", status="active")
    ctx.db.add(second)
    ctx.db.flush()
    ctx.db.add(Membership(site_id=ctx.site.id, account_id=second.id, access_id=ctx.access.id, status="active"))
    ctx.db.commit()
    ctx.preauth, ctx.token, ctx.csrf = auth_service.bootstrap(ctx.db, "127.0.0.2")
    ctx.db.commit()
    challenge, code = send_code(ctx, "second@example.com")
    _, _, token = verify(ctx, challenge, code)
    for identifier in (first["quote_id"], uuid4()):
        with pytest.raises(PortalError) as caught:
            service.detail(ctx.db, token, identifier)
        assert caught.value.status == 404


def test_disabled_write_switch_precedes_database(quoting):
    quoting.settings.PORTAL_WRITES_ENABLED = False
    with pytest.raises(PortalError) as caught:
        service.create(None, "", "", body(quoting))
    assert caught.value.status == 503


def test_tampered_snapshot_rejected(quoting):
    ctx = quoting
    first = create(ctx)
    quote = ctx.db.scalar(select(Quote))
    quote.lines_json = [{**deepcopy(quote.lines_json[0]), "unit_price": "1.0000"}]
    with pytest.raises(PortalError) as caught:
        service.view(quote)
    assert caught.value.code == "QUOTE_UNAVAILABLE"
    ctx.db.rollback()


def test_quote_and_audit_rollback_together(quoting):
    ctx = quoting
    service.create(ctx.db, ctx.session_token, ctx.session_csrf, body(ctx))
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Quote)) == 0
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=="quote.created")) == 0


def test_expired_quote_read_keeps_evidence_and_revoked_price_denies(quoting, monkeypatch):
    ctx = quoting
    first = create(ctx)
    row = ctx.db.scalar(select(Quote))
    monkeypatch.setattr(service, "beijing_now", lambda: row.expires_at)
    result = service.detail(ctx.db, ctx.session_token, first["quote_id"])
    assert result["status"] == "expired" and result["content_hash"] == first["content_hash"]
    assert row.status == "valid"
    ctx.access.can_order = ctx.access.can_view_price = False
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.detail(ctx.db, ctx.session_token, first["quote_id"])
    assert caught.value.status == 403


def test_quote_http_requires_origin_csrf_and_never_returns_internal_evidence(quoting, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    ctx = quoting
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                                     headers={"X-Real-IP": "203.0.113.1"}) as client:
            path = "/api/portal/v1/quotes"
            client.cookies.set("__Host-portal_session", ctx.session_token)
            payload = body(ctx).model_dump(mode="json")
            assert (await client.post(path, json=payload)).status_code == 403
            headers = {"Origin": ctx.settings.PORTAL_ORIGIN}
            assert (await client.post(path, json=payload, headers=headers)).status_code == 403
            headers["X-Portal-CSRF"] = ctx.session_csrf
            response = await client.post(path, json=payload, headers=headers)
            assert response.status_code == 201 and response.headers["cache-control"] == "no-store"
            assert "inventory_snapshot" not in response.text and "price_fingerprint" not in response.text
            result = response.json()["data"]
            read = await client.get(path+"/"+result["quote_id"])
            assert read.status_code == 200 and read.json()["data"] == result
            assert (await client.get(path+"/"+str(uuid4()))).status_code == 404
    asyncio.run(scenario())
