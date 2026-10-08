"""Invoice receipt corrections use isolated SQLite and mocked OKKI reads."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.invoice.models import Invoice
from app.receipt import invoice_link, remote, service
from app.receipt.models import Receipt, ReceiptAttachment, ReceiptIntent
from app.receipt.schemas import ReceiptDraft, ReceiptUpdate


@pytest.fixture
def records(db, monkeypatch):
    order = Invoice(invoice_no="CORRECT", order_type="stock", customer_id="101",
                    customer_name="Test", sales_user_id=1, invoice_date=date(2026, 10, 8),
                    currency="USD", total_amount=Decimal("1000"), surcharge_amount=0,
                    xiaoman_order_id="123", sync_status="synced", status="synced")
    db.add(order); db.flush()
    row = Receipt(receipt_no="CORRECT-HK", invoice_id=order.id, source="auto",
                  request_key="correction-test-key", request_hash="x" * 64,
                  amount=500, bank_charge=0, currency="USD", customer_id="101",
                  collection_date=order.invoice_date, payment_type="Other", attachment_ids=["proof"],
                  xiaoman_order_id="123", sync_status="pending", created_by=1)
    db.add(row); db.flush()
    intent = ReceiptIntent(invoice_id=order.id, eligible=1, status="converted", receipt_id=row.id,
                           amount=500, collection_date=row.collection_date, payment_type="Other",
                           attachment_ids=["proof"], currency="USD", customer_id="101", created_by=1)
    db.add(intent); db.commit()
    monkeypatch.setattr(remote, "order_snapshot", lambda *a: {"rows": []})
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [])
    monkeypatch.setattr(remote, "receipt_types", lambda *a: ["Other"])
    monkeypatch.setattr(service.attachments, "bind", lambda *a: None)
    return order, row, intent


def correction(row, amount="600", charge="0"):
    return ReceiptUpdate(amount=amount, bank_charge=charge, collection_date="2026-10-08",
                         payment_type="Other", attachment_ids=["proof"], remark="corrected", version=row.version)


def test_converted_display_and_save_use_current_receipt(db, records):
    order, row, intent = records
    service.change(db, row, order, correction(row), 1); db.commit()
    shown = invoice_link.describe(db, order)
    assert shown["amount"] == "600.00"
    assert shown["remark"] == "corrected"
    invoice_link.save_draft(db, order, ReceiptDraft(**{k: shown[k] for k in
        ("amount", "collection_date", "payment_type", "remark", "attachment_ids")}), 1)
    assert intent.status == "converted" and intent.receipt_id == row.id
    with pytest.raises(ValueError, match="不能随订单修改"):
        invoice_link.save_draft(db, order, ReceiptDraft(amount="700", collection_date="2026-10-08",
                                                     payment_type="Other", attachment_ids=["proof"]), 1)


def test_stale_converted_intent_already_in_database_is_displayed_from_receipt(db, records):
    order, row, intent = records
    row.amount = Decimal("650"); row.status = "voided"; db.commit()
    shown = invoice_link.describe(db, order)
    assert shown["amount"] == "650.00"
    assert shown["receipt_status"] == "voided"
    assert intent.amount == Decimal("500")


def test_summary_preserves_multi_proof_order_for_invoice_round_trip(db, records):
    order, row, _ = records
    row.attachment_ids = ["proof-b", "proof-a"]
    for identity in ("proof-a", "proof-b"):
        db.add(ReceiptAttachment(id=identity, filename=identity + ".png", storage_key=identity,
                                content_type="image/png", size=100, sha256="a" * 64,
                                created_by=1, invoice_id=order.id, receipt_id=row.id))
    db.commit()
    shown = service.invoice_summary(db, order)["initial_receipt"]
    ids = [item["id"] for item in shown["attachments"]]
    assert ids == ["proof-b", "proof-a"]
    invoice_link.save_draft(db, order, ReceiptDraft(
        amount=shown["amount"], collection_date=shown["collection_date"],
        payment_type=shown["payment_type"], remark=shown["remark"] or "", attachment_ids=ids), 1)


def test_auto_correction_reallocates_fee_excluding_original_row(db, records, monkeypatch):
    order, row, _ = records
    order.surcharge_amount = Decimal("50"); db.commit()
    calls = []
    monkeypatch.setattr(service.fees, "allocate", lambda db, inv, amount, **kwargs:
                        calls.append((amount, kwargs["exclude_receipt"])) or Decimal("30"))
    service.change(db, row, order, correction(row, charge="99"), 1)
    assert row.bank_charge == Decimal("30")
    assert calls == [(Decimal("600"), row.id)]


def test_remote_read_cannot_overwrite_concurrent_receipt_version(db, records, monkeypatch):
    order, row, _ = records
    body = correction(row)
    def read(*args):
        row.version += 1; db.commit()
        return ["Other"]
    monkeypatch.setattr(remote, "receipt_types", read)
    with pytest.raises(HTTPException) as error:
        service.change(db, row, order, body, 1)
    assert error.value.status_code == 409
    assert row.amount == Decimal("500")


def test_unsynced_summary_shows_funds_but_blocks_actions(db, records):
    order, row, _ = records
    order.sync_status = "not_synced"; db.commit()
    data = service.invoice_summary(db, order)
    assert data["balance"]["registered_amount"] == "500.00"
    assert data["balance"]["effective_amount"] == "0"
    assert data["initial_receipt"]["id"] == row.id
    assert data["action_blocked_reason"]


def test_synced_and_uncertain_receipts_stay_uneditable(db, records):
    order, row, _ = records
    for state in ("synced", "syncing", "uncertain"):
        row.sync_status = state; db.commit()
        with pytest.raises(ValueError, match="仅未发送"):
            service.change(db, row, order, correction(row), 1)


def test_real_auto_fee_allocation_keeps_identity_and_does_not_duplicate(db, records):
    from app.receipt import sync_service
    order, row, intent = records
    order.surcharge_amount = Decimal("50"); row.bank_charge = Decimal("25"); db.commit()
    service.change(db, row, order, correction(row), 1); db.commit()
    assert row.bank_charge == Decimal("30.00")
    sync_service.generate_ready(db)
    assert db.query(Receipt).count() == 1
    assert intent.status == "converted" and intent.receipt_id == row.id


def test_auto_correction_below_previous_fee_uses_recomputed_charge(db, records):
    order, row, _ = records
    order.surcharge_amount = Decimal("50"); row.bank_charge = Decimal("25"); db.commit()
    service.change(db, row, order, correction(row, amount="20", charge="0"), 1); db.commit()
    assert row.amount == Decimal("20") and row.bank_charge == Decimal("1")
    assert invoice_link.describe(db, order)["receipt_version"] == row.version


def test_summary_requires_receipt_action_and_salesperson_scope(db, records):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.receipt.router import router
    order, _, _ = records
    app = FastAPI(); app.include_router(router, prefix="/api/receipts")
    app.dependency_overrides[get_db] = lambda: db
    for user, expected in [({"sub": "1", "permissions": ["invoice:write"]}, 403),
                           ({"sub": "2", "permissions": ["receipt:read"]}, 404),
                           ({"sub": "2", "permissions": ["receipt:read_all"]}, 403),
                           ({"sub": "1", "permissions": ["receipt:read"]}, 200),
                           ({"sub": "2", "permissions": ["receipt:read", "receipt:read_all"]}, 200)]:
        app.dependency_overrides[get_current_user] = lambda user=user: user
        with TestClient(app) as client:
            assert client.get(f"/api/receipts/invoice-summary/{order.id}").status_code == expected


def test_remote_change_is_reflected_without_rewriting_generation_intent(db, records, monkeypatch):
    from app.invoice import lifecycle_remote
    from app.receipt import remote_change_service as changes
    from app.receipt.schemas import RemoteChange
    order, row, intent = records
    row.sync_status = "synced"; row.xiaoman_receipt_id = "88"; row.bank_charge = Decimal("25"); db.commit()
    monkeypatch.setattr(lifecycle_remote, "read", lambda *a: {"order_id": "123", "currency": "USD",
        "amount": "550", "bank_charge": "0", "real_amount": "550", "collect_status": 1, "collection_date": "2026-10-08"})
    proof = changes.evidence(db, row)
    changes.accept(db, row, RemoteChange(version=row.version, evidence_hash=proof["evidence_hash"],
        reason="已核实实际收款与小满原单更正结果", confirmed=True), 1); db.commit()
    shown = invoice_link.describe(db, order)
    assert shown["amount"] == "575.00" and intent.amount == Decimal("500")
    invoice_link.save_draft(db, order, ReceiptDraft(**{k: shown[k] for k in
        ("amount", "collection_date", "payment_type", "remark", "attachment_ids")}), 1)


@pytest.mark.parametrize("case", ["changed", "missing", "uncertain"])
def test_frozen_balance_keeps_original_receipt_for_recovery(db, records, monkeypatch, case):
    order, row, _ = records
    row.xiaoman_receipt_id = "88"; row.sync_status = "uncertain" if case == "uncertain" else "synced"; db.commit()
    rows = [] if case == "missing" else [{"cash_collection_id": "88", "currency": "USD", "amount": "600", "collect_status": 1}]
    monkeypatch.setattr(remote, "order_receipts", lambda *a: rows)
    data = service.invoice_summary(db, order)
    assert data["balance"] is None and data["balance_error"]
    assert data["initial_receipt"]["id"] == row.id
    assert data["initial_receipt"]["xiaoman_receipt_id"] == "88"
    assert data["action_blocked_reason"]
