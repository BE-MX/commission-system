"""Receipt draft save guards use isolated SQLite; no real provider calls."""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.invoice import product_service, service, settlement_policy
from app.invoice.models import Invoice
from app.invoice.schemas import InvoiceCreate, InvoiceItemPayload, InvoiceUpdate
from app.receipt import invoice_link
from app.receipt.models import ReceiptIntent
from app.receipt.schemas import ReceiptDraft


@pytest.fixture
def body(monkeypatch):
    monkeypatch.setattr(product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    monkeypatch.setattr(settlement_policy, "require_enabled", lambda: None)
    return InvoiceCreate(
        invoice_no="RECEIPT-SAVE", order_type="stock", customer_id="101", customer_name="Test",
        invoice_date="2026-10-20", currency="USD", shipping_fee="0",
        receipt_draft=ReceiptDraft(amount="100"),
        items=[InvoiceItemPayload(product_id=1, sku_id=9001, product_name="Hair",
            product_display="Hair", color="#1", quantity=2, price_per_piece="50")],
    )


def test_create_rejects_excess_receipt_before_commit(db, body):
    body.receipt_draft.amount = Decimal("100.01")
    with pytest.raises(ValueError, match="回款金额.*100.01.*订单总额.*100.00"):
        service.create_invoice(db, body, 1)
    db.rollback()
    assert db.query(Invoice).count() == 0
    assert db.query(ReceiptIntent).count() == 0


def test_save_api_returns_specific_error_and_rolls_back(db, body):
    from app.invoice.router import _write_invoice_or_400
    body.receipt_draft.amount = Decimal("100.01")
    with pytest.raises(HTTPException) as error:
        _write_invoice_or_400(db, lambda: service.create_invoice(db, body, 1))
    assert error.value.status_code == 400
    assert "100.01" in error.value.detail and "100.00" in error.value.detail
    assert db.query(Invoice).count() == 0
    assert db.query(ReceiptIntent).count() == 0


@pytest.mark.parametrize("amount", ["0", "100", "99.99", None])
def test_create_allows_zero_partial_and_exact_payment(db, body, amount):
    body.receipt_draft.amount = Decimal(amount) if amount is not None else None
    invoice = service.create_invoice(db, body, 1)
    db.commit()
    assert invoice.total_amount == Decimal("100")
    assert invoice_link.get_intent(db, invoice.id).amount == body.receipt_draft.amount


@pytest.mark.parametrize("include_draft", [True, False])
def test_reducing_total_checks_existing_draft_even_when_omitted(db, body, include_draft):
    invoice = service.create_invoice(db, body, 1)
    db.commit()
    invoice_id = invoice.id
    update = InvoiceUpdate(**body.model_dump())
    update.items[0].price_per_piece = Decimal("49")
    if not include_draft:
        update.receipt_draft = None
    with pytest.raises(ValueError, match="回款金额.*100.00.*订单总额.*98.00"):
        service.update_invoice(db, invoice, update, 1)
    db.rollback()
    assert db.get(Invoice, invoice_id).total_amount == Decimal("100")
    assert invoice_link.get_intent(db, invoice_id).amount == Decimal("100")


def test_edit_rejects_new_excess_amount_and_retains_original(db, body):
    invoice = service.create_invoice(db, body, 1)
    db.commit()
    update = InvoiceUpdate(**body.model_dump())
    update.receipt_draft.amount = Decimal("100.01")
    with pytest.raises(ValueError, match="回款金额"):
        service.update_invoice(db, invoice, update, 1)
    db.rollback()
    assert invoice_link.get_intent(db, invoice.id).amount == Decimal("100")


def test_existing_excess_draft_can_be_corrected_without_changing_order(db, body):
    invoice = service.create_invoice(db, body, 1)
    intent = invoice_link.get_intent(db, invoice.id)
    intent.amount = Decimal("105")  # Historical draft saved before the guard existed.
    db.commit()
    service.update_invoice(db, invoice, InvoiceUpdate(**body.model_dump()), 1)
    db.commit()
    assert invoice_link.get_intent(db, invoice.id).amount == Decimal("100")
    assert invoice.total_amount == Decimal("100")


def test_presale_draft_keeps_existing_advance_rules(db, body):
    body.order_type = "presale"
    body.receipt_draft = ReceiptDraft(amount="200", purpose="presale_advance")
    invoice = service.create_invoice(db, body, 1)
    db.commit()
    assert invoice_link.get_intent(db, invoice.id).amount == Decimal("200")


def test_frozen_intent_does_not_revalidate_historical_payment(db, body):
    invoice = service.create_invoice(db, body, 1)
    intent = invoice_link.get_intent(db, invoice.id)
    intent.status = "armed"
    db.flush()
    invoice.total_amount = Decimal("50")
    invoice_link.save_draft(db, invoice, body.receipt_draft, 1)
    assert intent.amount == Decimal("100")


def test_invalid_new_draft_does_not_bind_proofs_or_create_intent(db, monkeypatch):
    invoice = Invoice(id=999, order_type="stock", total_amount=Decimal("100"), currency="USD")
    def forbidden(*args):
        pytest.fail("Invalid draft must be rejected before proof binding")
    monkeypatch.setattr(invoice_link.attachments, "bind", forbidden)
    with pytest.raises(ValueError, match="回款金额"):
        invoice_link.save_draft(db, invoice, ReceiptDraft(amount="100.01", attachment_ids=["proof"]), 1)
    assert not any(isinstance(row, ReceiptIntent) for row in db.new)
