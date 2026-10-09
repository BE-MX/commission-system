"""Mutable presale runtime funding; isolated SQLite and no provider writes."""
from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.invoice.models import Invoice, InvoiceItem
from app.invoice import settlement_service as shipments, shipment_delivery, shipment_state_service, presale_runtime
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement, Receivable, SettlementItem
from app.invoice.settlement_schemas import ShipmentQuote, ShipmentCreate, BatchAllocation
from app.receipt import balance, remote
from app.receipt.models import Receipt

USER = {"sub": "1", "roles": ["super_admin"], "permissions": []}


@pytest.fixture
def order(db, monkeypatch):
    monkeypatch.setattr(shipments, "require_enabled", lambda: None)
    invoice = Invoice(invoice_no="FUNDING", order_type="presale", customer_id="C1", customer_name="Veronika",
        sales_user_id=1, invoice_date=date(2026, 10, 9), currency="USD", product_amount=627,
        total_amount=627, surcharge_amount=0, shipping_fee=0, internal_accessory=0,
        sync_status="synced", xiaoman_order_id="100")
    invoice.items = [InvoiceItem(product_id=1, sku_id=2, product_name="Hair", product_display="Hair",
        color="Black", quantity=3, price_per_piece=209, total_price=627, xiaoman_unique_id="11")]
    db.add(invoice); db.commit()
    return invoice


def payment(db, order, amount="1077", purpose="presale_advance", charge="0"):
    row = Receipt(invoice_id=order.id, receipt_no=f"FUND-{db.query(Receipt).count()}", source="manual",
        purpose=purpose, request_key=f"fund_receipt_{db.query(Receipt).count():016d}", request_hash="a"*64,
        amount=Decimal(amount), bank_charge=Decimal(charge), currency="USD", collection_date=date(2026, 10, 9),
        payment_type="TT", customer_id="C1", xiaoman_order_id="100", sync_status="synced",
        collect_status=1, created_by=1, attachment_ids=[])
    db.add(row); db.flush(); row.xiaoman_receipt_id = str(200 + row.id); db.commit()
    return row


def evidence(db, order):
    return {"receipt": {"rows": [{"cash_collection_id": row.xiaoman_receipt_id,
        "amount": str(row.amount - row.bank_charge), "currency": row.currency,
        "collect_status": row.collect_status} for row in db.query(Receipt).filter_by(invoice_id=order.id)
            if row.xiaoman_receipt_id]}, "freight": {target.settlement_id: {"rows": [],
                "target_binding": [target.id, target.remote_order_id, str(target.amount), target.currency,
                    target.customer_id, target.version]} for target in db.query(Receivable).filter_by(kind="freight")},
        "outbounds": [], "order": {"order_id": "100"}}


def create(db, order, *, quantity=3, final=False, freight="38", key="runtime_shipment_001"):
    current = next(item for item in order.items if not item.presale_archived)
    draft = ShipmentQuote(items=[{"invoice_item_id": current.id, "quantity": quantity}],
        freight_amount=freight, is_final=final)
    quote = shipments.build_quote(db, order, draft, evidence(db, order), current=True)
    body = ShipmentCreate(**draft.model_dump(), quote_hash=quote["quote_hash"], request_key=key)
    row = shipments._create_verified(db, order, body, USER, evidence(db, order), None)
    db.commit()
    return row, body


def test_1077_covers_627_goods_and_38_freight_without_duplicate_cash(db, order):
    receipt = payment(db, order)
    row, _ = create(db, order)
    assert row.quote["new_payment_due"] == "0.00"
    assert row.quote["pool_balances"][0]["remaining_amount"] == "412.00"
    assert db.query(Receipt).count() == 1
    apps = db.query(SettlementApplication).all()
    assert [(app.receipt_id, app.component, app.amount) for app in apps] == [
        (receipt.id, "goods", Decimal("627")), (receipt.id, "freight", Decimal("38"))]
    funds = shipments.funding_balance(db, row, current=True)
    assert funds["funding_version"] == 2
    assert Decimal(funds["remaining_amount"]) == 0
    assert Decimal(funds["effective_amount"]) == 665
    assert shipment_delivery._funded(db, row)


def test_deposit_requires_manual_final_and_retains_residual(db, order):
    payment(db, order, purpose="presale_deposit")
    draft = ShipmentQuote(items=[{"invoice_item_id": order.items[0].id, "quantity": 3}])
    quote = shipments.build_quote(db, order, draft, evidence(db, order))
    assert not quote["is_final"] and quote["deposit_applied"] == "0.00"
    assert quote["new_payment_due"] == "627.00"
    row, _ = create(db, order, final=True, quantity=1, freight="0")
    assert row.quote["deposit_applied"] == "209.00"
    assert row.quote["pool_balances"][0]["remaining_amount"] == "868.00"


def test_cancel_releases_pool_reservations_and_replay_verifies_original_graph(db, order):
    from app.invoice import shipment_create_service
    payment(db, order)
    row, body = create(db, order, freight="0")
    captured, graph = shipment_state_service._capture(db, order, row.id, "cancel")
    shipments._change_state_verified(db, captured, USER, "cancel", row.version, "Changed batch", graph)
    db.commit()
    assert db.query(SettlementApplication).one().status == "released"
    shipment_create_service._replay(db, order, row, order.id, body, USER)
    replacement, _ = create(db, order, freight="0", key="runtime_shipment_002")
    assert replacement.quote["new_payment_due"] == "0.00"


def test_global_pool_principal_cap_blocks_concurrent_reservations(db, order):
    receipt = payment(db, order, amount="50", charge="10")
    row = ShipmentSettlement(invoice_id=order.id, sequence=1, settlement_no="CAP", is_final=0,
        quote={"currency": "USD"}, quote_hash="a"*64, request_key="cap_runtime_0001", request_hash="b"*64, created_by=1)
    db.add(row); db.flush()
    shipments.application(db, row, receipt, "goods", Decimal("35"), Decimal("0"))
    with pytest.raises(ValueError, match="本金"):
        shipments.application(db, row, receipt, "freight", Decimal("10"), Decimal("0"))


def test_source_main_receipt_funds_freight_with_empty_remote_freight_receipts(db, order, monkeypatch):
    payment(db, order)
    row, _ = create(db, order)
    target = db.query(Receivable).filter_by(settlement_id=row.id).one()
    target.remote_order_id = "300"; target.remote_status = "bound"; db.commit()
    monkeypatch.setattr(remote, "order_snapshot", lambda *_: evidence(db, order)["receipt"])
    monkeypatch.setattr(remote, "read", lambda *_: {"order_id": "100"})
    monkeypatch.setattr(remote, "order_active", lambda *_: True)
    monkeypatch.setattr(remote, "target_snapshot", lambda *_: {"rows": [], "target_binding": [target.id,
        "300", str(target.amount), "USD", "C1", target.version]})
    assert shipment_delivery._live_funding(db, order, row) == {"order_id": "100"}
    summary = balance.calculate_target(db, target, remote.target_snapshot(db, target))
    assert Decimal(summary["remaining_amount"]) == 0
    assert Decimal(summary["registered_amount"]) == Decimal(summary["effective_amount"]) == 0
    assert Decimal(summary["pool_applied_amount"]) == 38


@pytest.mark.parametrize("field,value", [("collect_status", 0), ("sync_status", "uncertain"),
    ("last_error", "changed")])
def test_ineffective_pool_cannot_fund_quote(db, order, field, value):
    receipt = payment(db, order); setattr(receipt, field, value); db.commit()
    if field == "sync_status":
        with pytest.raises(ValueError, match="待核对"):
            create(db, order)
    else:
        row, _ = create(db, order)
        assert row.quote["new_payment_due"] == "665.00"


def test_archived_items_cannot_be_selected_and_current_fees_are_prorated(db, order):
    payment(db, order)
    order.presale_current_accessory = 30; order.presale_current_handling = 6; db.commit()
    row, _ = create(db, order, quantity=1, freight="0")
    assert row.quote["packaging_amount"] == "10.00" and row.quote["handling_amount"] == "2.00"
    assert row.quote["advance_applied"] == "221.00"


def test_manual_final_marker_is_strict_and_pool_batch_inputs_are_explicit():
    with pytest.raises(ValidationError):
        ShipmentQuote(items=[{"invoice_item_id": 1, "quantity": 1}], is_final=1)
    assert BatchAllocation(invoice_id=1, amount="1077", purpose="presale_advance",
        bank_charge="12", balance_version="a"*64).settlement_id is None
    with pytest.raises(ValidationError):
        BatchAllocation(invoice_id=1, amount="1077", purpose="presale_advance",
            settlement_id=1, balance_version="a"*64)


def test_legacy_quote_balance_semantics_remain_operable(db, order):
    from app.invoice import shipment_create_service
    deposit = payment(db, order, amount="200", purpose="presale_deposit")
    row = ShipmentSettlement(invoice_id=order.id, sequence=1, settlement_no="LEGACY", is_final=1,
        quote={"currency": "USD", "goods_payment_due": "427", "freight_amount": "38",
            "goods_payment_charge": "0", "new_payment_due": "465", "deposit_applied": "200.00",
            "deposit_charge_applied": "0.00", "deposit_receipt_id": deposit.id},
        quote_hash="a"*64, request_key="legacy_runtime_0001", request_hash="b"*64, created_by=1)
    db.add(row); db.flush(); shipments.application(db, row, deposit, "deposit", Decimal("200"), Decimal("0"))
    body = ShipmentCreate(items=[{"invoice_item_id": order.items[0].id, "quantity": 3}],
        freight_amount="38", quote_hash=row.quote_hash, request_key=row.request_key)
    row.request_hash = shipments.digest(body.model_dump(mode="json", exclude={"is_final"}))
    db.add(SettlementItem(settlement_id=row.id, invoice_item_id=order.items[0].id,
        quantity=3, line_amount=627, snapshot={}))
    db.commit()
    shipment_create_service._replay(db, order, row, order.id, body, USER)
    summary = shipments.funding_balance(db, row)
    assert summary["funding_version"] == 1
    assert Decimal(summary["remaining_amount"]) == 465
    assert Decimal(summary["effective_amount"]) == 200


def legacy_final(db, order):
    receipt = payment(db, order, amount="200", purpose="presale_deposit")
    row = ShipmentSettlement(invoice_id=order.id, sequence=1, settlement_no="LEGACY-STATE", is_final=1,
        quote={"currency": "USD", "goods_payment_due": "427.00", "freight_amount": "0.00",
            "goods_payment_charge": "0.00", "new_payment_due": "427.00", "deposit_applied": "200.00",
            "deposit_charge_applied": "0.00", "deposit_receipt_id": receipt.id}, quote_hash="a"*64,
        request_key="legacy_cancel_state_001", request_hash="b"*64, created_by=1)
    db.add(row); db.flush()
    shipments.application(db, row, receipt, "deposit", Decimal("200"), Decimal("0"))
    db.add(SettlementItem(settlement_id=row.id, invoice_item_id=order.items[0].id,
        quantity=3, line_amount=627, snapshot={}))
    row.request_hash = shipments.digest(legacy_body(row, order).model_dump(mode="json", exclude={"is_final"}))
    db.commit()
    return row, receipt


def legacy_body(row, order):
    return ShipmentCreate(items=[{"invoice_item_id": order.items[0].id, "quantity": 3}],
        freight_amount="0", quote_hash=row.quote_hash, request_key=row.request_key)


@pytest.mark.parametrize("action", ["pause_resume", "cancel"])
def test_legacy_cancel_then_correct_advance_allows_current_batch_state_commands(db, order, action):
    from copy import deepcopy
    from app.invoice import shipment_create_service
    from app.receipt import purpose_service
    from app.receipt.schemas import PresalePurposeUpdate
    legacy, receipt = legacy_final(db, order)
    body, frozen = legacy_body(legacy, order), deepcopy(legacy.quote)
    row, graph = shipment_state_service._capture(db, order, legacy.id, "cancel")
    shipments._change_state_verified(db, row, USER, "cancel", row.version, "Cancel old shipment", graph)
    db.commit()
    purpose_service.apply(db, receipt, order, PresalePurposeUpdate(version=receipt.version,
        purpose="presale_advance", reason="Correct payment intent"), 1)
    db.commit()
    current, _ = create(db, order, freight="0", key="v2_after_legacy_001")
    shipment_create_service._replay(db, order, legacy, order.id, body, USER)
    for command in (["pause", "resume"] if action == "pause_resume" else ["cancel"]):
        row, graph = shipment_state_service._capture(db, order, current.id, command)
        shipments._change_state_verified(db, row, USER, command, row.version, "Change current shipment", graph)
        db.commit()
    assert current.state == ("awaiting_payment" if action == "pause_resume" else "cancelled")
    assert db.query(SettlementApplication).filter_by(settlement_id=legacy.id).one().status == "released"
    assert receipt.amount == 200 and receipt.bank_charge == 0 and receipt.purpose == "presale_advance"
    shipment_create_service._replay(db, order, legacy, order.id, body, USER)
    assert legacy.quote == frozen


def test_active_legacy_deposit_purpose_mismatch_is_rejected(db, order):
    from fastapi import HTTPException
    from app.invoice import shipment_create_service
    row, receipt = legacy_final(db, order)
    receipt.purpose = "presale_advance"; db.commit()
    with pytest.raises(ValueError, match="资金关联异常"):
        shipment_state_service._capture(db, order, row.id, "pause")
    with pytest.raises(HTTPException) as rejected:
        shipment_create_service._replay(db, order, row, order.id, legacy_body(row, order), USER)
    assert rejected.value.status_code == 409


@pytest.mark.parametrize("field,value", [("amount", Decimal("199")), ("bank_charge", Decimal("1")),
    ("component", "goods"), ("status", "reserved")])
def test_reclassified_cancelled_legacy_reference_still_requires_original_money_and_release(db, order, field, value):
    from fastapi import HTTPException
    from app.invoice import shipment_create_service
    from app.receipt import purpose_service
    from app.receipt.schemas import PresalePurposeUpdate
    legacy, receipt = legacy_final(db, order)
    row, graph = shipment_state_service._capture(db, order, legacy.id, "cancel")
    shipments._change_state_verified(db, row, USER, "cancel", row.version, "Cancel old shipment", graph)
    db.commit()
    purpose_service.apply(db, receipt, order, PresalePurposeUpdate(version=receipt.version,
        purpose="presale_advance", reason="Correct payment intent"), 1)
    db.commit()
    current, _ = create(db, order, freight="0", key="v2_after_legacy_001")
    historical = db.query(SettlementApplication).filter_by(settlement_id=legacy.id).one()
    setattr(historical, field, value); db.commit()
    with pytest.raises(ValueError, match="历史已释放预付款|资金关联异常"):
        shipment_state_service._capture(db, order, current.id, "pause")
    with pytest.raises(HTTPException) as rejected:
        shipment_create_service._replay(db, order, legacy, order.id, legacy_body(legacy, order), USER)
    assert rejected.value.status_code == 409


def test_new_effective_application_purpose_stays_strict_after_legacy_reclassification(db, order):
    from app.receipt import purpose_service
    from app.receipt.schemas import PresalePurposeUpdate
    legacy, receipt = legacy_final(db, order)
    row, graph = shipment_state_service._capture(db, order, legacy.id, "cancel")
    shipments._change_state_verified(db, row, USER, "cancel", row.version, "Cancel old shipment", graph)
    db.commit()
    purpose_service.apply(db, receipt, order, PresalePurposeUpdate(version=receipt.version,
        purpose="presale_advance", reason="Correct payment intent"), 1)
    db.commit()
    current, _ = create(db, order, freight="0", key="v2_after_legacy_001")
    receipt.purpose = "presale_deposit"; db.commit()
    with pytest.raises(ValueError, match="资金池結算|资金池结算"):
        shipment_state_service._capture(db, order, current.id, "pause")


def proof(db, monkeypatch, tmp_path):
    import io
    from PIL import Image
    from app.receipt import attachments
    monkeypatch.setattr(attachments, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachments, "origin", lambda: "")
    data = io.BytesIO(); Image.new("RGB", (2, 2), "white").save(data, format="PNG")
    row = attachments.register_upload(db, attachments.store_upload(
        attachments.prepare_upload(data.getvalue(), "payment.png", 1)), 1)
    db.commit()
    return row


def test_principal_pays_handling_and_freight_only_topup_is_accepted(db, order, monkeypatch, tmp_path):
    from app.receipt import batch_service, attachments
    from app.receipt.schemas import ReceiptFields
    order.items[0].total_price = 90; order.items[0].price_per_piece = 30
    order.total_amount = 95; order.surcharge_amount = 5; order.presale_current_handling = 5
    db.commit(); payment(db, order, amount="100")
    row, _ = create(db, order, freight="10")
    summary = shipments.funding_balance(db, row)
    assert Decimal(summary["goods_remaining"]) == Decimal(summary["charge_remaining"]) == 0
    assert Decimal(summary["freight_remaining"]) == 5
    upload = proof(db, monkeypatch, tmp_path)
    fields = ReceiptFields(amount="5", collection_date="2026-10-09", payment_type="TT", attachment_ids=[upload.id])
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db, fields.attachment_ids, 1)))
    batch_service._register_shipment_payment_verified(db, order, row, fields, 1, "funding_topup_0001", files)
    db.commit()
    assert Decimal(shipments.funding_balance(db, row)["remaining_amount"]) == 0
    child = db.query(Receipt).filter(Receipt.purpose == "freight").one()
    assert child.amount == 5 and child.bank_charge == 0


def test_released_advance_can_be_reclassified_as_deposit_without_poisoning_pool(db, order):
    import copy
    from app.invoice import shipment_create_service
    from app.receipt import purpose_service
    from app.receipt.schemas import PresalePurposeUpdate
    receipt = payment(db, order)
    row, body = create(db, order)
    original_quote = copy.deepcopy(row.quote)
    captured, graph = shipment_state_service._capture(db, order, row.id, "cancel")
    shipments._change_state_verified(db, captured, USER, "cancel", row.version, "Change intent", graph)
    db.commit()
    purpose_service.apply(db, receipt, order, PresalePurposeUpdate(version=receipt.version,
        purpose="presale_deposit", reason="Correct original intent"), 1)
    db.commit()
    shipment_create_service._replay(db, order, row, order.id, body, USER)
    assert row.quote == original_quote
    assert shipments.funding_balance(db, row)["funding_version"] == 2
    summary = shipments.goods_balance(db, order, evidence(db, order)["receipt"], current=True)
    assert Decimal(summary["pool_available_amount"]) == 1077
    replacement, _ = create(db, order, freight="0", final=True, key="reclassified_0001")
    assert replacement.quote["deposit_applied"] == "627.00"
    old_app = db.query(SettlementApplication).filter_by(settlement_id=row.id, component="goods").one()
    old_app.amount -= Decimal("1"); db.commit()
    with pytest.raises(ValueError, match="资金池分配已变化"):
        shipment_create_service._replay(db, order, row, order.id, body, USER)


def test_standalone_pool_registration_before_products_allows_arbitrary_payment(db, order, monkeypatch, tmp_path):
    from app.receipt import service, attachments
    from app.receipt.schemas import ReceiptCreate
    order.items = []; order.total_amount = 0; order.product_amount = 0; db.commit()
    upload = proof(db, monkeypatch, tmp_path)
    snapshot = {"rows": []}
    summary = shipments.goods_balance(db, order, snapshot, current=True)
    body = ReceiptCreate(invoice_id=order.id, request_key="standalone_pool_001", purpose="presale_advance",
        amount="1077", bank_charge="12", collection_date="2026-10-09", payment_type="TT",
        attachment_ids=[upload.id], balance_version=summary["version"])
    files = attachments.verify_storage(attachments.capture_binding(db, body.attachment_ids, 1, order.id, None))
    row = service._create(db, order, body, 1, "c"*64, snapshot, ["TT"], files)
    db.commit()
    assert row.purpose == "presale_advance" and row.amount == 1077 and row.bank_charge == 12


def test_batch_pool_registration_without_settlement_keeps_explicit_charge_and_replays(db, order, monkeypatch, tmp_path):
    from app.receipt import batch_create_service, batch_service, attachments, edit_service, service
    from app.invoice.settlement_schemas import BatchCreate
    upload = proof(db, monkeypatch, tmp_path)
    snapshot = {"rows": []}
    body = BatchCreate(request_key="batch_pool_money_0001", amount="1077", collection_date="2026-10-09",
        payment_type="TT", attachment_ids=[upload.id], allocations=[{"invoice_id": order.id,
            "amount": "1077", "purpose": "presale_advance", "bank_charge": "12",
            "balance_version": shipments.goods_balance(db, order, snapshot)["version"]}])
    evidence_rows = {order.id: edit_service.OrderEvidence(tuple(remote.invoice_binding(order)), (), ("TT",))}
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db, body.attachment_ids, 1)))
    batch = batch_service._create_verified(db, body, {order.id: order}, 1, evidence_rows, {}, files)
    db.commit()
    receipt = db.query(Receipt).one()
    assert receipt.purpose == "presale_advance" and receipt.amount == 1077 and receipt.bank_charge == 12
    batch_create_service._replay(db, batch, [receipt], body, USER)
    assert db.query(SettlementApplication).count() == 0


def test_archive_zero_without_remote_identity_does_not_block_current_quote(db, order):
    payment(db, order)
    historical = InvoiceItem(product_name="Cancelled", product_display="Cancelled", color="Black",
        quantity=1, price_per_piece=1, total_price=1, presale_archived=1, presale_shipped_quantity=0)
    order.items.append(historical); db.commit()
    row, _ = create(db, order, freight="0")
    assert len(row.quote["items"]) == 1


def test_prior_applied_pool_reduces_next_batch_available_funds(db, order):
    receipt = payment(db, order, amount="300")
    row, _ = create(db, order, quantity=1, freight="0")
    row.state = "shipped"
    db.query(SettlementApplication).filter_by(settlement_id=row.id).update({"status": "applied"})
    db.commit()
    second, _ = create(db, order, quantity=1, freight="0", key="second_presale_001")
    assert second.quote["advance_applied"] == "91.00"
    assert second.quote["new_payment_due"] == "118.00"


def test_pool_remote_changed_amount_or_moved_identity_blocks_quote(db, order):
    receipt = payment(db, order)
    data = evidence(db, order); data["receipt"]["rows"][0]["amount"] = "1076"
    draft = ShipmentQuote(items=[{"invoice_item_id": order.items[0].id, "quantity": 1}])
    with pytest.raises(ValueError, match="修改关联回款金额"):
        shipments.build_quote(db, order, draft, data)
    receipt.xiaoman_order_id = "999"; db.commit()
    with pytest.raises(ValueError, match="远端订单已变化"):
        shipments.build_quote(db, order, draft, evidence(db, order))


def test_new_pool_registration_is_blocked_during_active_batch_but_original_replay_is_valid(db, order):
    from app.receipt import service
    payment(db, order)
    row, _ = create(db, order, freight="0")
    with pytest.raises(ValueError, match="通过原批次补款"):
        service.ensure_pool_registration(db, order, current=True)
    assert shipments.goods_balance(db, order, evidence(db, order)["receipt"])["pool_available_amount"] == "450.00"


def test_v2_receipt_guard_rejects_changed_frozen_application(db, order, monkeypatch, tmp_path):
    from app.invoice.settlement_guard import ensure_receipt_sendable
    from app.receipt import batch_service, attachments
    from app.receipt.schemas import ReceiptFields
    payment(db, order, amount="100")
    row, _ = create(db, order, freight="0")
    upload = proof(db, monkeypatch, tmp_path)
    fields = ReceiptFields(amount="527", collection_date="2026-10-09", payment_type="TT", attachment_ids=[upload.id])
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db, fields.attachment_ids, 1)))
    batch_service._register_shipment_payment_verified(db, order, row, fields, 1, "guard_payment_001", files)
    db.commit()
    child = db.query(Receipt).filter_by(purpose="presale_goods").one()
    assert ensure_receipt_sendable(db, child, current=True).id == row.id
    app = db.query(SettlementApplication).filter_by(receipt_id=child.id).one()
    app.amount -= Decimal("1"); db.commit()
    with pytest.raises(ValueError, match="冻结资金分配"):
        ensure_receipt_sendable(db, child, current=True)


def test_second_batch_goods_shortfall_sends_even_when_old_main_cap_is_smaller(db, order, monkeypatch, tmp_path):
    from app.receipt import batch_service, attachments, sync_service
    from app.receipt.schemas import ReceiptFields
    source = payment(db, order)
    first, _ = create(db, order)
    first.state = "shipped"
    db.query(SettlementApplication).filter_by(settlement_id=first.id).update({"status": "applied"})
    target = db.query(Receivable).filter_by(settlement_id=first.id).one()
    target.remote_order_id = "300"; target.remote_status = "bound"
    order.items[0].presale_archived = 1; order.items[0].presale_shipped_quantity = 3
    order.items[0].presale_shipped_amount = 627
    order.items.append(InvoiceItem(product_id=1, sku_id=2, product_name="Next", product_display="Next",
        color="Black", quantity=1, price_per_piece=500, total_price=500, xiaoman_unique_id="12"))
    order.total_amount = 1127; order.product_amount = 1127; db.commit()
    second, _ = create(db, order, quantity=1, key="next_shipment_001")
    assert second.quote["goods_payment_due"] == "88.00" and second.quote["freight_payment_due"] == "38.00"
    upload = proof(db, monkeypatch, tmp_path)
    fields = ReceiptFields(amount="126", collection_date="2026-10-09", payment_type="TT", attachment_ids=[upload.id])
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db, fields.attachment_ids, 1)))
    batch_service._register_shipment_payment_verified(db, order, second, fields, 1, "second_cash_0001", files)
    db.commit()
    child = db.query(Receipt).filter_by(purpose="presale_goods").one()
    child.sync_status = "pending"; db.commit()
    monkeypatch.setattr(remote, "order_snapshot", lambda *_: {"rows": [{"cash_collection_id": source.xiaoman_receipt_id,
        "amount": "1077", "currency": "USD", "collect_status": 1}]})
    sent = []
    def push(_db, receipt, snapshot, before_send):
        before_send("test-payload-hash"); sent.append(receipt.amount)
        return {"cash_collection_id": "999", "cash_collection_no": "PAY999"}
    monkeypatch.setattr(remote, "push", push)
    monkeypatch.setattr(sync_service, "refresh_accepted", lambda *_: None)
    sync_service.deliver(db, child.id)
    db.refresh(child)
    assert sent == [Decimal("88.00")]
    assert child.sync_status == "synced" and child.xiaoman_receipt_id == "999"


def test_handling_only_shortfall_is_real_cash_with_zero_actual_bank_charge(db, order, monkeypatch, tmp_path):
    from app.invoice.settlement_guard import ensure_receipt_sendable
    from app.receipt import batch_service, attachments
    from app.receipt.schemas import ReceiptFields
    order.items[0].total_price = 100; order.total_amount = 105
    order.surcharge_amount = 5; order.presale_current_handling = 5; db.commit()
    payment(db, order, amount="103", charge="3")
    row, _ = create(db, order, freight="0")
    assert row.quote["goods_payment_due"] == row.quote["goods_payment_charge"] == "2.00"
    upload = proof(db, monkeypatch, tmp_path)
    fields = ReceiptFields(amount="2", collection_date="2026-10-09", payment_type="TT", attachment_ids=[upload.id])
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db, fields.attachment_ids, 1)))
    batch_service._register_shipment_payment_verified(db, order, row, fields, 1, "handling_cash_001", files)
    db.commit()
    child = db.query(Receipt).filter_by(purpose="presale_goods").one()
    assert remote.net_amount(child) == 2 and child.bank_charge == 0
    assert ensure_receipt_sendable(db, child, current=True).id == row.id
    summary = shipments.funding_balance(db, row)
    assert Decimal(summary["remaining_amount"]) == Decimal(summary["charge_remaining"]) == 0


@pytest.mark.parametrize("amount,goods,freight,capacity,fee", [
    ("2", "2", "0", "2", "2"), ("20", "0", "20", "0", "1"),
    ("20", "20", "0", "1", "2"), ("5", "1", "4", "1", "1")])
def test_actual_bank_charge_cannot_be_zero_net_goods_or_exceed_handling(amount, goods, freight, capacity, fee):
    from app.invoice.settlement_pricing import split_current_payment
    with pytest.raises(ValueError, match="实际银行手续费"):
        split_current_payment(amount, goods, freight, capacity, fee)


def test_actual_bank_charge_shifts_minimal_freight_cents_to_goods_when_capacity_allows():
    from app.invoice.settlement_pricing import split_current_payment
    parts = split_current_payment("20", "10", "90", "5", "3")
    assert parts == {"goods_amount": Decimal("3.01"), "freight_amount": Decimal("16.99"), "charge_amount": Decimal("3")}
    assert parts["goods_amount"] + parts["freight_amount"] == 20
    assert parts["goods_amount"] - parts["charge_amount"] > 0
    with pytest.raises(ValueError, match="实际银行手续费"):
        split_current_payment("20", "2", "90", "5", "3")


def test_order_balance_exposes_active_settlement_funding_version(db, order, monkeypatch):
    from app.receipt import service
    payment(db, order)
    row, _ = create(db, order, freight="0")
    monkeypatch.setattr(remote, "order_snapshot", lambda *_: evidence(db, order)["receipt"])
    assert service.order_balance(db, order)["active_settlement"]["funding_version"] == 2
    monkeypatch.setattr(remote, "order_receipts", lambda *_: evidence(db, order)["receipt"]["rows"])
    details = service.invoice_summary(db, order)
    assert details["balance"]["active_settlement"]["funding_version"] == 2
    assert details["balance"]["active_settlement"]["version"] == service.order_balance(db, order)["active_settlement"]["version"]
    assert details["action_blocked_reason"] is None
    row.state = "paused"; db.commit()
    assert service.invoice_summary(db, order)["balance"]["active_settlement"]["state"] == "paused"


def test_ordinary_receipt_legacy_hash_replays_and_changed_purpose_actor_or_key_is_rejected(db, order):
    import hashlib
    from fastapi import HTTPException
    from app.receipt import create_service
    from app.receipt.schemas import ReceiptCreate
    body = ReceiptCreate(invoice_id=order.id, request_key="legacy_ordinary_001", balance_version="a"*64,
        amount="100", collection_date="2026-10-09", payment_type="TT", attachment_ids=["proof"])
    row = payment(db, order, amount="100", purpose="ordinary")
    row.request_key = body.request_key
    row.request_hash = hashlib.sha256(body.model_dump_json(exclude={"balance_version", "purpose"}).encode()).hexdigest()
    db.commit()
    create_service._replay(row, order, body, 1)
    for changed in (body.model_copy(update={"purpose": "presale_advance"}),
            body.model_copy(update={"request_key": "changed_ordinary_001"}),
            body.model_copy(update={"invoice_id": order.id + 1})):
        with pytest.raises(HTTPException) as rejected:
            create_service._replay(row, order, changed, 1)
        assert rejected.value.status_code == 409
    with pytest.raises(HTTPException):
        create_service._replay(row, order, body, 2)


def test_v2_partial_cash_retains_actual_charge_instead_of_allocating_customer_surcharge(db, order, monkeypatch, tmp_path):
    from app.receipt import batch_service, attachments
    from app.receipt.schemas import ReceiptFields
    order.items[0].total_price = 100; order.total_amount = 105
    order.surcharge_amount = 5; order.presale_current_handling = 5; db.commit()
    payment(db, order, amount="10", purpose="presale_deposit")
    row, _ = create(db, order, freight="0")
    upload = proof(db, monkeypatch, tmp_path)
    fields = ReceiptFields(amount="50", bank_charge="1", collection_date="2026-10-09", payment_type="TT",
        attachment_ids=[upload.id])
    files = attachments.verify_storage(attachments._bindings(batch_service._proof_rows(db, fields.attachment_ids, 1)))
    batch_service._register_shipment_payment_verified(db, order, row, fields, 1, "actual_partial_001", files)
    db.commit()
    child = db.query(Receipt).filter_by(purpose="presale_goods").one()
    assert child.amount == 50 and child.bank_charge == 1 and remote.net_amount(child) == 49
    summary = shipments.funding_balance(db, row)
    assert Decimal(summary["goods_remaining"]) == 55 and Decimal(summary["charge_remaining"]) == 4
