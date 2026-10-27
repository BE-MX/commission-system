"""Order numbers and provider IDs remain distinct through recovery callers."""
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.invoice import sync_recovery, xiaoman_service
from app.invoice.models import InvoiceSyncLog, OkkiOutboundTask
from tests.test_invoice_outbound_tasks import _make_invoice, _seed_settings, _stock_item


def pending_order(db):
    _seed_settings(db)
    invoice = _make_invoice(db, status="sync_uncertain", sync_status="sync_uncertain")
    invoice.items.append(_stock_item())
    db.execute(text("""INSERT INTO lsordertest.okki_orders
        (order_id,order_no,name,company_id) VALUES ('424242','26917',:name,:customer)"""),
        {"name": invoice.invoice_no, "customer": invoice.customer_id})
    db.commit()
    return invoice


def test_bind_by_provider_id_preserves_number_and_does_not_enqueue(db, monkeypatch):
    invoice = pending_order(db)
    monkeypatch.setattr(xiaoman_service, "get_settings", lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=True))
    xiaoman_service.resolve_sync_uncertain(db, invoice, resolution="bind_order",
        reason="Reviewed original provider order", operator_id=1, xiaoman_order_id="424242")
    db.commit()
    assert (invoice.xiaoman_order_id, invoice.xiaoman_order_no) == ("424242", "26917")
    assert (invoice.status, invoice.sync_status) == ("ready", "not_synced")
    assert db.query(OkkiOutboundTask).count() == 0


def test_clear_unknown_accepts_empty_provider_id_without_type_error(db):
    invoice = pending_order(db)
    xiaoman_service.resolve_sync_uncertain(db, invoice, resolution="confirm_not_created",
        reason="Reviewed provider absence", operator_id=1, xiaoman_order_id=None)
    db.commit()
    assert invoice.xiaoman_order_id is None and invoice.sync_status == "not_synced"


@pytest.mark.parametrize("provider_id,number", [("0424242", None), ("26917", None),
    ("424242", "different-number"), ("not-an-id", None)])
def test_invalid_or_conflicting_binding_identifiers_do_not_change_invoice(db, provider_id, number):
    invoice = pending_order(db)
    with pytest.raises(ValueError):
        xiaoman_service.resolve_sync_uncertain(db, invoice, resolution="bind_order",
            reason="Reviewed provider identity", operator_id=1,
            xiaoman_order_id=provider_id, xiaoman_order_no=number)
    assert invoice.xiaoman_order_id is None and invoice.sync_status == "sync_uncertain"
    assert db.query(InvoiceSyncLog).count() == 0


def test_portal_recovery_accepts_number_from_invoice_list(db, monkeypatch):
    invoice = pending_order(db)
    monkeypatch.setattr(xiaoman_service, "get_settings", lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=True))
    monkeypatch.setattr(sync_recovery.edit_authority, "prepare_recovery",
        lambda *args: (invoice, {"id": 1}))
    monkeypatch.setattr(sync_recovery, "current_response", lambda *args: {
        "xiaoman_order_id": invoice.xiaoman_order_id, "sync_status": invoice.sync_status})
    result = sync_recovery.resolve(db, invoice.id, {"id": 1}, resolution="bind_order",
        reason="Reviewed original provider order", xiaoman_order_no="26917")
    assert result == {"xiaoman_order_id": "424242", "sync_status": "not_synced"}


def test_simultaneous_identifiers_reject_ambiguous_number(db):
    invoice = pending_order(db)
    db.execute(text("""INSERT INTO lsordertest.okki_orders
        (order_id,order_no,name,company_id) VALUES ('424243','26917','another','another')"""))
    with pytest.raises(ValueError, match="不唯一"):
        xiaoman_service.resolve_sync_uncertain(db, invoice, resolution="bind_order",
            reason="Reviewed both identifiers", operator_id=1,
            xiaoman_order_id="424242", xiaoman_order_no="26917")
    assert invoice.xiaoman_order_id is None


def test_portal_route_forwards_explicit_order_number(db, monkeypatch):
    from app.portal import authority
    from tests.test_invoice_screenshot_import import _api_client
    invoice = pending_order(db)
    seen = {}
    def resolve(*args, **kwargs):
        seen.update(kwargs)
        return {"sync_status": "not_synced"}
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=True))
    monkeypatch.setattr(sync_recovery, "resolve", resolve)
    with _api_client(db, ["invoice:admin"]) as client:
        result = client.post(f"/api/invoice/invoices/{invoice.id}/sync-uncertain/resolve",
            json={"resolution": "bind_order", "xiaoman_order_no": "26917", "reason": "核对原单"})
    assert result.status_code == 200, result.text
    assert seen["xiaoman_order_no"] == "26917" and seen["xiaoman_order_id"] is None


@pytest.mark.parametrize("number,expected_status", [(None, 200), ("conflicting-number", 400)])
def test_legacy_route_preserves_provider_id_and_identifier_conflicts(db, monkeypatch, number, expected_status):
    from app.portal import authority
    from tests.test_invoice_screenshot_import import _api_client
    invoice = pending_order(db)
    invoice.sales_user_id = invoice.created_by = 27
    db.commit()
    monkeypatch.setattr(authority, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=False))
    monkeypatch.setattr(xiaoman_service, "get_settings", lambda: SimpleNamespace(OKKI_OUTBOUND_AUTO_ENABLED=True))
    with _api_client(db, ["invoice:admin"]) as client:
        response = client.post(f"/api/invoice/invoices/{invoice.id}/sync-uncertain/resolve",
            json={"resolution": "bind_order", "xiaoman_order_id": "424242",
                "xiaoman_order_no": number, "reason": "核对原单"})
    assert response.status_code == expected_status, response.text
    db.refresh(invoice)
    if expected_status == 200:
        assert (invoice.xiaoman_order_id, invoice.xiaoman_order_no) == ("424242", "26917")
        assert invoice.sync_status == "not_synced"
    else:
        assert invoice.xiaoman_order_id is None and invoice.sync_status == "sync_uncertain"
        assert db.query(InvoiceSyncLog).count() == 0
