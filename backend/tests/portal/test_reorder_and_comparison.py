import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, func, update

from test_proposals import proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, propose
from app.invoice.models import CustomerPriceRule
from app.portal import reorder_service, order_queries
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Revision, RequestLine, Quote, CatalogGrant
from app.portal.schemas import ReorderInput


def reorder(ctx, order, **body):
    return reorder_service.create_quote(ctx.db, ctx.session_token, ctx.session_csrf,
        order["request_id"], ReorderInput(**body))


def test_proposal_difference_preserves_unknown_fees_and_historical_values(proposing):
    ctx, order = proposing
    propose(ctx, order, items=[{"item_id":ctx.items[0].public_id,"quantity":4}])
    detail = order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    diff = detail["proposal"]["changes"]
    fields = {row["field"]:row for row in diff["fields"]}
    assert diff["before_revision_kind"] == "submitted"
    assert fields["shipping_amount"] == {"field":"shipping_amount","before":None,"after":"45.00"}
    assert fields["total_amount"]["before"] is None
    assert fields["total_amount"]["after"] == "155.00"
    line = diff["items"][0]
    assert line["before"]["quantity"] == 3 and line["after"]["quantity"] == 4
    assert line["before"]["line_amount"] == "81.00"
    rule = ctx.db.get(CustomerPriceRule, 1)
    rule.adjust_value = 0
    ctx.db.commit()
    assert order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])["proposal"]["changes"] == diff
    serialized = json.dumps(diff)
    for private in ("product_id", "sku_id", "price_fingerprint", "authority_versions", "sales_user_id"):
        assert private not in serialized
    ctx.access.can_view_price = ctx.access.can_order = False
    ctx.db.commit()
    hidden = order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    assert "proposal" not in hidden and "unit_price" not in json.dumps(hidden)


def test_corrupt_baseline_does_not_produce_misleading_comparison(proposing):
    ctx, order = proposing
    baseline = ctx.db.scalar(select(Revision))
    propose(ctx, order)
    ctx.db.execute(update(RequestLine).where(RequestLine.revision_id == baseline.id).values(qty=999))
    ctx.db.commit()
    with pytest.raises(PortalError):
        order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])


def test_reorder_reprices_without_creating_request_or_reusing_po(submitted):
    ctx, order = submitted
    original = ctx.db.scalar(select(Revision))
    old_hash = original.content_hash
    unchanged = reorder(ctx, order)
    assert unchanged["reorder"]["changes"] == []
    ctx.db.commit()
    ctx.db.get(CustomerPriceRule, 1).adjust_value = 0
    ctx.db.commit()
    fresh = reorder(ctx, order)
    ctx.db.commit()
    assert fresh["items"][0]["unit_price"] == "30.0000"
    assert fresh["product_amount"] == "90.00"
    assert fresh["total_amount"] is None
    change = fresh["reorder"]["changes"][0]
    assert change["before"]["unit_price"] == "27.0000"
    assert change["after"]["unit_price"] == "30.0000"
    assert "unit_price" in change["changed_fields"]
    assert ctx.db.scalar(select(func.count()).select_from(OrderRequest)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(Revision)) == 1
    assert original.content_hash == old_hash
    quote = ctx.db.scalar(select(Quote).order_by(Quote.id.desc()))
    assert quote.status == "valid"
    assert quote.customer_po == "" and original.request_id is not None
    assert quote.delivery_json == original.delivery_json


@pytest.mark.parametrize("cause", ["selection", "foreign", "capability", "withdrawn", "inventory"])
def test_reorder_fails_closed_without_persisting_quote(submitted, cause):
    ctx, order = submitted
    args = {}
    expected = None
    if cause == "selection":
        args = {"line_keys":[uuid4()]}
        expected = "INVALID_INPUT"
    elif cause == "foreign":
        order = {"request_id":str(uuid4())}
        expected = "RESOURCE_NOT_FOUND"
    elif cause == "capability":
        ctx.access.can_order = False
        ctx.db.commit()
    elif cause == "withdrawn":
        grant = ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == ctx.items[0].id))
        ctx.db.delete(grant)
        ctx.db.commit()
        expected = "REORDER_CHANGED"
    else:
        ctx.observations = {}
    count = ctx.db.scalar(select(func.count()).select_from(Quote))
    with pytest.raises(PortalError) as caught:
        reorder(ctx, order, **args)
    if expected:
        assert caught.value.code == expected
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Quote)) == count


def test_reorder_rejects_duplicate_selection():
    key = uuid4()
    with pytest.raises(ValidationError):
        ReorderInput(line_keys=[key,key])


def test_quote_quantity_rules_are_public_but_raw_inventory_remains_private(submitted):
    from app.portal import quote_service
    ctx, order = submitted
    ctx.items[0].min_qty = 2
    ctx.items[0].step_qty = 1
    ctx.db.commit()
    result = reorder(ctx, order)
    ctx.db.commit()
    assert result["items"][0]["min_order_qty"] == 2
    assert result["items"][0]["step_qty"] == 1
    for private in ("inventory_snapshot", "safety_buffer", "conversion_factor", "price_fingerprint", "standard_snapshot"):
        assert private not in json.dumps(result)
    quote = ctx.db.scalar(select(Quote).order_by(Quote.id.desc()))
    ctx.items[0].min_qty = 10
    ctx.items[0].step_qty = 5
    ctx.db.commit()
    # Reading an earlier quote must not rewrite its immutable commercial evidence.
    old = quote_service.view(quote)
    assert old["items"][0]["min_order_qty"] == 2
    assert old["items"][0]["step_qty"] == 1


def test_reorder_uses_current_alias_without_rewriting_old_evidence(submitted):
    from app.portal import mapping_service
    from app.portal.schemas import MappingInput
    ctx, order = submitted
    old = order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    old_hash = ctx.db.scalar(select(Revision)).content_hash
    mapping_service.publish(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
        MappingInput(base_version=ctx.access.mapping_version, entries=[{
            "kind":"sku", "source_key":ctx.items[0].public_id,
            "item_id":ctx.items[0].public_id, "display_value":"New Client Collection"}]))
    ctx.db.commit()
    fresh = reorder(ctx, order)
    assert fresh["items"][0]["display_snapshot"]["model_name"] == "New Client Collection"
    assert fresh["reorder"]["changes"][0]["changed_fields"] == ["display_snapshot"]
    assert order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])["items"] == old["items"]
    assert ctx.db.scalar(select(Revision)).content_hash == old_hash


def test_added_removed_rows_and_selected_reorder(proposing):
    ctx, order = proposing
    propose(ctx, order, items=[{"item_id":ctx.items[1].public_id,"quantity":2}])
    detail = order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    changes = detail["proposal"]["changes"]["items"]
    assert [line["change"] for line in changes] == ["removed","added"]
    assert changes[0]["after"] is None and changes[1]["before"] is None
    fresh = reorder(ctx, order, line_keys=[changes[1]["line_key"]])
    assert len(fresh["items"]) == 1 and fresh["items"][0]["quantity"] == 2
    assert fresh["items"][0]["item_id"] == ctx.items[1].public_id


def test_reorder_http_requires_origin_csrf_and_returns_fresh_quote(submitted, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    ctx, order = submitted
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                headers={"X-Real-IP":"203.0.113.1"}) as client:
            path = "/api/portal/v1/orders/" + order["request_id"] + "/reorder-quote"
            client.cookies.set("__Host-portal_session", ctx.session_token)
            assert (await client.post(path, json={})).status_code == 403
            client.headers["Origin"] = ctx.settings.PORTAL_ORIGIN
            assert (await client.post(path, json={})).status_code == 403
            client.headers["X-Portal-CSRF"] = ctx.session_csrf
            response = await client.post(path, json={})
            assert response.status_code == 201
            assert response.json()["code"] == 201
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["data"]["reorder"]["source_request_id"] == order["request_id"]
    asyncio.run(scenario())
