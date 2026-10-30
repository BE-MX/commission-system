"""Net presale funding over isolated immutable historical facts."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.invoice.models import Invoice, InvoiceItem
from app.invoice.settlement_models import ShipmentSettlement, ShipmentOutbound, SettlementApplication, SettlementItem, ReceiptBatch
from app.invoice.settlement_schemas import ShipmentQuote, ShipmentCreate, BatchCreate
from app.invoice.presale_funding import plan_funding
from app.invoice import presale_runtime, settlement_service, settlement_guard
from app.receipt.models import Receipt, ReceiptLog
from app.receipt import service as receipt_service
from app.sales_return.models import SalesReturn, ReturnItem, ReturnAllocation, ReturnEffect, ReturnReceipt
from app.sales_return.presale_adjustments import projection, ensure_releasable, credit_sources


def quote(goods, *, receipt=None, paid=None, credit=False):
    paid = goods if paid is None else paid
    return {"funding_version": 2, "currency": "USD", "goods_amount": str(goods), "packaging_amount": "0",
            "handling_amount": "0", "freight_amount": "0", "funding_total_amount": str(goods),
            "goods_payment_due": str(goods - paid), "goods_payment_charge": "0", "freight_payment_due": "0",
            "new_payment_due": str(goods - paid), "deposit_applied": "0", "is_final": False,
            "payment_term": "ship_first" if credit else "pay_first", "pool_applications": ([{
                "receipt_id": receipt.id, "component": "goods", "purpose": "presale_advance", "amount": str(paid),
                "bank_charge": "0"}] if receipt and receipt.purpose == "presale_advance" else [])}


def fixture(db, *, d=200, r=200, paid=400, pool=True, credit=False):
    invoice = Invoice(invoice_no="RET-PS", invoice_date=date(2026, 10, 1), customer_id="C1", customer_name="Customer",
                      order_type="presale", currency="USD", xiaoman_order_id="101", total_amount=1000,
                      surcharge_amount=0, internal_accessory=0, shipping_fee=0, sync_status="synced")
    db.add(invoice)
    db.flush()
    receipt = Receipt(receipt_no="PS-R1", invoice_id=invoice.id, purpose="presale_advance" if pool else "presale_goods",
                      source="manual", request_key="ps-receipt-1", request_hash="hash", amount=600 if pool else paid,
                      currency="USD", collection_date=date(2026, 10, 1), payment_type="bank", bank_charge=0,
                      customer_id="C1", xiaoman_order_id="101", xiaoman_receipt_id="P1", collect_status=1,
                      status="active", sync_status="synced", created_by=1)
    db.add(receipt)
    db.flush()
    batch = ShipmentSettlement(invoice_id=invoice.id, sequence=1, settlement_no="B1", state="shipped", is_final=0,
                               quote=quote(400, receipt=receipt, paid=paid, credit=credit), quote_hash="hash",
                               request_key="ps-batch-1", request_hash="hash", created_by=1)
    db.add(batch)
    db.flush()
    app = SettlementApplication(settlement_id=batch.id, receipt_id=receipt.id, component="goods", amount=paid,
                                 bank_charge=0, status="applied")
    outbound = ShipmentOutbound(invoice_id=invoice.id, settlement_id=batch.id, outbound_no="OUT-1", status="shipped",
                                 remote_id="OUT1", payload={}, payload_hash="hash")
    db.add_all([app, outbound])
    document = SalesReturn(return_no="RET1", order_id="101", order_no="PS-1", invoice_id=invoice.id,
                            customer_id="C1", customer_name="Customer", owner_okki_user_id="A", return_type="refund_only",
                            currency="USD", reduction_amount=d, refund_amount=r, waived_amount=d-r,
                            reason_code="quality", reason="Quality", status="effective", request_key="ret1",
                            request_hash="hash", created_by=1)
    db.add(document)
    db.flush()
    db.add(ReturnItem(return_id=document.id, source_key="OUT1:L1", outbound_id="OUT1", outbound_line_id="L1",
                       order_line_id="OL1", product_id="P", sku_id="S", product_name="Goods", quantity=1,
                       reduction_amount=d, reduction_usd=d, source_snapshot={"outbound_id": "OUT1"}))
    db.add(ReturnEffect(return_id=document.id, effect_kind="activate", order_id="101", owner_okki_user_id="A",
                         customer_id="C1", currency="USD", amount=-d, amount_usd=-d, effective_date=date(2026,10,2),
                         gmv_eligible=1, order_role="repeat", departments=[], snapshot={}))
    if r:
        db.add(ReturnAllocation(return_id=document.id, original_payment_id="P1", original_principal=receipt.amount,
                                 original_principal_usd=receipt.amount, refund_amount=r, refund_amount_usd=r, basis={},
                                 funding=[{"settlement_id": batch.id, "amount": str(r)}]))
        db.add(ReturnReceipt(return_id=document.id, receipt_no="RET-R1", effect_kind="activate", order_id="101",
                              customer_id="C1", currency="USD", amount=-r, amount_usd=-r,
                              collection_date=date(2026,10,2), created_by=1))
    db.flush()
    snapshot = {"rows": [{"cash_collection_id": "P1", "amount": str(receipt.amount), "currency": "USD", "collect_status": 1}]}
    return invoice, receipt, batch, app, document, snapshot


def test_refunded_batch_keeps_free_cash_and_allows_remaining_topup_and_shipment(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db)
    receipt_service.ensure_pool_registration(db, invoice, current=True)
    summary = settlement_service.goods_balance(db, invoice, snapshot, current=True)
    assert Decimal(summary["remaining_amount"]) == 400
    assert Decimal(summary["pool_available_amount"]) == 200
    _, lots = presale_runtime.pool_lots(db, invoice, snapshot, current=True)
    assert plan_funding("600", "0", "0", lots, is_final=False)["goods_payment_due"] == "400.00"
    topup = Receipt(receipt_no="PS-R2", invoice_id=invoice.id, purpose="presale_advance", source="manual",
                    request_key="ps-receipt-2", request_hash="hash", amount=400, currency="USD",
                    collection_date=date(2026,10,3), payment_type="bank", bank_charge=0, customer_id="C1",
                    xiaoman_order_id="101", xiaoman_receipt_id="P2", collect_status=1, status="active",
                    sync_status="synced", created_by=1)
    db.add(topup)
    db.flush()
    _, lots = presale_runtime.pool_lots(db, invoice, current=True)
    assert plan_funding("600", "0", "0", lots, is_final=False)["goods_payment_due"] == "0.00"
    assert receipt.amount == 600 and app.amount == 400 and batch.quote["goods_amount"] == "400"
    funds = settlement_service.funding_balance(db, batch, current=True)
    assert Decimal(funds["total_amount"]) == Decimal(funds["effective_amount"]) == 200
    assert Decimal(funds["remaining_amount"]) == 0
    settlement_service.check_shipped_funding(db, invoice, {"receipt": snapshot, "freight": {}}, [batch], current=True)


def test_no_cash_refund_moves_only_paid_surplus_back_to_pool(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, r=0)
    _, lots = presale_runtime.pool_lots(db, invoice, current=True)
    assert Decimal(lots[0].amount) - Decimal(lots[0].allocated_amount) == 400  # Original free200 + credit200.
    assert projection(db, invoice)["releases"][app.id] == 200


def test_credit_batch_reduces_unpaid_debt_before_releasing_paid_money(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, r=0, paid=100, credit=True)
    projected = projection(db, invoice)
    assert projected["releases"].get(app.id, 0) == 0
    funds = settlement_service.funding_balance(db, batch, current=True)
    assert Decimal(funds["total_amount"]) == 200
    assert Decimal(funds["effective_amount"]) == Decimal(funds["outstanding_amount"]) == 100
    assert Decimal(funds["goods_remaining"]) == 100


def test_returned_original_batch_cannot_cancel_or_release_money_again(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db)
    with pytest.raises(ValueError, match="不能整体取消"):
        ensure_releasable(db, batch, current=True)
    graph = SimpleNamespace(outbound=None, freight=None, applications=[app], receipts={receipt.id: receipt})
    with patch("app.invoice.settlement_service.action_reason", return_value=None):
        with pytest.raises(ValueError, match="不能整体取消"):
            settlement_service._change_state_verified(db, batch, {"sub":"1"}, "cancel", batch.version, "Cancel", graph)
    assert app.status == "applied"


def test_nonpool_paid_goods_becomes_receipt_backed_credit_without_new_external_receipt(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, r=0, pool=False)
    receipts, lots = presale_runtime.pool_lots(db, invoice, current=True)
    assert len(lots) == 1 and lots[0].receipt_id == receipt.id and Decimal(lots[0].amount) == 200
    assert lots[0].goods_only and receipt.purpose == "presale_goods"
    plan = plan_funding("200", "0", "30", lots, is_final=False)
    assert plan["goods_payment_due"] == "0.00" and plan["freight_payment_due"] == "30.00"
    sources = credit_sources(db, invoice, [receipt.id], current=True)
    assert sources == {str(receipt.id): {"return_ids": [document.id]}}
    next_quote = quote(200, paid=200)
    next_quote.update(pool_applications=plan["applications"], return_credit_sources=sources)
    next_batch = ShipmentSettlement(invoice_id=invoice.id, sequence=2, settlement_no="B2", state="awaiting_payment",
                                    is_final=0, quote=next_quote, quote_hash="h", request_key="ps-batch-2", request_hash="h", created_by=1)
    db.add(next_batch)
    db.flush()
    settlement_service.application(db, next_batch, receipt, "goods", Decimal(200), Decimal(0))
    funds = settlement_service.funding_balance(db, next_batch, current=True)
    assert Decimal(funds["effective_amount"]) == 200 and Decimal(funds["remaining_amount"]) == 0
    assert db.query(Receipt).count() == 1  # Credit references do not create a second positive receipt/outbox.
    assert receipt.purpose == "presale_goods" and receipt.xiaoman_receipt_id == "P1"
    # Dispatch ownership still resolves to the original app, never the credit borrower.
    with patch("app.invoice.settlement_guard._validate_current_payment"):
        receipt.batch_id = 1
        assert settlement_guard.receipt_settlement(db, receipt, current=True).id == batch.id
    from app.receipt.sync_service import deliver
    with patch("app.receipt.remote.push") as external_send:
        deliver(db, receipt.id)
        external_send.assert_not_called()


def test_legacy_batch_blocks_only_its_own_funding_review_not_new_pool_topup(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db)
    batch.quote = {**batch.quote, "funding_version": 1}
    db.flush()
    receipt_service.ensure_pool_registration(db, invoice, current=True)
    summary = settlement_service.goods_balance(db, invoice, snapshot, current=True)
    assert Decimal(summary["remaining_amount"]) == 400
    assert summary["return_funding_issues"][0]["settlement_id"] == batch.id
    assert Decimal(summary["pool_available_amount"]) == 200
    with pytest.raises(ValueError, match="该退货旧批次"):
        settlement_service.funding_balance(db, batch, current=True)


def test_pool_credit_can_be_consumed_by_next_batch_without_reusing_cash_refund(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, r=0)
    next_quote = quote(400, receipt=receipt, paid=400)
    next_batch = ShipmentSettlement(invoice_id=invoice.id, sequence=2, settlement_no="B2", state="awaiting_payment",
                                    is_final=0, quote=next_quote, quote_hash="h", request_key="ps-batch-2", request_hash="h", created_by=1)
    db.add(next_batch)
    db.flush()
    settlement_service.application(db, next_batch, receipt, "goods", Decimal(400), Decimal(0))
    _, lots = presale_runtime.pool_lots(db, invoice, current=True)
    assert Decimal(lots[0].amount) - Decimal(lots[0].allocated_amount) == 0
    with pytest.raises(ValueError, match="占用"):
        settlement_service.application(db, next_batch, receipt, "freight", Decimal(1), Decimal(0))
    assert app.amount == 400 and receipt.amount == 600
    shown = receipt_service.describe(db, receipt, invoice, detail=True)
    assert Decimal(shown["original_allocated_amount"]) == 800
    assert Decimal(shown["allocated_amount"]) == 600 and Decimal(shown["available_amount"]) == 0
    document.status = "reversed"
    db.flush()
    with pytest.raises(ValueError, match="占用"):
        presale_runtime.pool_lots(db, invoice, current=True)


def test_goods_refund_keeps_original_fee_allocation_and_never_reuses_bank_fee(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db)
    receipt.bank_charge = app.bank_charge = Decimal(10)
    app.amount = Decimal(410)
    updated = {**batch.quote, "handling_amount": "10", "funding_total_amount": "410"}
    updated["pool_applications"] = [{**updated["pool_applications"][0], "amount": "410", "bank_charge": "10"}]
    batch.quote = updated
    db.flush()
    _, lots = presale_runtime.pool_lots(db, invoice, current=True)
    lot = lots[0]
    assert (Decimal(lot.amount), Decimal(lot.bank_charge), Decimal(lot.allocated_amount), Decimal(lot.allocated_charge)) == (
        Decimal(400), Decimal(10), Decimal(210), Decimal(10))
    funds = settlement_service.funding_balance(db, batch, current=True)
    assert Decimal(funds["total_amount"]) == Decimal(funds["effective_amount"]) == 210
    assert receipt.bank_charge == app.bank_charge == 10


def test_fully_refunded_goods_fee_only_old_lot_does_not_block_new_cash(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, d=400, r=400)
    receipt.amount = app.amount = Decimal(410)
    receipt.bank_charge = app.bank_charge = Decimal(10)
    updated = {**batch.quote, "handling_amount": "10", "funding_total_amount": "410"}
    updated["pool_applications"] = [{**updated["pool_applications"][0], "amount": "410", "bank_charge": "10"}]
    batch.quote = updated
    db.flush()
    _, lots = presale_runtime.pool_lots(db, invoice, current=True)
    assert lots == []
    extra = Receipt(receipt_no="EXTRA", invoice_id=invoice.id, purpose="presale_advance", source="manual",
                    request_key="extra-cash", request_hash="h", amount=100, bank_charge=0, currency="USD",
                    customer_id="C1", collection_date=date(2026,10,3), payment_type="bank", xiaoman_order_id="101",
                    xiaoman_receipt_id="P2", status="active", sync_status="synced", collect_status=1, created_by=1)
    db.add(extra)
    db.flush()
    _, lots = presale_runtime.pool_lots(db, invoice, current=True)
    assert len(lots) == 1 and lots[0].receipt_id == extra.id
    assert plan_funding("100", "0", "0", lots, is_final=False)["goods_payment_due"] == "0.00"


@pytest.mark.parametrize("pool", [True, False], ids=["pool-refund-plus-topup", "nonpool-return-credit"])
def test_return_to_quote_to_new_batch_is_fully_funded_without_rewriting_originals(db, monkeypatch, pool):
    invoice, receipt, original_batch, original_app, document, snapshot = fixture(db, r=200 if pool else 0, pool=pool)
    item = InvoiceItem(invoice_id=invoice.id, product_id=1, sku_id=2, product_name="Goods", product_display="Goods",
                       color="Black", quantity=10, price_per_piece=100, total_price=1000, xiaoman_unique_id="11")
    db.add(item)
    db.flush()
    invoice.items = [item]
    db.add(SettlementItem(settlement_id=original_batch.id, invoice_item_id=item.id, quantity=4,
                          line_amount=400, snapshot={"order_record_id": "11"}))
    if pool:
        topup = Receipt(receipt_no="PS-TOPUP", invoice_id=invoice.id, purpose="presale_advance", source="manual",
                        request_key="whole-flow-topup", request_hash="h", amount=400, bank_charge=0,
                        currency="USD", customer_id="C1", collection_date=date(2026,10,3), payment_type="bank",
                        xiaoman_order_id="101", xiaoman_receipt_id="P2", status="active", sync_status="synced",
                        collect_status=1, created_by=1)
        db.add(topup)
        snapshot["rows"].append({"cash_collection_id":"P2", "amount":"400", "currency":"USD", "collect_status":1})
    db.flush()
    # Provider identity/physical-inspection verification belongs to the existing
    # authorized caller. Exercise all actual local quote and funding writes.
    monkeypatch.setattr(settlement_service, "check_outbounds", lambda *_args, **_kwargs: None)
    body = ShipmentQuote(items=[{"invoice_item_id": item.id, "quantity": 6 if pool else 2}], freight_amount=0)
    evidence = {"receipt": snapshot, "freight": {}, "outbounds": []}
    calculated = settlement_service.build_quote(db, invoice, body, evidence, current=True)
    assert Decimal(calculated["new_payment_due"]) == 0
    request = ShipmentCreate(**body.model_dump(), quote_hash=calculated["quote_hash"],
                              request_key="return_followup_whole_flow")
    created = settlement_service._create_verified(db, invoice, request, {"sub":"1"}, evidence, None)
    funds = settlement_service.funding_balance(db, created, current=True)
    expected = Decimal(600 if pool else 200)
    assert Decimal(funds["total_amount"]) == Decimal(funds["effective_amount"]) == expected
    assert Decimal(funds["remaining_amount"]) == 0
    from app.invoice.shipment_delivery import _funded
    assert _funded(db, created, current=True)
    assert original_app.amount == 400 and original_batch.quote["goods_amount"] == "400"
    assert receipt.amount == (600 if pool else 400)
    assert db.query(Receipt).count() == (2 if pool else 1)
    if not pool:
        assert created.quote["return_credit_sources"] == {str(receipt.id): {"return_ids": [document.id]}}


def _original_payment_and_borrower(db):
    invoice, receipt, original, app, document, snapshot = fixture(db, r=0, pool=False, credit=True)
    original.quote = {**original.quote, "goods_payment_due": "400"}
    target = settlement_service.target(db, invoice, current=True)
    body = BatchCreate(amount="400", collection_date="2026-10-01", payment_type="bank",
                        request_key="original_payment_batch_key", allocations=[{
                            "invoice_id": invoice.id, "settlement_id": original.id, "amount":"400", "balance_version":"0"*64}])
    payment_batch = ReceiptBatch(batch_no="PAY-B1", customer_id="C1", currency="USD", gross_amount=400,
                                 collection_date=date(2026,10,1), payment_type="bank", request_key=body.request_key,
                                 request_hash=settlement_service.digest(body.model_dump(mode="json", exclude={"request_key"})), created_by=1)
    db.add(payment_batch)
    db.flush()
    receipt.batch_id, receipt.receivable_id = payment_batch.id, target.id
    borrowed_quote = quote(200, paid=200)
    borrowed_quote.update(pool_applications=[{"receipt_id": receipt.id, "component":"goods", "purpose":"presale_advance",
                                             "amount":"200", "bank_charge":"0"}],
                          return_credit_sources=credit_sources(db, invoice, [receipt.id]))
    borrower = ShipmentSettlement(invoice_id=invoice.id, sequence=2, settlement_no="CREDIT-B2", state="awaiting_payment",
                                  is_final=0, quote=borrowed_quote, quote_hash="h", request_key="credited-shipment-2",
                                  request_hash="h", created_by=1)
    db.add(borrower)
    db.flush()
    settlement_service.application(db, borrower, receipt, "goods", Decimal(200), Decimal(0))
    return invoice, receipt, original, borrower, payment_batch, body


def test_dispatch_funding_refresh_keeps_original_owner_after_credit_reuse(db, monkeypatch):
    from app.invoice import shipment_delivery
    from app.receipt import remote
    invoice, receipt, original, borrower, payment_batch, body = _original_payment_and_borrower(db)
    observed = []
    def readback(_db, identity):
        observed.append(identity)
        return {"order_id":"101", "cash_collection_id":"P1", "cash_collection_no":"HK-P1", "amount":"400",
                "real_amount":"400", "bank_charge":"0", "currency":"USD", "collection_date":"2026-10-01", "collect_status":1}
    monkeypatch.setattr(remote, "receipt_info", readback)
    with patch("app.receipt.remote.push") as external_send:
        assert shipment_delivery._refresh_funding(db, borrower.id)
        assert shipment_delivery._funded(db, borrower, current=True)
        external_send.assert_not_called()
    assert observed == ["P1"]
    assert receipt.sync_status == "synced" and receipt.last_error is None
    assert db.query(ReceiptLog).filter_by(receipt_id=receipt.id, action="credit_effective").count() == 1
    assert db.query(SettlementApplication).filter_by(receipt_id=receipt.id).count() == 2


def test_original_receipt_batch_key_replays_with_valid_credit_references(db):
    from app.receipt.batch_create_service import _replay
    invoice, receipt, original, borrower, payment_batch, body = _original_payment_and_borrower(db)
    for _ in range(2):
        _replay(db, payment_batch, [receipt], body, {"sub":"1"})
    assert db.query(Receipt).count() == 1
    assert db.query(SettlementApplication).filter_by(receipt_id=receipt.id).count() == 2


def test_uncollected_credit_registration_is_not_released_as_cash_or_sent_at_old_amount(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, r=0, pool=False, credit=True)
    receipt.collect_status, app.status = 0, "reserved"
    db.flush()
    funds = projection(db, invoice)
    assert funds["releases"].get(app.id, 0) == 0
    assert funds["credits"].get(receipt.id, 0) == 0
    assert batch.id in funds["uncollected_excess"]
    with pytest.raises(ValueError, match="未收预登记款超过"):
        settlement_service.funding_balance(db, batch, current=True)
    receipt.batch_id = 1
    db.flush()
    from app.receipt.sync_service import deliver
    with patch("app.receipt.remote.push") as external_send:
        deliver(db, receipt.id)
        external_send.assert_not_called()
    assert receipt.amount == 400 and app.amount == 400 and receipt.collect_status == 0


def test_ship_first_without_any_received_or_registered_payment_can_waive_all_goods(db):
    invoice, receipt, batch, app, document, snapshot = fixture(db, d=1000, r=0, pool=False, credit=True)
    db.delete(app)
    db.delete(receipt)
    batch.quote = quote(1000, paid=0, credit=True)
    db.flush()
    funds = settlement_service.funding_balance(db, batch, current=True)
    assert Decimal(funds["total_amount"]) == Decimal(funds["effective_amount"]) == 0
    assert Decimal(funds["remaining_amount"]) == Decimal(funds["outstanding_amount"]) == 0
    summary = settlement_service.goods_balance(db, invoice, {"rows": []}, current=True)
    assert Decimal(summary["registered_amount"]) == Decimal(summary["effective_amount"]) == 0
    assert Decimal(summary["remaining_amount"]) == 0


def _second_return(db, invoice, amount, *, status="effective", refund=0):
    number = db.query(SalesReturn).count() + 1
    row = SalesReturn(return_no=f"RET{number}", order_id="101", order_no="PS-1", invoice_id=invoice.id,
                       customer_id="C1", customer_name="Customer", owner_okki_user_id="A", return_type="refund_only",
                       currency="USD", reduction_amount=amount, refund_amount=refund, waived_amount=amount-refund,
                       reason_code="quality", reason="Quality", status=status, request_key=f"return-draft-key-{number}",
                       request_hash="hash", created_by=1)
    db.add(row)
    db.flush()
    line = {"source_key":"OUT1:L1", "outbound_id":"OUT1", "outbound_line_id":"L1", "order_line_id":"OL1",
            "product_id":"P", "sku_id":"S", "product_name":"Goods", "quantity":1,
            "reduction_amount":str(amount), "reduction_usd":str(amount)}
    db.add(ReturnItem(return_id=row.id, **line, source_snapshot=line))
    if status == "effective":
        db.add(ReturnEffect(return_id=row.id, effect_kind="activate", order_id="101", owner_okki_user_id="A",
                             customer_id="C1", currency="USD", amount=-amount, amount_usd=-amount,
                             effective_date=date(2026,10,3), gmv_eligible=1, order_role="repeat", departments=[], snapshot={}))
    db.flush()
    return row, line


def test_reverse_rejects_removing_a_frozen_credit_source_even_when_money_still_covers_borrower(db, monkeypatch):
    from app.sales_return import access, schemas, service
    from app.sales_return.router import execute
    from fastapi import HTTPException
    invoice, receipt, original, app, first, snapshot = fixture(db, d=100, r=0, pool=False)
    second, _ = _second_return(db, invoice, 100)
    borrowed_quote = quote(100, paid=100)
    borrowed_quote.update(pool_applications=[{"receipt_id":receipt.id, "component":"goods", "purpose":"presale_advance",
                                             "amount":"100", "bank_charge":"0"}],
                          return_credit_sources=credit_sources(db, invoice, [receipt.id]))
    assert borrowed_quote["return_credit_sources"][str(receipt.id)]["return_ids"] == [first.id, second.id]
    borrower = ShipmentSettlement(invoice_id=invoice.id, sequence=2, settlement_no="FROZEN-CREDIT", state="shipped",
                                  is_final=0, quote=borrowed_quote, quote_hash="h", request_key="frozen-source-shipment",
                                  request_hash="h", created_by=1)
    db.add(borrower)
    db.flush()
    settlement_service.application(db, borrower, receipt, "goods", Decimal(100), Decimal(0))
    db.commit()
    user = {"id":1, "roles":["super_admin"], "permissions":[]}
    monkeypatch.setattr(access, "current_user", lambda _db, current, *_args: current)
    effect_count = db.query(ReturnEffect).count()
    with pytest.raises(HTTPException) as rejected:
        execute(db, user, "sales_return:admin", lambda current: service.reverse(db, first.id,
            schemas.Reverse(version=first.version, request_key="reverse-frozen-source", reason="Correction"), current), write=True)
    assert rejected.value.status_code == 409 and "仍引用" in str(rejected.value.detail)
    assert db.get(SalesReturn, first.id).status == "effective"
    assert db.query(ReturnEffect).count() == effect_count
    assert projection(db, invoice)["credit_used"][receipt.id] == 100


def test_activation_rolls_back_when_fifo_refund_would_spend_already_borrowed_credit(db, monkeypatch):
    from app.models.commission import SyncedPayment
    from app.sales_return import access, schemas, service
    from app.sales_return.router import execute
    from fastapi import HTTPException
    invoice, first_receipt, original, first_app, first_return, snapshot = fixture(db, r=0, pool=False)
    first_receipt.amount = first_app.amount = Decimal(200)
    second_receipt = Receipt(receipt_no="ORIGINAL-B", invoice_id=invoice.id, purpose="presale_goods", source="manual",
        request_key="second-original-receipt", request_hash="h", amount=200, bank_charge=0, currency="USD", customer_id="C1",
        collection_date=date(2026,9,1), payment_type="bank", xiaoman_order_id="101", xiaoman_receipt_id="P2",
        status="active", sync_status="synced", collect_status=1, created_by=1)
    db.add(second_receipt)
    db.flush()
    db.add(SettlementApplication(settlement_id=original.id, receipt_id=second_receipt.id, component="goods",
                                 amount=200, bank_charge=0, status="applied"))
    db.flush()
    borrowed_quote = quote(200, paid=200)
    borrowed_quote.update(pool_applications=[{"receipt_id":second_receipt.id, "component":"goods", "purpose":"presale_advance",
                                             "amount":"200", "bank_charge":"0"}],
                          return_credit_sources=credit_sources(db, invoice, [second_receipt.id]))
    borrower = ShipmentSettlement(invoice_id=invoice.id, sequence=2, settlement_no="BORROW-B", state="shipped", is_final=0,
                                  quote=borrowed_quote, quote_hash="h", request_key="borrow-second-original", request_hash="h", created_by=1)
    db.add(borrower)
    db.flush()
    settlement_service.application(db, borrower, second_receipt, "goods", Decimal(200), Decimal(0))
    draft, line = _second_return(db, invoice, 100, status="draft", refund=100)
    order = {"order_id":"101", "customer_id":"C1", "currency":"USD", "owner_okki_user_id":"A",
             "invoice_id":invoice.id, "sales_user_id":None, "gmv_eligible":True, "order_role":"repeat", "departments":[],
             "payments":[{"payment_id":"P2", "commission_basis_usd":"200"}]}
    priced = {"order":order, "lines":[line], "quote_version":"a"*64, "reduction_amount":"100", "reduction_usd":"100",
              "refund_amount":"100", "refund_usd":"100", "waived_amount":"0", "allocations":[{
                  "original_payment_id":"P2", "original_principal":"200", "original_principal_usd":"200",
                  "refund_amount":"100", "refund_amount_usd":"100", "funding":[{"settlement_id":original.id, "amount":"100"}]}]}
    # Freeze an upstream FIFO decision as a replacement for provider evidence;
    # exercise the real activation writes and final transactional funding guard.
    monkeypatch.setattr(service, "preview", lambda *_args, **_kwargs: priced)
    monkeypatch.setattr(access, "current_user", lambda _db, current, *_args: current)
    db.commit()
    counts = {model:db.query(model).count() for model in (ReturnEffect, ReturnReceipt, ReturnAllocation, SyncedPayment)}
    user = {"id":1, "roles":["super_admin"], "permissions":[]}
    with pytest.raises(HTTPException) as rejected:
        execute(db, user, "sales_return:write", lambda current: service.activate(db, draft.id,
            schemas.Activate(version=draft.version, quote_version="a"*64, request_key="activate-borrowed-cash"), current), write=True)
    assert rejected.value.status_code == 409 and "信用余额已被后批占用" in str(rejected.value.detail)
    assert db.get(SalesReturn, draft.id).status == "draft"
    assert {model:db.query(model).count() for model in counts} == counts
    assert projection(db, invoice)["credit_used"][second_receipt.id] == 200
