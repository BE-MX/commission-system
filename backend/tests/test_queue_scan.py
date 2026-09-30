"""Blocked head rows must not indefinitely hide later ready work."""
from datetime import date

from app.core import queue_scan
from app.invoice.models import Invoice


def test_rotating_scan_reaches_beyond_limit_and_wraps(db, monkeypatch):
    monkeypatch.setattr(queue_scan, "_cursors", {})
    for number in range(25):
        db.add(Invoice(invoice_no=f"QUEUE-{number}", order_type="presale", customer_id="1",
                       customer_name="Test", invoice_date=date(2026, 9, 28), currency="USD",
                       product_amount=1, total_amount=1))
    db.commit()
    query = db.query(Invoice.id).filter(Invoice.order_type == "presale")
    batches = [queue_scan.take(query, Invoice.id, "test_presale", 10) for _ in range(4)]
    assert [len(batch) for batch in batches] == [10, 10, 10, 10]
    assert len(set(batches[0] + batches[1] + batches[2])) == 25
    assert batches[3] == batches[0][5:] + batches[1][:5]
