"""Isolated ledger tests. All remote reads are explicit fixtures; no live network."""
from decimal import Decimal
from datetime import date
import pytest

from app.invoice.models import Invoice, InvoiceItem
from app.invoice import settlement_service as service
from app.invoice.settlement_models import ShipmentSettlement, SettlementApplication
from app.invoice.settlement_schemas import ShipmentCreate, ShipmentQuote
from app.receipt.models import Receipt

USER = {"sub": "1", "roles": ["super_admin"], "permissions": []}


@pytest.fixture
def presale(db, monkeypatch):
    monkeypatch.setattr(service, "require_enabled", lambda: None)
    invoice = Invoice(invoice_no="PRE-1", order_type="presale", customer_id="C1", customer_name="Customer",
        sales_user_id=1, invoice_date=date(2026, 9, 23), currency="USD", product_amount=10000,
        total_amount=10000, surcharge_amount=0, shipping_fee=0, internal_accessory=0,
        status="synced", sync_status="synced", xiaoman_order_id="100")
    invoice.items = [InvoiceItem(product_id=1, sku_id=2, product_name="Hair", product_display="Hair",
        color="Black", quantity=10, price_per_piece=1000, total_price=10000, xiaoman_unique_id="11")]
    db.add(invoice); db.flush()
    deposit = Receipt(invoice_id=invoice.id, receipt_no="DEP", source="auto", purpose="presale_deposit",
        request_key="deposit_request_001", request_hash="x"*64, amount=3000, bank_charge=0,
        currency="USD", collection_date=date(2026,9,23), payment_type="TT", customer_id="C1",
        xiaoman_order_id="100", xiaoman_receipt_id="201", collect_status=1,
        sync_status="synced", created_by=1, attachment_ids=[])
    db.add(deposit); db.commit()
    monkeypatch.setattr(service, "fetch_evidence", lambda *_: {"receipt": {"rows": [{
        "cash_collection_id":"201", "amount":"3000.00", "currency":"USD", "collect_status":1}]},
        "outbounds": [], "order": {"order_id":"100"}})
    return invoice


def make(db, invoice, quantity=4, freight="200.00", key="shipment_request_001"):
    draft=ShipmentQuote(items=[{"invoice_item_id":invoice.items[0].id,"quantity":quantity}],freight_amount=freight)
    quote=service.quote(db,invoice.id,draft,USER)
    return service.create(db,invoice.id,ShipmentCreate(**draft.model_dump(),quote_hash=quote["quote_hash"],request_key=key),USER)


def test_partial_keeps_deposit_and_original_total(db,presale):
    row=make(db,presale)
    assert row.quote["new_payment_due"]=="4200.00"
    assert row.quote["deposit_applied"]=="0.00"
    assert presale.total_amount==Decimal("10000")
    assert db.query(SettlementApplication).count()==0


def test_presale_quote_rejects_unmapped_or_shared_okki_product_line(db,presale):
    presale.items[0].product_id = None
    with pytest.raises(ValueError, match="独立 OKKI 产品行"):
        make(db,presale)
    presale.items[0].product_id = 1
    presale.items.append(InvoiceItem(product_id=1, sku_id=2, product_name="Other", product_display="Other",
        color="Black", quantity=1, price_per_piece=100, total_price=100, xiaoman_unique_id="11"))
    db.flush()
    with pytest.raises(ValueError, match="共享 OKKI 明细"):
        make(db,presale)


def test_duplicate_returns_same_and_blocks_second_batch(db,presale):
    first=make(db,presale); db.commit()
    assert db.query(ShipmentSettlement).count()==1
    with pytest.raises(ValueError,match="活动|未完成"):
        make(db,presale,key="shipment_request_002")
    assert first.sequence==1


def test_partial_cannot_spend_last_deposit(db,presale):
    with pytest.raises(ValueError): make(db,presale,quantity=8)


def test_final_reserves_deposit_without_new_receipt(db,presale):
    row=make(db,presale,quantity=10,freight="150.00")
    assert row.quote["new_payment_due"]=="7150.00"
    assert db.query(Receipt).count()==1
    assert db.query(SettlementApplication).one().amount==3000


def test_cancel_unpaid_final_releases_only_application(db,presale):
    row=make(db,presale,quantity=10,freight="0.00")
    service.change_state(db,row,USER,"cancel",row.version,"暂不发货")
    assert row.state=="cancelled"
    assert db.query(Receipt).one().status=="active"
    assert db.query(SettlementApplication).one().status=="released"


def test_unknown_remote_payment_freezes_new_settlement(db,presale,monkeypatch):
    evidence=service.fetch_evidence(db,presale)
    evidence["receipt"]["rows"].append({"cash_collection_id":"999", "amount":"4000",
        "currency":"USD", "collect_status":1})
    monkeypatch.setattr(service,"fetch_evidence",lambda *a:evidence)
    with pytest.raises(ValueError,match="未分配的远端回款"):
        make(db,presale)
    assert db.query(ShipmentSettlement).count()==0


def test_create_replay_uses_same_settlement_and_does_not_reserve_twice(db,presale):
    draft=ShipmentQuote(items=[{"invoice_item_id":presale.items[0].id,"quantity":10}])
    quoted=service.quote(db,presale.id,draft,USER)
    body=ShipmentCreate(**draft.model_dump(),quote_hash=quoted["quote_hash"],request_key="shipment_replay_001")
    first=service.create(db,presale.id,body,USER); db.commit()
    replay=service.create(db,presale.id,body,USER)
    assert replay.id==first.id
    assert db.query(SettlementApplication).count()==1


def test_quote_hash_cannot_hide_contract_or_quantity_change(db,presale):
    draft=ShipmentQuote(items=[{"invoice_item_id":presale.items[0].id,"quantity":4}])
    quoted=service.quote(db,presale.id,draft,USER)
    body=ShipmentCreate(items=[{"invoice_item_id":presale.items[0].id,"quantity":5}],
        quote_hash=quoted["quote_hash"],request_key="shipment_stale_001")
    with pytest.raises(ValueError,match="QUOTE_STALE"):
        service.create(db,presale.id,body,USER)
    assert db.query(ShipmentSettlement).count()==0


def test_partial_embedded_payment_stays_awaiting_payment(db,presale,monkeypatch):
    from app.receipt import attachments, remote
    monkeypatch.setattr(attachments,"origin",lambda: "https://proofs.invalid")
    from app.receipt.models import ReceiptAttachment
    proof=ReceiptAttachment(id="p1",filename="proof.png",storage_key="p1",content_type="image/png",
        size=100,sha256="a"*64,created_by=1)
    db.add(proof); db.commit()
    monkeypatch.setattr(remote,"receipt_types",lambda db:["TT"])
    draft=ShipmentQuote(items=[{"invoice_item_id":presale.items[0].id,"quantity":4}],freight_amount="200")
    quoted=service.quote(db,presale.id,draft,USER)
    body=ShipmentCreate(**draft.model_dump(),quote_hash=quoted["quote_hash"],request_key="shipment_partial_001",
        payment=dict(amount="1000",collection_date="2026-09-23",payment_type="TT",attachment_ids=["p1"]))
    row=service.create(db,presale.id,body,USER)
    assert row.state=="awaiting_payment"
    assert Decimal(service.funding_balance(db,row)["remaining_amount"])==3200
    assert Decimal(service.funding_balance(db,row)["effective_amount"])==0


def test_transport_requires_verified_capability_even_if_feature_enabled(monkeypatch):
    from app.invoice import settlement_policy
    with pytest.raises(ValueError,match="REMOTE_CAPABILITY_UNVERIFIED"):
        settlement_policy.require_delivery()


def test_history_remains_readable_after_order_not_ready(db,presale):
    row=make(db,presale); db.commit()
    presale.sync_status="failed"; db.commit()
    assert service.get(db,row.id,USER).id==row.id
    with pytest.raises(ValueError):
        service.get(db,row.id,USER,lock=True)
