"""Credit shipment tests use isolated SQLite and explicit supplier fixtures."""
from decimal import Decimal
import io
from uuid import uuid4
from PIL import Image

import pytest
from fastapi import HTTPException

from app.invoice import settlement_service as service, shipment_delivery as delivery
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication
from app.invoice.settlement_schemas import ShipmentCreate, ShipmentQuote
from app.receipt.models import Receipt
from app.receipt import attachments, batch_service, sync_service
from app.receipt.schemas import ReceiptFields
from tests.test_presale_settlement import presale, financial_quote, financial_create, USER


def credit_batch(db, invoice, *, quantity=4, mode="ship_first", key="credit_request_001"):
    draft = ShipmentQuote(items=[{"invoice_item_id": invoice.items[0].id, "quantity": quantity}],
        payment_term=mode)
    quoted = financial_quote(db, invoice.id, draft, USER)
    body = ShipmentCreate(**draft.model_dump(), quote_hash=quoted["quote_hash"], request_key=key)
    row = financial_create(db, invoice.id, body, USER)
    db.commit()
    return row, body


def register_payment(db, invoice, row, amount, monkeypatch, tmp_path):
    monkeypatch.setattr(attachments, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachments, "origin", lambda: "")
    png = io.BytesIO(); Image.new("RGB", (2, 2), "white").save(png, format="PNG")
    proof = attachments.register_upload(db, attachments.store_upload(
        attachments.prepare_upload(png.getvalue(), "proof.png", 1)), 1)
    db.commit()
    fields = ReceiptFields(amount=str(amount), collection_date=invoice.invoice_date,
        payment_type="TT", bank_charge="0", attachment_ids=[proof.id])
    evidence = attachments.verify_storage(attachments._bindings(
        batch_service._proof_rows(db, fields.attachment_ids, 1)))
    batch = batch_service._register_shipment_payment_verified(db, invoice, row, fields, 1, uuid4().hex, evidence)
    db.commit()
    return batch


def test_credit_can_dispatch_without_payment_but_prepaid_cannot(db, presale):
    row, _ = credit_batch(db, presale)
    assert not delivery._funded(db, row)
    assert delivery._dispatchable(db, row)
    assert service.funding_balance(db, row)["outstanding_amount"] == "4000.00"
    assert db.query(Receipt).count() == 1  # Existing deposit, never fictitious receipts.
    row.quote = {**row.quote, "payment_term": "pay_first"}
    db.commit()
    assert not delivery._dispatchable(db, row)


def test_term_is_bound_to_quote_and_original_request(db, presale):
    row, body = credit_batch(db, presale)
    assert financial_create(db, presale.id, body, USER).id == row.id
    with pytest.raises(HTTPException) as error:
        financial_create(db, presale.id, body.model_copy(update={"payment_term": "pay_first"}), USER)
    assert error.value.status_code == 409


def test_credit_without_any_first_payment_can_quote(db, presale):
    db.query(Receipt).delete()
    db.commit()
    evidence = {"receipt": {"rows": []}, "outbounds": [], "order": {"order_id": "100"}}
    draft = ShipmentQuote(items=[{"invoice_item_id": presale.items[0].id, "quantity": 1}],
        payment_term="ship_first")
    quoted = service.build_quote(db, presale, draft, evidence)
    assert quoted["new_payment_due"] == "1000.00"
    with pytest.raises(ValueError, match="首款"):
        service.build_quote(db, presale, draft.model_copy(update={"payment_term": "pay_first"}), evidence)


def test_registered_credit_payment_does_not_reduce_debt_until_effective(db, presale):
    row, _ = credit_batch(db, presale)
    target = service.target(db, presale)
    receipt = Receipt(invoice_id=presale.id, receipt_no="CREDIT-PAY", source="manual",
        receivable_id=target.id,
        purpose="presale_goods", request_key="credit_payment_key", request_hash="x"*64,
        amount=1000, bank_charge=0, currency="USD", collection_date=presale.invoice_date,
        payment_type="TT", customer_id=presale.customer_id, xiaoman_order_id="100",
        sync_status="pending", created_by=1, attachment_ids=[])
    db.add(receipt); db.flush()
    service.application(db, row, receipt, "goods", Decimal("1000"), Decimal("0"))
    db.commit()
    summary = service.funding_balance(db, row)
    assert Decimal(summary["remaining_amount"]) == 3000
    assert Decimal(summary["outstanding_amount"]) == 4000
    assert Decimal(summary["pending_amount"]) == 1000
    assert delivery._dispatchable(db, row)
    receipt.xiaoman_receipt_id = "301"
    receipt.sync_status = "synced"
    receipt.collect_status = 1
    db.commit()
    assert Decimal(service.funding_balance(db, row)["outstanding_amount"]) == 3000
    receipt.status = "voided"
    db.commit()
    assert not delivery._dispatchable(db, row)


def test_credit_inspection_completion_and_recall_keep_debt(db, presale):
    from app.invoice.shipment_inspection_service import apply
    row, _ = credit_batch(db, presale)
    outbound = ShipmentOutbound(invoice_id=presale.id, settlement_id=row.id,
        outbound_no=row.settlement_no, status="pending_remote", remote_id="501",
        payload={"record_list": []}, payload_hash="x"*64)
    db.add(outbound); db.commit()
    apply(db, outbound, row, True, funded=delivery._dispatchable(db, row))
    db.commit()
    assert (outbound.status, row.state) == ("shipped", "shipped")
    assert Decimal(service.funding_balance(db, row)["outstanding_amount"]) == 4000
    apply(db, outbound, row, False)
    db.commit()
    assert (outbound.status, row.state) == ("pending_remote", "outbound_pending")
    assert db.query(SettlementApplication).count() == 0


@pytest.mark.parametrize("state", ["shipped", "outbound_pending"])
def test_later_partial_payments_preserve_physical_state_and_exact_links(db, presale, monkeypatch, tmp_path, state):
    from app.invoice.settlement_guard import ensure_receipt_sendable
    row, _ = credit_batch(db, presale)
    row.state = state; db.commit()
    first = register_payment(db, presale, row, "1000", monkeypatch, tmp_path)
    second = register_payment(db, presale, row, "500", monkeypatch, tmp_path)
    receipts = db.query(Receipt).filter(Receipt.batch_id.in_([first.id, second.id])).all()
    assert row.state == state and len(receipts) == 2
    for receipt in receipts:
        assert ensure_receipt_sendable(db, receipt).id == row.id
        receipt.sync_status = "synced"; receipt.collect_status = 1
        receipt.xiaoman_receipt_id = str(300 + receipt.id); receipt.last_error = None
    db.commit()
    summary = service.funding_balance(db, row)
    assert Decimal(summary["outstanding_amount"]) == 2500
    assert Decimal(summary["remaining_amount"]) == 2500
    assert len(service.describe(db, row)["receipt_applications"]) == 2
    from app.receipt.service import describe
    assert describe(db, receipts[0], detail=True)["shipment_applications"][0]["settlement_id"] == row.id
    assert delivery._dispatchable(db, row)


def test_uncollected_shipped_credit_payment_can_be_voided_without_recalling_goods(db, presale, monkeypatch, tmp_path):
    row, _ = credit_batch(db, presale)
    row.state = "shipped"; db.commit()
    batch = register_payment(db, presale, row, "1000", monkeypatch, tmp_path)
    children = batch_service.ensure_batch_access(db, batch, USER)
    batch_service._void_financial(db, batch, children, USER, batch.version, "Correct unsubmitted payment")
    db.commit()
    assert row.state == "shipped"
    assert Decimal(service.funding_balance(db, row)["remaining_amount"]) == 4000
    assert db.query(SettlementApplication).one().status == "released"
    assert children[0].status == "voided" and batch.status == "voided"


def test_credit_debt_allows_next_prepaid_batch_but_never_waives_its_own_payment(db, presale):
    first, _ = credit_batch(db, presale)
    first.state = "shipped"; db.commit()
    second, _ = credit_batch(db, presale, quantity=2, mode="pay_first", key="prepaid_after_credit_001")
    assert second.quote["payment_term"] == "pay_first"
    assert not delivery._dispatchable(db, second)
    assert Decimal(service.funding_balance(db, first)["outstanding_amount"]) == 4000
    from app.receipt.service import _with_active_settlement
    summary = _with_active_settlement(db, presale, {"version": "order-v1"})
    assert {item["settlement_id"] for item in summary["payment_settlements"]} == {first.id, second.id}
    assert summary["active_settlement"]["settlement_id"] == second.id


def test_once_effective_credit_payment_cannot_become_ordinary_debt(db, presale, monkeypatch, tmp_path):
    from app.invoice.shipment_payment_policy import record_effective
    row, _ = credit_batch(db, presale)
    row.state = "shipped"; db.commit()
    batch = register_payment(db, presale, row, "1000", monkeypatch, tmp_path)
    receipt = db.query(Receipt).filter_by(batch_id=batch.id).one()
    receipt.sync_status = "synced"; receipt.collect_status = 1
    receipt.xiaoman_receipt_id = "301"; receipt.last_error = None
    db.flush(); record_effective(db, receipt, 1); db.commit()
    assert delivery._dispatchable(db, row)
    assert db.query(SettlementApplication).one().status == "reserved"
    receipt.collect_status = 0; db.commit()
    assert not delivery._dispatchable(db, row)
    evidence = {"receipt": {"rows": [{"cash_collection_id": "301", "collect_status": 0}]}}
    with pytest.raises(ValueError, match="失效"):
        service.check_shipped_funding(db, presale, evidence, [row])


def test_credit_freight_payment_releases_only_after_exact_target_binding(db, presale, monkeypatch, tmp_path):
    draft = ShipmentQuote(items=[{"invoice_item_id": presale.items[0].id, "quantity": 4}],
        freight_amount="200", payment_term="ship_first")
    quoted = financial_quote(db, presale.id, draft, USER)
    row = financial_create(db, presale.id, ShipmentCreate(**draft.model_dump(),
        quote_hash=quoted["quote_hash"], request_key="credit_freight_request_001"), USER)
    db.commit()
    register_payment(db, presale, row, "2100", monkeypatch, tmp_path)
    target = service.target(db, presale, row)
    freight = db.query(Receipt).filter_by(invoice_id=presale.id, purpose="freight").one()
    assert freight.xiaoman_order_id is None and freight.sync_status == "waiting_target"
    target.remote_order_id = "401"; target.remote_status = "bound"
    row.state = "shipped"; db.commit()
    sync_service.release_targets(db)
    db.refresh(freight)
    assert freight.xiaoman_order_id == "401" and freight.sync_status == "pending"
    assert row.state == "shipped" and delivery._dispatchable(db, row)


def test_credit_outbound_unknown_result_never_creates_a_second_supplier_request(db, presale, monkeypatch):
    from app.invoice import okki_client
    row, _ = credit_batch(db, presale)
    payload = {"serial_id": row.settlement_no, "status": 1, "record_list": [{
        "order_id": 100, "order_record_id": 11, "product_id": 1, "sku_id": 2, "outbound_count": 4}]}
    monkeypatch.setattr(delivery, "require_delivery", lambda: None)
    monkeypatch.setattr(delivery, "_live_candidate", lambda *args, **kwargs: payload)
    monkeypatch.setattr(okki_client, "find_outbound_by_serial", lambda *args: None)
    sent = []
    def push(db, body, before_send):
        before_send(); sent.append(body)
        raise okki_client.OkkiOutcomeUncertainError("Synthetic timeout after POST")
    monkeypatch.setattr(okki_client, "push_outbound", push)
    identity = delivery.queue_ready(db, row.id)
    assert identity is not None
    delivery.deliver(db, identity)
    db.refresh(row)
    assert row.state == "outbound_uncertain"
    assert db.get(ShipmentOutbound, identity).status == "uncertain"
    delivery.deliver(db, identity)
    assert delivery.queue_ready(db, row.id) is None
    assert len(sent) == 1 and db.query(ShipmentOutbound).count() == 1


def test_shared_real_prepayment_readback_does_not_require_a_single_batch(db, presale):
    from app.invoice.shipment_payment_policy import record_effective
    original = db.query(Receipt).one()
    original.purpose = "presale_advance"; db.commit()
    first, _ = credit_batch(db, presale, quantity=1)
    first.state = "shipped"; db.commit()
    second, _ = credit_batch(db, presale, quantity=1, key="credit_shared_pool_002")
    assert db.query(SettlementApplication).filter_by(receipt_id=original.id).count() == 2
    record_effective(db, original, 1)
    db.commit()
    assert delivery._dispatchable(db, first) and delivery._dispatchable(db, second)


def test_existing_legacy_payment_balance_needs_no_new_quote_fields(db, presale):
    row = ShipmentSettlement(invoice_id=presale.id, sequence=1, settlement_no="LEGACY-CREDIT-READ",
        state="awaiting_payment", is_final=0, quote={"currency": "USD", "goods_payment_due": "50.00",
            "freight_amount": "20.00", "goods_payment_charge": "5.00", "new_payment_due": "70.00"},
        quote_hash="a"*64, request_key="legacy_credit_balance_001", request_hash="b"*64, created_by=1)
    db.add(row); db.commit()
    summary = service.funding_balance(db, row)
    assert summary["payment_term"] == "pay_first"
    assert Decimal(summary["outstanding_amount"]) == 70
    assert Decimal(summary["remaining_amount"]) == 70
