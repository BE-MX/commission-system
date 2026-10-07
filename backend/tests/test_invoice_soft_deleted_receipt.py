"""Reproduce Rina's readable soft-deleted receipt without real business writes."""
from copy import deepcopy
from decimal import Decimal

from tests.test_invoice_deletion import execute, invoice, live, no_network, receipt, user  # noqa: F401
from app.invoice import lifecycle_remote
from app.receipt import remote


def install_soft_delete(monkeypatch, live):
    live["receipt"]["update_time"] = "2026-10-01 09:08:34"
    live["deleted_receipt"] = False
    before = deepcopy(live["receipt"])
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [] if live["deleted_receipt"] else [{"cash_collection_id": "88"}])
    def read(db, path, params):
        assert path == "/v1/invoices/receipt/list"
        match = live["deleted_receipt"] == (params["removed"] == 1)
        return {"list": [deepcopy(before)] if match else [], "totalItem": int(match)}
    monkeypatch.setattr(remote, "read", read)
    original = lifecycle_remote.request
    def request(token, kind, identity, remove=False):
        result = original(token, kind, identity, remove=remove)
        if kind == "receipt" and remove:
            live["receipt"] = deepcopy(before)
            live["deleted_receipt"] = True
        return result
    monkeypatch.setattr(lifecycle_remote, "request", request)


def test_successful_soft_delete_completes_without_waiting_for_detail_disappearance(db, invoice, receipt, live, user, monkeypatch):
    install_soft_delete(monkeypatch, live)
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["receipt"] is not None
    assert live["posts"] == ["outbound", "receipt", "order"]
    db.refresh(receipt)
    assert receipt.status == "remote_deleted"
    assert receipt.amount == Decimal("168") and receipt.bank_charge == Decimal("8")
    assert receipt.attachment_ids == ["proof-retained"] and receipt.xiaoman_receipt_id == "88"


def test_previously_uncertain_soft_delete_continues_without_repeating_receipt_post(db, invoice, receipt, live, user, monkeypatch):
    install_soft_delete(monkeypatch, live)
    live["uncertain"].add("receipt")
    assert execute(db, invoice, user)["status"] == "uncertain"
    assert live["posts"] == ["outbound", "receipt"]
    live["deleted_receipt"] = True
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]
    db.refresh(invoice)
    db.refresh(receipt)
    assert invoice.status == "cancelled" and receipt.status == "remote_deleted"
