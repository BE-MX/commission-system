"""Financial regression tests. SQLite only; all OKKI traffic is replaced."""
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from app.core.time import beijing_now
from app.invoice import okki_client
from app.invoice.models import Invoice
from app.receipt import attachments, balance, invoice_link, remote, service, sync_service
from app.receipt.models import Receipt, ReceiptIntent
from app.receipt.schemas import ReceiptCreate, ReceiptDraft, ReceiptFields, Resolution

USER = {"sub": "1", "roles": [], "permissions": ["receipt:read", "receipt:write"]}


@pytest.fixture
def order(db):
    row = Invoice(invoice_no="TEST-RECEIPT", order_type="stock", customer_id="101", customer_name="Test",
                  sales_user_id=1, created_by=1, invoice_date=date(2026, 9, 17), currency="USD",
                  total_amount=Decimal("4860"), xiaoman_order_id="2001", sync_status="synced", status="synced")
    db.add(row); db.commit()
    return row


@pytest.fixture(autouse=True)
def no_real_remote(monkeypatch, tmp_path):
    monkeypatch.setattr(attachments, "STORAGE_ROOT", tmp_path / "proofs")
    monkeypatch.setattr(remote, "receipt_types", lambda db: ["T/T", "PayPal"])
    monkeypatch.setattr(remote, "order_snapshot", lambda db, invoice: {"rows": [], "exchange_rate": 725})
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [])
    monkeypatch.setattr(remote, "receipt_info", lambda db, identity: {"cash_collection_id": identity,
        "cash_collection_no": "TEST-HK", "order_id": "2001", "currency": "USD", "amount": "500",
        "collection_date": "2026-09-17", "bank_charge": "0", "real_amount": "500", "collect_status": 0})
    def forbidden(*a, **k):
        raise AssertionError("Unexpected real remote call")
    monkeypatch.setattr(okki_client, "ensure_access_token", forbidden)
    monkeypatch.setattr(remote, "push", lambda *a: {"cash_collection_id": 701, "cash_collection_no": "REMOTE-701"})


def proof(db):
    content = io.BytesIO(); Image.new("RGB", (8, 8), "white").save(content, format="PNG")
    row = attachments.upload(db, content.getvalue(), "test.png", 1)
    db.commit()
    return row.id


def fields(db, amount="500"):
    return ReceiptFields(amount=amount, collection_date=date(2026, 9, 17), payment_type="T/T", attachment_ids=[proof(db)])


def register(db, order, amount="500", key="test_request_key_001"):
    data = fields(db, amount).model_dump()
    snapshot = service.order_balance(db, order)
    body = ReceiptCreate(**data, invoice_id=order.id, request_key=key, balance_version=snapshot["version"])
    row = service.create(db, body, USER); db.commit()
    return row, body


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "1.001", "1000000000000"])
def test_invalid_money_rejected(value):
    with pytest.raises(ValidationError):
        ReceiptFields(amount=value, collection_date="2026-09-17", payment_type="T/T", attachment_ids=["x"])


def test_upload_rejects_fake_or_oversize(db):
    with pytest.raises(ValueError): attachments.upload(db, b"fake-png", "fake.png", 1)
    with pytest.raises(ValueError): attachments.upload(db, b"x" * (attachments.MAX_BYTES + 1), "x.jpg", 1)


def test_stock_missing_proof_cannot_sync(db, order):
    with pytest.raises(ValueError, match="截图"):
        invoice_link.preflight(db, order, 1)


def test_foreign_attachment_cannot_bind(db, order):
    identity = proof(db)
    with pytest.raises(ValueError, match="他人"):
        attachments.bind(db, [identity], 2, order.id)


def test_manual_amount_and_replay_are_exactly_once(db, order):
    row, body = register(db, order)
    assert service.order_balance(db, order)["remaining_amount"] == "4360.00"
    same = service.create(db, body, USER)
    assert same.id == row.id and db.query(Receipt).count() == 1
    with pytest.raises(HTTPException):
        service.create(db, body.model_copy(update={"amount": Decimal("501")}), USER)


def test_stale_balance_rejects_second_registration(db, order):
    version = service.order_balance(db, order)["version"]
    register(db, order, "4000")
    payload = ReceiptCreate(**fields(db, "1000").model_dump(), invoice_id=order.id,
        request_key="test_request_second", balance_version=version)
    with pytest.raises(HTTPException) as exc:
        service.create(db, payload, USER)
    assert exc.value.status_code == 409
    assert db.query(Receipt).count() == 1


def test_overpayment_rejected_with_fresh_balance(db, order):
    with pytest.raises(ValueError, match="余额"):
        register(db, order, "4860.01")


def test_remote_original_currency_and_id_dedupe(db, order):
    row, _ = register(db, order, "600")
    row.xiaoman_receipt_id = "701"; db.commit()
    snapshot = {"rows": [{"cash_collection_id": "701", "amount": "600", "currency": "USD", "collect_status": 0},
                         {"cash_collection_id": "702", "amount": "1500", "currency": "USD", "collect_status": 1}]}
    result = balance.calculate(db, order, snapshot)
    assert Decimal(result["remaining_amount"]) == Decimal("2760")
    assert Decimal(result["effective_amount"]) == Decimal("1500")
    snapshot["rows"][0]["currency"] = "CNY"
    with pytest.raises(ValueError, match="币种"): balance.calculate(db, order, snapshot)


def test_ready_intent_reserves_then_transfers_once(db, order):
    draft = ReceiptDraft(**fields(db, "600").model_dump(exclude={"bank_charge"}))
    invoice_link.save_draft(db, order, draft, 1, new=True); db.commit()
    invoice_link.arm(db, order, 1); invoice_link.mark_success(db, order); db.commit()
    assert Decimal(service.order_balance(db, order)["remaining_amount"]) == Decimal("4260")
    sync_service.generate_ready(db); sync_service.generate_ready(db)
    assert db.query(Receipt).count() == 1
    assert Decimal(service.order_balance(db, order)["remaining_amount"]) == Decimal("4260")
    assert invoice_link.get_intent(db, order.id).status == "converted"


def test_historical_invoice_does_not_backfill(db, order):
    invoice_link.save_draft(db, order, ReceiptDraft(attachment_ids=[proof(db)]), 1)
    db.commit(); invoice_link.preflight(db, order, 1); invoice_link.mark_success(db, order); db.commit()
    sync_service.generate_ready(db)
    assert db.query(Receipt).count() == 0


def test_no_generation_before_success_event(db, order):
    invoice_link.save_draft(db, order, ReceiptDraft(**fields(db).model_dump(exclude={"bank_charge"})), 1, new=True)
    db.commit(); invoice_link.arm(db, order, 1); db.commit()
    sync_service.generate_ready(db)
    assert db.query(Receipt).count() == 0


def test_timeout_stays_reserved_and_no_retry(db, order, monkeypatch):
    row, _ = register(db, order)
    def timeout(*a): raise okki_client.OkkiOutcomeUncertainError("test timeout")
    monkeypatch.setattr(remote, "push", timeout)
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "uncertain"
    with pytest.raises(ValueError): service.retry(db, row, 1)
    with pytest.raises(ValueError): service.void(db, row, "test", 1)
    assert Decimal(service.order_balance(db, order)["remaining_amount"]) == Decimal("4360")


def test_failed_can_retry_without_new_local_receipt(db, order, monkeypatch):
    row, _ = register(db, order)
    def rejected(*a): raise okki_client.OkkiApiError("denied")
    monkeypatch.setattr(remote, "push", rejected)
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "failed"
    service.retry(db, row, 1); db.commit()
    monkeypatch.setattr(remote, "push", lambda *a: {"cash_collection_id": "99", "cash_collection_no": "HK99"})
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "synced" and row.xiaoman_receipt_id == "99"
    assert db.query(Receipt).count() == 1


def test_expired_sender_never_resends(db, order, monkeypatch):
    row, _ = register(db, order)
    row.sync_status = "syncing"; row.lease_until = beijing_now() - timedelta(minutes=1); db.commit()
    sync_service.recover_expired(db); db.refresh(row)
    assert row.sync_status == "uncertain"
    monkeypatch.setattr(remote, "push", lambda *a: pytest.fail("must not send"))
    sync_service.deliver(db, row.id)


def test_cross_owner_hidden_and_production_not_auto(db, order):
    row, _ = register(db, order)
    with pytest.raises(HTTPException): service.get(db, row.id, {**USER, "sub": "2"})
    assert service.list_receipts(db, {**USER, "sub": "2"})["total"] == 0
    order.order_type = "production"
    invoice_link.preflight(db, order, 1)


def test_void_releases_balance_preserves_evidence(db, order):
    row, _ = register(db, order)
    service.void(db, row, "not sent", 1); db.commit()
    assert Decimal(service.order_balance(db, order)["remaining_amount"]) == Decimal("4860")
    assert row.attachment_ids and db.query(Receipt).count() == 1


def test_same_amount_candidate_is_not_auto_bound(db, order, monkeypatch):
    row, _ = register(db, order); row.sync_status = "uncertain"; db.commit()
    data = {"cash_collection_id": "99", "order_id": "2001", "currency": "USD", "amount": "500",
            "collection_date": "2026-09-17", "cash_collection_no": "manual-other", "collect_status": 1}
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [data])
    assert len(sync_service.reconcile(db, row, 1)) == 1 and row.xiaoman_receipt_id is None
    with pytest.raises(ValueError):
        sync_service.resolve(db, row, Resolution(resolution="confirm_not_created", reason="checked"), 1)


def test_order_identity_frozen_after_receipt(db, order):
    register(db, order)
    with pytest.raises(ValueError, match="客户"):
        invoice_link.guard_edit(db, order, SimpleNamespace(customer_id="other", currency="USD", order_type="stock"))


def test_beijing_receipt_number_across_utc_midnight(db, order, monkeypatch):
    # The business clock is injected, not the host timezone/date.
    monkeypatch.setattr(service, "beijing_now", lambda: datetime(2026, 9, 18, 0, 1))
    row, _ = register(db, order)
    assert row.receipt_no.startswith("HK20260918-")


def test_stock_concurrent_claim_and_expired_initial_push_require_review(db, order):
    order.xiaoman_order_id = None; order.sync_status = "not_synced"
    invoice_link.save_draft(db, order, ReceiptDraft(**fields(db).model_dump(exclude={"bank_charge"})), 1, new=True)
    db.commit()
    token = invoice_link.arm(db, order, 1); db.commit()
    with pytest.raises(ValueError, match="重复"):
        invoice_link.arm(db, order, 1)
    intent = invoice_link.get_intent(db, order.id)
    intent.lease_until = beijing_now() - timedelta(seconds=1); db.commit()
    invoice_link.recover_expired(db); db.refresh(order)
    assert order.sync_status == "sync_uncertain" and intent.status == "armed"
    with pytest.raises(ValueError, match="失效"):
        invoice_link.ensure_attempt(db, order, token)


def test_stock_partial_failure_can_repair_lines_but_keeps_amount_floor(db, order):
    invoice_link.save_draft(db, order, ReceiptDraft(**fields(db, "600").model_dump(exclude={"bank_charge"})), 1, new=True)
    db.commit(); token = invoice_link.arm(db, order, 1)
    order.sync_status = "sync_failed"
    invoice_link.finish_attempt(db, order, token); db.commit()
    body = SimpleNamespace(customer_id=order.customer_id, currency=order.currency, order_type="stock")
    assert invoice_link.guard_edit(db, order, body) == Decimal("600")


def test_remote_only_history_freezes_identity_and_amount(db, order, monkeypatch):
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [
        {"cash_collection_id": "900", "amount": "700", "currency": "USD", "collect_status": 1}])
    body = SimpleNamespace(customer_id=order.customer_id, currency=order.currency, order_type="stock")
    assert invoice_link.guard_edit(db, order, body) == Decimal("700")
    body.currency = "EUR"
    with pytest.raises(ValueError, match="币种"):
        invoice_link.guard_edit(db, order, body)


def test_manual_cannot_reuse_automatic_intent_proof(db, order):
    draft = ReceiptDraft(**fields(db).model_dump(exclude={"bank_charge"}))
    invoice_link.save_draft(db, order, draft, 1, new=True); db.commit()
    body = ReceiptCreate(**draft.model_dump(), invoice_id=order.id, request_key="different-payment-key",
                         balance_version=service.order_balance(db, order)["version"])
    with pytest.raises(ValueError, match="自动回款"):
        service.create(db, body, USER)
    db.rollback()
    assert db.query(Receipt).count() == 0


def test_revoked_or_inactive_delegate_cannot_list_receipts(db, order):
    from app.auth.models import ArkUser
    from app.invoice.models import InvoiceDelegateGrant
    register(db, order)
    order.created_by = 2
    if not db.get(ArkUser, 1):
        db.add(ArkUser(id=1, username="receipt-owner", real_name="Test owner", password_hash="x", is_active=True))
    db.add(InvoiceDelegateGrant(sales_user_id=1, delegate_user_id=2, created_by=1)); db.commit()
    assert service.list_receipts(db, {**USER, "sub": "2"})["total"] == 1
    db.get(ArkUser, 1).is_active = False; db.commit()
    assert service.list_receipts(db, {**USER, "sub": "2"})["total"] == 0


def test_old_success_cannot_overwrite_new_attempt(db, order, monkeypatch):
    row, _ = register(db, order)
    def old_sender(db, row, snapshot, fence):
        fence()
        row.sync_status, row.attempt_token = "uncertain", "replaced-token"
        db.commit()
        return {"cash_collection_id": "99", "cash_collection_no": "HK99"}
    monkeypatch.setattr(remote, "push", old_sender)
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "uncertain" and row.xiaoman_receipt_id is None


def api_client(db, user):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.receipt.router import router
    from app.invoice.router import router as invoice_router
    app = FastAPI()
    app.include_router(router, prefix="/api/receipts")
    app.include_router(invoice_router, prefix="/api/invoice")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_routes_scope_permissions_private_image_and_creation(db, order):
    screenshot = proof(db)
    data = ReceiptCreate(amount="500", collection_date="2026-09-17", payment_type="T/T", attachment_ids=[screenshot],
        invoice_id=order.id, request_key="api-receipt-create-test", balance_version=service.order_balance(db, order)["version"])
    with api_client(db, USER) as client:
        result = client.post("/api/receipts", json=data.model_dump(mode="json"))
        assert result.status_code == 200, result.text
        identity = result.json()["data"]["id"]
        assert client.post("/api/receipts", json=data.model_dump(mode="json")).json()["data"]["id"] == identity
        image = client.get(f"/api/receipts/attachments/{screenshot}")
        assert image.status_code == 200 and image.headers["cache-control"] == "private, no-store"
    with api_client(db, {**USER, "sub": "2"}) as client:
        assert client.get(f"/api/receipts/{identity}").status_code == 404
        assert client.get(f"/api/receipts/attachments/{screenshot}").status_code == 404
        assert client.get("/api/receipts").json()["data"]["total"] == 0
    with api_client(db, {**USER, "permissions": ["receipt:read_all"]}) as client:
        assert client.get("/api/receipts").status_code == 403
    with api_client(db, {**USER, "permissions": ["receipt:read"]}) as client:
        assert client.post("/api/receipts", json=data.model_dump(mode="json")).status_code == 403


def test_stock_router_gates_before_inventory_or_remote_side_effect(db, order, monkeypatch):
    from app.invoice import router
    monkeypatch.setattr(router.semifinished_invoice_service, "prepare_invoice_sync", lambda *a: pytest.fail("inventory touched"))
    monkeypatch.setattr(router.xiaoman_service, "sync_invoice", lambda *a, **k: pytest.fail("remote touched"))
    with api_client(db, {**USER, "permissions": ["invoice:sync"]}) as client:
        response = client.post(f"/api/invoice/invoices/{order.id}/sync")
        assert response.status_code == 409 and "截图" in response.json()["detail"]


@pytest.mark.parametrize("finalize_failure", [False, True])
def test_stock_router_only_complete_success_marks_ready(db, order, monkeypatch, finalize_failure):
    from app.invoice import router
    order.xiaoman_order_id = None; order.sync_status = "not_synced"
    invoice_link.save_draft(db, order, ReceiptDraft(**fields(db).model_dump(exclude={"bank_charge"})), 1, new=True)
    db.commit()
    def push(db, invoice, **kwargs):
        invoice_link.ensure_attempt(db, invoice, kwargs["receipt_sync_token"])
        invoice.xiaoman_order_id, invoice.sync_status = "2001", "synced"
        db.commit()
        return {"ok": True}
    monkeypatch.setattr(router.xiaoman_service, "sync_invoice", push)
    if finalize_failure:
        def fail(*args): raise RuntimeError("test finalize failed")
        monkeypatch.setattr(router.semifinished_invoice_service, "finalize_invoice_sync", fail)
    with api_client(db, {**USER, "permissions": ["invoice:sync"]}) as client:
        response = client.post(f"/api/invoice/invoices/{order.id}/sync")
    assert response.status_code == 200, response.text
    intent = invoice_link.get_intent(db, order.id)
    assert intent.status == ("armed" if finalize_failure else "ready")
    assert intent.attempt_token is None
    sync_service.generate_ready(db)
    assert db.query(Receipt).count() == (0 if finalize_failure else 1)


def test_readback_unknown_and_mismatch_never_resend_or_release(db, order, monkeypatch):
    row, _ = register(db, order)
    def unavailable(*a): raise okki_client.OkkiApiError("read unavailable")
    monkeypatch.setattr(remote, "receipt_info", unavailable)
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "synced" and row.xiaoman_receipt_id == "701" and row.collect_status is None
    assert "核验" in row.last_error
    with pytest.raises(ValueError): service.retry(db, row, 1)
    data = {"cash_collection_id": "701", "cash_collection_no": "TEST-HK", "order_id": "2001",
            "currency": "USD", "amount": "500", "collection_date": "2026-09-16", "collect_status": 0}
    monkeypatch.setattr(remote, "receipt_info", lambda *a: data)
    sync_service.refresh_accepted(db, row.id); db.refresh(row)
    assert row.sync_status == "uncertain" and row.xiaoman_receipt_id == "701"
    with pytest.raises(ValueError, match="冻结"):
        balance.calculate(db, order, {"rows": [data]})
    with pytest.raises(ValueError, match="已取得"):
        sync_service.resolve(db, row, Resolution(resolution="confirm_not_created", reason="test"), 1)


def test_invoice_only_reader_cannot_fetch_manual_receipt_proof(db, order):
    row, _ = register(db, order)
    with api_client(db, {**USER, "permissions": ["invoice:read", "invoice:read_all"]}) as client:
        assert client.get(f"/api/receipts/attachments/{row.attachment_ids[0]}").status_code == 404


def test_identical_concurrent_request_replays_after_write_lock(db, order, monkeypatch):
    body = ReceiptCreate(**fields(db).model_dump(), invoice_id=order.id, request_key="concurrent-replay-test",
        balance_version=service.order_balance(db, order)["version"])
    def another_request_commits(db, invoice):
        import hashlib
        fingerprint = hashlib.sha256(body.model_dump_json(exclude={"balance_version"}).encode()).hexdigest()
        service.new_row(db, invoice, body, 1, body.request_key, fingerprint)
        db.commit()
        return {"rows": [], "exchange_rate": 725}
    monkeypatch.setattr(remote, "order_snapshot", another_request_commits)
    row = service.create(db, body, USER); db.commit()
    assert row.request_key == body.request_key and db.query(Receipt).count() == 1


def test_old_invoice_attempt_cannot_finish_or_release_new_claim(db, order):
    invoice_link.save_draft(db, order, ReceiptDraft(**fields(db).model_dump()), 1, new=True)
    token = invoice_link.arm(db, order, 1)
    intent = invoice_link.get_intent(db, order.id)
    assert intent.status == "armed"
    result = invoice_link.mark_success(db, order, "old-attempt")
    assert result["receipt_generation_status"] == "waiting_recovery" and intent.status == "armed"
    order.xiaoman_order_id = None
    invoice_link.release_rejected(db, order, "old-attempt")
    assert intent.status == "armed" and intent.attempt_token == token


@pytest.mark.parametrize("amount,charge", [("367.87", "17.52"), ("100.00", "4.76")])
def test_automatic_receipt_allocates_fee_proportionally(db, order, amount, charge):
    order.total_amount = Decimal("367.87")
    order.surcharge_amount = Decimal("17.52")
    draft = ReceiptDraft(**fields(db, amount).model_dump(exclude={"bank_charge"}))
    invoice_link.save_draft(db, order, draft, 1, new=True)
    invoice_link.arm(db, order, 1); invoice_link.mark_success(db, order); db.commit()
    sync_service.generate_ready(db)
    row = db.query(Receipt).one()
    assert row.amount == Decimal(amount)
    assert row.bank_charge == Decimal(charge)


def test_proportional_allocation_final_rounding():
    from app.receipt.fees import proportional
    total, fee = Decimal("3.00"), Decimal("0.01")
    registered, charged, charges = Decimal("0"), Decimal("0"), []
    for _ in range(3):
        charge = proportional(total, fee, Decimal("1"), registered, charged)
        charges.append(charge); registered += Decimal("1"); charged += charge
    assert charges == [Decimal("0"), Decimal("0"), Decimal("0.01")]
    assert charged == fee


def test_fee_allocation_deduplicates_remote_and_local(db, order, monkeypatch):
    from app.receipt import fees
    order.total_amount = Decimal("367.87"); order.surcharge_amount = Decimal("17.52"); db.commit()
    first, _ = register(db, order, "100")
    first.bank_charge = Decimal("4.76")
    first.xiaoman_receipt_id = "701"; first.sync_status = "synced"; db.commit()
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [dict(cash_collection_id="701", amount="100")])
    monkeypatch.setattr(remote, "receipt_info", lambda *a: dict(order_id="2001", currency="USD", amount="100",
                                                              bank_charge="4.76", real_amount="95.24"))
    assert fees.allocate(db, order, Decimal("267.87")) == Decimal("12.76")
    first.sync_status = "uncertain"; db.commit()
    with pytest.raises(ValueError, match="待核对"):
        fees.allocate(db, order, Decimal("267.87"))


def test_explicit_manual_fee_is_preserved(db, order):
    order.surcharge_amount = Decimal("17.52"); db.commit()
    data = ReceiptCreate(**fields(db, "100").model_copy(update={"bank_charge": Decimal("1.23")}).model_dump(),
        invoice_id=order.id, request_key="explicit_fee_request_001", balance_version=service.order_balance(db, order)["version"])
    row = service.create(db, data, USER)
    assert row.bank_charge == Decimal("1.23")


def test_fee_allocation_rejects_inconsistent_net(db, order, monkeypatch):
    from app.receipt import fees
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [dict(cash_collection_id="701", amount="500")])
    monkeypatch.setattr(remote, "receipt_info", lambda *a: dict(order_id="2001", currency="USD", amount="500",
                                                              bank_charge="2", real_amount="500"))
    with pytest.raises(ValueError, match="实到账"):
        fees.allocate(db, order, Decimal("100"))


def test_old_failed_auto_retry_allocates_without_duplicate(db, order):
    order.total_amount = Decimal("367.87"); order.surcharge_amount = Decimal("17.52"); db.commit()
    row, _ = register(db, order, "367.87")
    row.source = "auto"; row.bank_charge = Decimal("0"); row.sync_status = "failed"; db.commit()
    service.retry(db, row, 1); db.commit()
    assert row.bank_charge == Decimal("17.52") and row.sync_status == "pending"
    assert db.query(Receipt).count() == 1


def test_old_pending_auto_never_sends_zero_fee(db, order, monkeypatch):
    order.surcharge_amount = Decimal("17.52"); db.commit()
    row, _ = register(db, order)
    row.source = "auto"; row.bank_charge = Decimal("0"); db.commit()
    monkeypatch.setattr(remote, "push", lambda *a: pytest.fail("must not POST old zero fee"))
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "failed" and row.xiaoman_receipt_id is None


@pytest.mark.parametrize("fee", ["NaN", "-1", "bad"])
def test_invalid_remote_fee_freezes_accepted_receipt(db, order, monkeypatch, fee):
    row, _ = register(db, order)
    monkeypatch.setattr(remote, "receipt_info", lambda *a: dict(order_id="2001", currency="USD", amount="500",
        collection_date="2026-09-17", cash_collection_id="701", bank_charge=fee, real_amount="500", collect_status=1))
    sync_service.deliver(db, row.id); db.refresh(row)
    assert row.sync_status == "uncertain" and row.xiaoman_receipt_id == "701"
    with pytest.raises(ValueError): service.retry(db, row, 1)


@pytest.mark.parametrize("status", ["pending", "failed", "syncing", "uncertain"])
def test_pending_receipt_freezes_fee_basis(db, order, status):
    row, _ = register(db, order)
    row.sync_status = status; db.commit()
    previous = (order.total_amount, order.surcharge_amount)
    invoice_link.guard_fee_basis(db, order, previous)
    order.total_amount += Decimal("10"); order.surcharge_amount += Decimal("10")
    with pytest.raises(ValueError, match="总额或手续费"):
        invoice_link.guard_fee_basis(db, order, previous)


@pytest.mark.parametrize("value", [None, "", 0, "0.00"])
def test_empty_manual_fee_is_zero(db, order, value):
    order.surcharge_amount = Decimal("17.52"); db.commit()
    data = fields(db, "100").model_dump(); data["bank_charge"] = value
    body = ReceiptCreate(**data, invoice_id=order.id, request_key="empty_fee_request_001",
                         balance_version=service.order_balance(db, order)["version"])
    row = service.create(db, body, USER)
    assert row.bank_charge == Decimal("0")
