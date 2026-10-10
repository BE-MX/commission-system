"""Remark-only requests use isolated SQLite and never call remote services."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.core.database import get_db
from app.invoice.linked_sync_service import edit_version
from app.invoice.models import Invoice
from app.receipt.models import Receipt, ReceiptIntent, ReceiptLog


@pytest.fixture
def documents(db, monkeypatch):
    from app.invoice import okki_client
    from app.receipt import remote
    def forbidden(*args, **kwargs):
        raise AssertionError("Remark editing must not access OKKI")
    monkeypatch.setattr(okki_client, "ensure_access_token", forbidden)
    monkeypatch.setattr(remote, "order_receipts", forbidden)
    monkeypatch.setattr(remote, "push", forbidden)
    perms = [ArkPermission(code=code, module=code.split(":")[0], action="write", label=code)
             for code in ("invoice:write", "receipt:write")]
    role = ArkRole(name="remark_editor", label="Editor", permissions=perms)
    db.add_all([ArkUser(id=801, username="remark_editor", real_name="Editor", password_hash="x", roles=[role]),
                ArkUser(id=802, username="other_editor", real_name="Other", password_hash="x", roles=[role])])
    invoice = Invoice(invoice_no="REMARK-TEST", order_type="stock", customer_id="101",
        customer_name="Test", sales_user_id=801, created_by=801, invoice_date=date(2026, 10, 10),
        total_amount=Decimal("500"), currency="USD", remark="old order",
        xiaoman_order_id="2001", sync_status="synced", status="synced")
    db.add(invoice); db.flush()
    receipt = Receipt(receipt_no="REMARK-R", invoice_id=invoice.id, source="auto",
        amount=Decimal("500"), bank_charge=Decimal("0"), currency="USD", collection_date=invoice.invoice_date,
        payment_type="T/T", remark="old receipt", created_by=801, attachment_ids=[],
        status="active", sync_status="synced", xiaoman_order_id="2001", xiaoman_receipt_id="701",
        collect_status=1, purpose="ordinary", customer_id="101",
        request_key="remark-request-key", request_hash="remark-hash")
    db.add(receipt); db.flush()
    db.add(ReceiptIntent(invoice_id=invoice.id, receipt_id=receipt.id, status="converted",
        remark=receipt.remark, attachment_ids=[], created_by=801))
    db.commit()
    return invoice.id, receipt.id


def request(db, documents, kind, remark, *, actor=801, version=None, extra=None):
    from app.invoice.remark_router import router as invoice_router
    from app.receipt.router import router as receipt_router
    invoice_id, receipt_id = documents
    invoice = db.get(Invoice, invoice_id)
    receipt = db.get(Receipt, receipt_id)
    payload = {"remark": remark}
    payload.update({"expected_version": version or edit_version(invoice)} if kind == "invoice"
                   else {"version": version if version is not None else receipt.version})
    payload.update(extra or {})
    db.rollback()
    app = FastAPI()
    app.include_router(invoice_router, prefix="/invoice")
    app.include_router(receipt_router, prefix="/receipts")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": str(actor), "roles": ["remark_editor"], "permissions": ["invoice:write", "receipt:write"]}
    app.dependency_overrides[get_db] = lambda: db
    path = f"/invoice/invoices/{invoice_id}/remark" if kind == "invoice" else f"/receipts/{receipt_id}/remark"
    with TestClient(app) as client:
        response = client.patch(path, json=payload)
    db.rollback()
    return response


@pytest.mark.parametrize("kind", ["invoice", "receipt"])
@pytest.mark.parametrize("remark", ["updated\n备注", ""])
def test_edit_and_clear_synced_remarks_only(db, documents, kind, remark):
    result = request(db, documents, kind, remark)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["remark"] == remark
    invoice, receipt = db.get(Invoice, documents[0]), db.get(Receipt, documents[1])
    assert invoice.total_amount == 500 and invoice.sync_status == "synced" and invoice.status == "synced"
    assert invoice.xiaoman_order_id == "2001"
    assert receipt.amount == 500 and receipt.collect_status == 1 and receipt.sync_status == "synced"
    assert receipt.xiaoman_receipt_id == "701" and receipt.attachment_ids == []
    if kind == "receipt":
        assert receipt.version == 2
        assert db.query(ReceiptIntent).one().remark == remark
        log = db.query(ReceiptLog).one()
        assert log.action == "remark" and log.created_by == 801
    else:
        assert invoice.updated_by == 801
        assert result.json()["data"]["edit_version"] == edit_version(invoice)


@pytest.mark.parametrize("kind", ["invoice", "receipt"])
def test_stale_edit_cannot_overwrite_new_remark(db, documents, kind):
    old = edit_version(db.get(Invoice, documents[0])) if kind == "invoice" else 1
    assert request(db, documents, kind, "new").status_code == 200
    result = request(db, documents, kind, "stale", version=old)
    assert result.status_code == 409
    model, identity = (Invoice, documents[0]) if kind == "invoice" else (Receipt, documents[1])
    assert db.get(model, identity).remark == "new"


@pytest.mark.parametrize("kind", ["invoice", "receipt"])
def test_foreign_scope_is_hidden(db, documents, kind):
    assert request(db, documents, kind, "foreign", actor=802).status_code == 404


@pytest.mark.parametrize("kind", ["invoice", "receipt"])
def test_revoked_live_permission_beats_stale_request_claim(db, documents, kind):
    role = db.get(ArkUser, 801).roles[0]
    role.permissions = [p for p in role.permissions if p.code != f"{kind}:write"]
    db.commit()
    assert request(db, documents, kind, "revoked").status_code == 403


@pytest.mark.parametrize("kind,limit", [("invoice", 5000), ("receipt", 500)])
def test_payload_rejects_other_fields_and_oversize(db, documents, kind, limit):
    assert request(db, documents, kind, "safe", extra={"amount": "1"}).status_code == 422
    assert request(db, documents, kind, "a" * (limit + 1)).status_code == 422


@pytest.mark.parametrize("kind", ["invoice", "receipt"])
def test_cancelled_documents_cannot_edit(db, documents, kind):
    db.get(Invoice, documents[0]).status = "cancelled"; db.commit()
    assert request(db, documents, kind, "cancelled").status_code == 409


def test_sending_receipt_is_fenced(db, documents):
    db.get(Receipt, documents[1]).sync_status = "syncing"; db.commit()
    assert request(db, documents, "receipt", "sending").status_code == 409


def test_duplicate_save_is_noop(db, documents):
    assert request(db, documents, "receipt", "new").status_code == 200
    assert request(db, documents, "receipt", "new").status_code == 200
    assert db.get(Receipt, documents[1]).version == 2
    assert db.query(ReceiptLog).count() == 1


@pytest.mark.parametrize("kind", ["invoice", "receipt"])
def test_order_push_in_progress_or_unknown_is_fenced(db, documents, kind):
    invoice = db.get(Invoice, documents[0])
    invoice.sync_status = "sync_uncertain"; invoice.status = "sync_uncertain"; db.commit()
    assert request(db, documents, kind, "during push").status_code == 409
    assert db.get(Receipt, documents[1]).version == 1
