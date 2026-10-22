"""Editor advisory reads; no network or shared database writes."""
from types import SimpleNamespace as NS
from fastapi import HTTPException, Response
import pytest
from app.invoice import editor_inventory, detail_router, detail_access, stock_reservations


def line(identity, **values):
    return NS(id=identity, product_id=8, sku_id=9, product_kind="hair", presale_archived=0, **values)


def invoice(remote="100"):
    return NS(id=1, xiaoman_order_id=remote, items=[line(1), line(2)])


@pytest.fixture
def stocks(monkeypatch):
    monkeypatch.setattr(stock_reservations, "read_inventory", lambda *args, **kwargs: ({(8, 9): 4}, {(8, 9): 4}))


def test_exact_line_quantities_and_stock_are_advisory(stocks, monkeypatch):
    monkeypatch.setattr(editor_inventory.detail_outbounds, "read", lambda *a: {
        "state": "ready", "summary": {"by_item": {"1": "6", "2": "0"}}})
    result = editor_inventory.read(None, invoice(), {})
    assert [(i["available_stock"], i["shipped_quantity"]) for i in result["items"]] == [(4, "6"), (4, "0")]
    assert result["source"] == "ark_free_available"


def test_unsynced_drafts_have_no_shipments_and_skip_outbound_permission(stocks, monkeypatch):
    monkeypatch.setattr(editor_inventory.detail_outbounds, "read", lambda *a: pytest.fail("drafts have no outbound"))
    assert {i["shipped_quantity"] for i in editor_inventory.read(None, invoice(None), {})["items"]} == {"0"}


@pytest.mark.parametrize("mode", ["restricted", "unverified", "missing_line"])
def test_unknown_shipped_quantity_is_never_zero(stocks, monkeypatch, mode):
    def read(*args):
        if mode == "restricted":
            raise HTTPException(403, "restricted")
        return {"state": "ready" if mode == "missing_line" else "unverified", "summary": {"by_item": {}}}
    monkeypatch.setattr(editor_inventory.detail_outbounds, "read", read)
    assert all(i["shipped_quantity"] is None for i in editor_inventory.read(None, invoice(), {})["items"])


def test_unknown_stock_and_noncurrent_lines(stocks, monkeypatch):
    monkeypatch.setattr(stock_reservations, "read_inventory", lambda *a, **kw: ({}, {}))
    saved = invoice(None)
    saved.items[0].presale_archived = 1
    saved.items[1].product_kind = "accessory"
    saved.items.append(line(3))
    result = editor_inventory.read(None, saved, {})
    assert len(result["items"]) == 1
    assert result["items"][0]["invoice_item_id"] == 3
    assert result["items"][0]["available_stock"] is None


def test_endpoint_applies_invoice_scope_and_disables_cache(stocks, monkeypatch):
    user = {"sub": "1"}
    saved = invoice(None)
    called = []
    monkeypatch.setattr(detail_access, "get_order", lambda db, identity, current: called.append((identity, current)) or saved)
    response = Response()
    detail_router.editor_inventory(1, response, None, user)
    assert called == [(1, user)]
    assert response.headers["Cache-Control"] == "private, no-store"
    def denied(*args):
        raise HTTPException(404, "not visible")
    monkeypatch.setattr(detail_access, "get_order", denied)
    with pytest.raises(HTTPException) as error:
        detail_router.editor_inventory(2, Response(), None, user)
    assert error.value.status_code == 404
