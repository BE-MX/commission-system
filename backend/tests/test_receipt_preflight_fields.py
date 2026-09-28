"""Invoice sync rejects incomplete receipt drafts before arming a remote attempt."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.receipt import invoice_link


@pytest.mark.parametrize("field,value,label", [
    ("payment_type", None, "回款方式"),
    ("payment_type", "", "回款方式"),
    ("payment_type", "   ", "回款方式"),
    ("amount", None, "回款金额"),
    ("collection_date", None, "回款日期"),
])
def test_incomplete_draft_has_actionable_error(monkeypatch, field, value, label):
    row = SimpleNamespace(attachment_ids=["proof"], receipt_id=None, status="draft", eligible=1,
        currency="USD", customer_id="101", amount=Decimal("100"),
        collection_date=date(2026, 9, 21), payment_type="T/T", remark="", attempt_token=None)
    setattr(row, field, value)
    invoice = SimpleNamespace(id=1, order_type="stock", currency="USD", customer_id="101",
        total_amount=Decimal("100"), sync_status="not_synced")
    monkeypatch.setattr(invoice_link, "get_intent", lambda *args: row)
    monkeypatch.setattr(invoice_link.attachments, "bind", lambda *args: None)
    with pytest.raises(ValueError, match=label) as exc:
        invoice_link.arm(None, invoice, 1)
    assert "保存后重新同步" in str(exc.value)
    assert row.status == "draft"
    assert row.attempt_token is None
