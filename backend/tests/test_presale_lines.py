"""Rolling edits preserve original facts while projecting only actual shipments."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentSettlement, SettlementItem
from app.invoice import presale_lines
from app.invoice import service, export_service, settlement_policy, xiaoman_service
from app.invoice.schemas import InvoiceUpdate
from app.receipt.models import Receipt, ReceiptIntent
from app.receipt.schemas import PresalePurposeUpdate
from app.receipt import purpose_service, sync_service
from app.receipt import invoice_link
from app.receipt.schemas import ReceiptDraft


def document(db):
    invoice = Invoice(invoice_no="ROLL", order_type="presale", customer_id="10", customer_name="Test",
        invoice_date=date(2026,10,9), currency="USD", total_amount=400, product_amount=400,
        surcharge_amount=0, shipping_fee=0)
    invoice.items = [InvoiceItem(quantity=4, total_price=400, price_per_piece=100, sort_order=1,
        xiaoman_unique_id="12", product_id=1, sku_id=2, product_name="Hair", product_display="Hair", color="Black")]
    db.add(invoice); db.flush()
    return invoice


def settlement(db, invoice, state, quantity, amount):
    row = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="ROLL-01", state=state,
        is_final=0, quote={"packaging_amount":"3.00", "handling_amount":"1.00"},
        quote_hash="a"*64, request_key="rolling_test_request", request_hash="b"*64, created_by=1)
    db.add(row); db.flush()
    db.add(SettlementItem(settlement_id=row.id, invoice_item_id=invoice.items[0].id,
        quantity=quantity, line_amount=amount, snapshot={"order_record_id":"12"}))
    db.flush()


def test_archive_actual_partial_without_rewriting_original_row(db):
    invoice = document(db); item = invoice.items[0]
    settlement(db, invoice, "shipped", 2, 200)
    carried = presale_lines.prepare_replace(db, invoice)
    assert carried == {}
    assert item.presale_archived == 1 and item.presale_shipped_quantity == 2
    assert item.presale_shipped_amount == Decimal("200")
    assert item.quantity == 4 and item.total_price == Decimal("400") and item.xiaoman_unique_id == "12"
    assert presale_lines.current_items(invoice) == []
    assert presale_lines.remote_quantity(item) == 2 and presale_lines.remote_amount(item) == Decimal("200")
    presale_lines.prepare_replace(db, invoice)
    assert item.quantity == 4 and item.presale_shipped_quantity == 2


def test_cancelled_references_remain_but_do_not_become_remote_goods(db):
    invoice = document(db); item = invoice.items[0]
    settlement(db, invoice, "cancelled", 2, 200)
    assert presale_lines.prepare_replace(db, invoice) == {}
    assert item in invoice.items and item.presale_archived == 1
    assert presale_lines.remote_items(invoice) == []


def test_unreferenced_current_identity_can_be_updated_in_place(db):
    invoice = document(db); item = invoice.items[0]
    assert presale_lines.prepare_replace(db, invoice) == {item.id:item}
    new = InvoiceItem(quantity=3, total_price=330, price_per_piece=110, sort_order=1,
        product_id=1, sku_id=2)
    presale_lines.apply_current(item, new)
    assert item.quantity == 3 and item.total_price == Decimal("330") and item.xiaoman_unique_id == "12"


def test_current_and_historical_fees_are_distinct(db):
    invoice = document(db)
    settlement(db, invoice, "shipped", 2, 200)
    presale_lines.set_current_fees(db, invoice, SimpleNamespace(internal_accessory=5, surcharge_amount=2))
    assert invoice.presale_current_accessory == 5 and invoice.presale_current_handling == 2
    assert invoice.internal_accessory == 8 and invoice.surcharge_amount == 3


def test_rolling_update_keeps_receipt_and_history_ids(db, monkeypatch):
    from tests.test_invoice_amounts import _create, _item
    monkeypatch.setattr(settlement_policy, "require_enabled", lambda: None)
    invoice = _create(db, [_item(4,100)], order_type="presale")
    original = invoice.items[0]; original.xiaoman_unique_id = "12"
    invoice.xiaoman_order_id = "100"
    settlement(db, invoice, "shipped", 2, 200)
    paid = Receipt(invoice_id=invoice.id, receipt_no="PAID", source="auto", purpose="presale_advance",
        request_key="rolling_original_receipt", request_hash="a"*64, amount=1077, bank_charge=12,
        currency="USD", collection_date=date(2026,10,8), payment_type="Other", customer_id=invoice.customer_id,
        xiaoman_order_id="100", xiaoman_receipt_id="101", collect_status=1, sync_status="synced",
        created_by=1, attachment_ids=["original-proof"])
    db.add(paid); db.flush()
    intent = db.query(ReceiptIntent).filter_by(invoice_id=invoice.id).one()
    intent.status, intent.receipt_id = "converted", paid.id
    invoice.status = invoice.sync_status = "synced"
    previous = (paid.amount, paid.bank_charge, paid.collection_date, paid.attachment_ids[:])
    body = InvoiceUpdate(customer_id=invoice.customer_id, customer_name=invoice.customer_name,
        invoice_date=invoice.invoice_date, order_type="presale", internal_accessory=5, surcharge_amount=2,
        items=[_item(3,110,id=original.id)])
    service.update_invoice(db,invoice,body,1,receipt_rows=[{"cash_collection_id":"101",
        "currency":"USD","amount":"1065.00","collect_status":1}]); db.flush()
    assert original.id != presale_lines.current_items(invoice)[0].id
    assert original in invoice.items and original.quantity == 4 and original.xiaoman_unique_id == "12"
    assert invoice.product_amount == Decimal("530.00") and invoice.total_amount == Decimal("541.00")
    assert presale_lines.editor_amounts(invoice)["total_amount"] == Decimal("337.00")
    assert (paid.amount, paid.bank_charge, paid.collection_date, paid.attachment_ids) == previous
    html = export_service.build_print_html(invoice)
    assert "USD 337.00" in html and "USD 541.00" not in html
    assert db.query(SettlementItem).one().invoice_item_id == original.id


def test_projection_omits_cancelled_rows_and_uses_actual_shipped_amount(db):
    invoice = document(db); settlement(db, invoice, "shipped", 2, 200)
    presale_lines.prepare_replace(db,invoice)
    rows, bindings, issues, _ = xiaoman_service._build_product_rows(db,invoice,None,editing=True)
    assert not issues and rows == [{"count":2,"unit_price":100.0,"cost_amount":200.0,
        "product_id":1,"sku_id":2,"unique_id":12}]
    assert bindings[0][0][0] is invoice.items[0]


def test_initial_presale_can_wait_for_product_details(db,monkeypatch):
    from tests.test_invoice_amounts import _create
    monkeypatch.setattr(settlement_policy,"require_enabled",lambda:None)
    invoice = _create(db,[],order_type="presale")
    assert service.validate_invoice(invoice) == []
    assert presale_lines.current_items(invoice) == []


def test_scheduler_generation_uses_original_advance_and_fee(db,monkeypatch):
    invoice = document(db); invoice.xiaoman_order_id="100"
    invoice.status=invoice.sync_status="synced"
    intent=ReceiptIntent(invoice_id=invoice.id,status="ready",eligible=1,amount=1077,
        purpose="presale_advance",bank_charge=12,collection_date=date(2026,10,8),
        payment_type="Other",attachment_ids=["proof"],currency="USD",customer_id="10",created_by=1)
    db.add(intent);db.commit()
    monkeypatch.setattr(sync_service.attachments,"bind",lambda *args:None)
    monkeypatch.setattr(sync_service.fees,"allocate",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("Do not recalculate original fee")))
    sync_service.generate_ready(db)
    paid=db.query(Receipt).filter_by(invoice_id=invoice.id).one()
    assert paid.purpose=="presale_advance" and paid.bank_charge==12 and paid.amount==1077
    assert paid.collection_date==date(2026,10,8) and paid.attachment_ids==["proof"]


def test_purpose_correction_preserves_original_cash_and_audits(db):
    invoice=document(db)
    paid=Receipt(invoice_id=invoice.id,receipt_no="DEP",source="auto",purpose="presale_deposit",
        request_key="purpose_correction_original",request_hash="x"*64,amount=1077,bank_charge=0,
        currency="USD",collection_date=date(2026,10,8),payment_type="Other",customer_id="10",
        xiaoman_order_id="100",xiaoman_receipt_id="101",collect_status=1,sync_status="synced",
        created_by=1,attachment_ids=["proof"])
    db.add(paid);db.flush()
    intent=ReceiptIntent(invoice_id=invoice.id,status="converted",receipt_id=paid.id,purpose="presale_deposit")
    db.add(intent);db.flush()
    purpose_service.apply(db,paid,invoice,PresalePurposeUpdate(version=paid.version,purpose="presale_advance",
        reason="User verified original payment is advance"),1)
    assert paid.purpose==intent.purpose=="presale_advance"
    assert paid.amount==1077 and paid.bank_charge==0 and paid.attachment_ids==["proof"]
    assert paid.collection_date==date(2026,10,8) and paid.xiaoman_receipt_id=="101"


def test_empty_presale_initial_advance_defaults_fee_and_generates_cash(db, monkeypatch):
    invoice = document(db)
    invoice.items.clear()
    invoice.total_amount = invoice.product_amount = Decimal(0)
    invoice.status = invoice.sync_status = "synced"
    invoice.xiaoman_order_id = "100"
    monkeypatch.setattr(invoice_link.attachments, "bind", lambda *args: None)
    draft = ReceiptDraft(amount="1077", purpose="presale_advance",
        collection_date=date(2026,10,8), payment_type="Other", attachment_ids=["proof"])
    invoice_link.save_draft(db, invoice, draft, 1, new=True)
    invoice_link.preflight(db, invoice, 1)
    intent = invoice_link.get_intent(db, invoice.id)
    assert intent.bank_charge == 0 and intent.purpose == "presale_advance"
    invoice_link.save_draft(db, invoice, draft.model_copy(update={"purpose":None}), 1)
    assert intent.bank_charge == 0 and intent.purpose == "presale_advance"
    intent.status = "ready"
    db.commit()
    sync_service.generate_ready(db)
    paid = db.query(Receipt).filter_by(invoice_id=invoice.id).one()
    assert paid.amount == 1077 and paid.bank_charge == 0 and paid.purpose == "presale_advance"
    assert paid.collection_date == date(2026,10,8) and paid.attachment_ids == ["proof"]


def test_historical_unknown_initial_fee_is_not_assumed_zero(db, monkeypatch):
    import pytest
    invoice = document(db); invoice.items.clear()
    invoice.total_amount = invoice.product_amount = Decimal(0)
    monkeypatch.setattr(invoice_link.attachments, "bind", lambda *args: None)
    draft = ReceiptDraft(amount="1077", collection_date=date(2026,10,8),
        payment_type="Other", attachment_ids=["proof"])
    invoice_link.save_draft(db, invoice, draft, 1, new=False)
    intent = invoice_link.get_intent(db, invoice.id)
    intent.eligible = 1
    with pytest.raises(ValueError):
        invoice_link.preflight(db, invoice, 1)
    assert intent.bank_charge is None
