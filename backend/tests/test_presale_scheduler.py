"""Presale dispatch must not release the ordinary receipt backlog."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.invoice.models import Invoice
from app.core import queue_scan
from app.receipt.models import Receipt
from app.receipt import scheduler


def _invoice(db, number, order_type):
    row = Invoice(invoice_no=number, order_type=order_type, customer_id="1", customer_name="Test",
                  invoice_date=date(2026, 9, 28), currency="USD", product_amount=Decimal("1"),
                  total_amount=Decimal("1"))
    db.add(row)
    db.flush()
    receipt = Receipt(invoice_id=row.id, receipt_no=number, source="manual", purpose="ordinary",
                      request_key=number, request_hash="x" * 64, amount=Decimal("1"),
                      bank_charge=Decimal("0"), currency="USD", collection_date=date(2026, 9, 28),
                      payment_type="TT", customer_id="1", created_by=1, attachment_ids=[],
                      status="active", sync_status="pending")
    db.add(receipt)
    db.flush()
    return receipt.id


@pytest.mark.parametrize("ordinary_ready,presale_ready,expected", [
    (False, False, []),
    (False, True, ["presale"]),
    (True, False, ["stock"]),
    (True, True, ["stock", "presale"]),
])
def test_scheduler_routes_only_enabled_receipt_types(db, monkeypatch, ordinary_ready, presale_ready, expected):
    monkeypatch.setattr(queue_scan, "_cursors", {})
    ordinary_id = _invoice(db, "ORD-1", "stock")
    presale_id = _invoice(db, "PRE-1", "presale")
    db.commit()

    @contextmanager
    def session():
        yield db

    sent = []
    monkeypatch.setattr(scheduler, "SessionLocal", session)
    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(RECEIPT_SYNC_ENABLED=ordinary_ready))
    monkeypatch.setattr("app.invoice.settlement_policy.capabilities", lambda: {
        "freight_delivery_enabled": presale_ready, "outbound_delivery_enabled": presale_ready})
    monkeypatch.setattr(scheduler.invoice_link, "recover_expired", lambda _: None)
    monkeypatch.setattr(scheduler, "recover_expired", lambda _: None)
    monkeypatch.setattr(scheduler, "generate_ready", lambda _: None)
    monkeypatch.setattr(scheduler, "release_targets", lambda _: None)
    monkeypatch.setattr(scheduler, "deliver", lambda _, identity: sent.append(identity))
    monkeypatch.setattr("app.invoice.freight_delivery.process_pending", lambda _: None)
    monkeypatch.setattr("app.invoice.shipment_delivery.process_pending", lambda _: None)

    scheduler.process_receipts()

    names = {ordinary_id: "stock", presale_id: "presale"}
    assert [names[identity] for identity in sent] == expected


def test_blocked_pending_receipts_do_not_starve_later_presale(db, monkeypatch):
    monkeypatch.setattr(queue_scan, "_cursors", {})
    blocked = [_invoice(db, f"ORD-{number}", "stock") for number in range(10)]
    presale_id = _invoice(db, "PRE-LAST", "presale")
    db.commit()

    @contextmanager
    def session():
        yield db

    sent = []
    monkeypatch.setattr(scheduler, "SessionLocal", session)
    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(RECEIPT_SYNC_ENABLED=True))
    monkeypatch.setattr("app.invoice.settlement_policy.capabilities", lambda: {
        "freight_delivery_enabled": True, "outbound_delivery_enabled": True})
    monkeypatch.setattr(scheduler.invoice_link, "recover_expired", lambda _: None)
    monkeypatch.setattr(scheduler, "recover_expired", lambda _: None)
    monkeypatch.setattr(scheduler, "generate_ready", lambda _: None)
    monkeypatch.setattr(scheduler, "release_targets", lambda _: None)
    monkeypatch.setattr(scheduler, "deliver", lambda _, identity: sent.append(identity))
    monkeypatch.setattr("app.invoice.freight_delivery.process_pending", lambda _: None)
    monkeypatch.setattr("app.invoice.shipment_delivery.process_pending", lambda _: None)

    scheduler.process_receipts()
    assert sent == blocked
    scheduler.process_receipts()
    assert presale_id in sent
