"""Invoice sync rejects incomplete receipt drafts before arming a remote attempt."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.invoice import order_sync_execution
from app.receipt import invoice_link
from app.receipt.schemas import ReceiptUpdate, ReceiptProofUpdate


@pytest.mark.parametrize("schema", [ReceiptUpdate, ReceiptProofUpdate])
def test_receipt_edits_require_explicit_attachment_choice(schema):
    fields = {"version": 1}
    if schema is ReceiptUpdate:
        fields.update(amount="100", collection_date="2026-10-30", payment_type="T/T")
    with pytest.raises(ValidationError, match="attachment_ids"):
        schema(**fields)
    assert schema(**fields, attachment_ids=[]).attachment_ids == []


@pytest.mark.parametrize("field,value,label", [
    ("payment_type", None, "回款方式"),
    ("payment_type", "", "回款方式"),
    ("payment_type", "   ", "回款方式"),
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


@pytest.mark.parametrize("order_type", ["stock", "presale"])
def test_positive_receipt_without_proof_can_arm(monkeypatch, order_type):
    row = SimpleNamespace(status="draft", amount=Decimal("2939.48"), attachment_ids=[],
        attempt_token=None, receipt_id=None, eligible=1, currency="USD", customer_id="101",
        collection_date=date(2026, 10, 30), payment_type="Other", remark="", created_by=20,
        bank_charge=Decimal("0"))
    invoice = SimpleNamespace(id=1528, order_type=order_type, total_amount=Decimal("3184.63"),
        currency="USD", customer_id="101", sync_status="not_synced")
    monkeypatch.setattr(invoice_link, "get_intent", lambda *args: row)
    monkeypatch.setattr(invoice_link.attachments, "bind", lambda *args: None)
    db = Mock()
    token = invoice_link.arm(db, invoice, 20)
    assert row.status == "armed" and row.attempt_token == token
    assert token and row.amount == Decimal("2939.48") and row.attachment_ids == []


def test_unexpected_push_value_error_remains_private(monkeypatch):
    def invalid_state(*args):
        raise ValueError("private provider payload and credentials")

    monkeypatch.setattr(order_sync_execution, "prepare", invalid_state)
    db = Mock()
    with pytest.raises(HTTPException) as error:
        order_sync_execution.run.__wrapped__(db, 1, {"id": 20})
    assert error.value.status_code == 409
    assert error.value.detail == "当前订单、库存或回款资料不允许推送"
    assert error.value.headers["Cache-Control"] == "private, no-store"
    db.rollback.assert_called_once()
