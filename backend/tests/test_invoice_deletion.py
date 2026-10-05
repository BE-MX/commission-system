"""Cascade deletion uses an isolated ledger and mocked remote boundaries only."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.core.time import beijing_now
from app.invoice import deletion_router, deletion_service as deletion, lifecycle_remote, linked_outbound_service, okki_client
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.invoice.xiaoman_service import FIELD_ORDER_TYPE
from app.receipt import remote
from app.receipt.models import Receipt, ReceiptLog
from app.semifinished.models import InvoiceAllocation, SemifinishedMaterial
from app.shipping_inspection import outbound_delete_client, outbound_delete_service, outbound_service
from app.shipping_inspection.models import ShippingOperationEvent


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real network or unmocked remote boundary is forbidden")
    monkeypatch.setattr(httpx, "request", forbidden)
    monkeypatch.setattr(lifecycle_remote, "read", forbidden)
    monkeypatch.setattr(lifecycle_remote, "request", forbidden)
    monkeypatch.setattr(remote, "order_receipts", forbidden)
    monkeypatch.setattr(remote, "order_active", forbidden)
    monkeypatch.setattr(linked_outbound_service, "find_related", forbidden)
    monkeypatch.setattr(outbound_delete_client, "read", forbidden)
    monkeypatch.setattr(outbound_delete_client, "remove", forbidden)
    monkeypatch.setattr(okki_client, "ensure_access_token", lambda *a: "test-token")
    monkeypatch.setattr(outbound_delete_service, "ensure_access_token", lambda *a: "test-token")


@pytest.fixture
def user():
    return {"sub": "1", "roles": [], "permissions": ["invoice:admin", "receipt:admin",
        "shipping_inspection:delete", "shipping_inspection:read_all"]}


@pytest.fixture
def invoice(db):
    row = Invoice(invoice_no="Rina-KC-1001", order_type="stock", customer_id="101",
        customer_name="Alissa Cheryl Vogel", sales_user_id=1, created_by=1,
        invoice_date=date(2026, 10, 1), currency="USD", total_amount=168,
        xiaoman_order_id="123", sync_status="synced", status="synced")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def receipt(db, invoice):
    row = Receipt(receipt_no="HK-RINA", invoice_id=invoice.id, source="manual",
        request_key="rina-receipt", request_hash="a" * 64, amount=168, currency="USD",
        collection_date=invoice.invoice_date, payment_type="T/T", bank_charge=8,
        customer_id="101", xiaoman_order_id="123", xiaoman_receipt_id="88",
        sync_status="synced", collect_status=1, created_by=1, attachment_ids=["proof-retained"])
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def live(db, invoice, monkeypatch):
    state = {
        "order": {"order_id": "123", "company_id": "101", "currency": "USD", "amount": "168"},
        "receipt": {"cash_collection_id": "88", "cash_collection_no": "HK-RINA", "order_id": "123",
            "currency": "USD", "amount": "160", "real_amount": "160", "bank_charge": "0", "collect_status": 1},
        "outbound": {"outbound_invoice_id": "7", "serial_id": "Rina-KC-1001", "status": 1,
            "company_info": {"id": "101"}, "record_list": [{"order_id": "123", "order_record_id": "line-1", "outbound_count": 1}]},
        "posts": [], "uncertain": set(), "scope_calls": [],
    }
    record = {"outbound_invoice_id": "7", "outbound_record_id": 17,
        "outbound_no": "Rina-KC-1001", "company_id": "101"}
    def read(db, kind, identity):
        assert identity in ("123", "88")
        return deepcopy(state[kind])
    def request(token, kind, identity, remove=False):
        assert token == "test-token"
        if remove:
            state["posts"].append(kind)
            db.refresh(invoice)
            assert invoice.status == "cancel_pending"
            assert invoice.cancellation["deletion"]["steps"]["receipt:88" if kind == "receipt" else "order"]["status"] == "sending"
            if kind in state["uncertain"]:
                raise okki_client.OkkiOutcomeUncertainError("timeout")
            state[kind] = None
            return True
        return read(db, kind, identity)
    def record_by_id(db, identity, okki_user_id=None):
        assert identity == "7"
        state["scope_calls"].append(okki_user_id)
        return deepcopy(record) if state.get("visible", True) else None
    def remove_outbound(token, identity):
        assert identity == "7" and token == "test-token"
        state["posts"].append("outbound")
        db.refresh(invoice)
        assert invoice.cancellation["deletion"]["steps"]["outbound:7"]["status"] == "sending"
        if "outbound" in state["uncertain"]:
            raise outbound_delete_client.DeleteRemoteError("timeout", uncertain=True)
        state["outbound"] = None
        return True
    monkeypatch.setattr(lifecycle_remote, "read", read)
    monkeypatch.setattr(lifecycle_remote, "request", request)
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [{"cash_collection_id": "88"}] if state["receipt"] else [])
    monkeypatch.setattr(remote, "order_active", lambda *a: state["order"] is not None and state.get("order_active", True))
    monkeypatch.setattr(linked_outbound_service, "find_related", lambda *a: [deepcopy(state["outbound"])] if state["outbound"] else [])
    monkeypatch.setattr(outbound_service, "get_record_by_outbound_invoice_id", record_by_id)
    monkeypatch.setattr(outbound_delete_client, "read", lambda *a: deepcopy(state["outbound"]))
    monkeypatch.setattr(outbound_delete_client, "remove", remove_outbound)
    return state


def execute(db, invoice, user):
    return deletion.run(db, invoice.id, user, deletion.preview(db, invoice, user)["version"])


def test_rina_deletes_in_order_and_retains_financial_facts(db, invoice, receipt, live, user):
    result = execute(db, invoice, user)
    assert result["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]
    db.refresh(invoice)
    db.refresh(receipt)
    assert invoice.status == "cancelled" and invoice.xiaoman_order_id == "123"
    assert receipt.status == "remote_deleted" and receipt.collect_status is None
    assert receipt.amount == Decimal("168") and receipt.bank_charge == Decimal("8")
    assert receipt.xiaoman_receipt_id == "88" and receipt.attachment_ids == ["proof-retained"]
    assert db.query(ReceiptLog).filter_by(receipt_id=receipt.id, action="remote_deleted").count() == 1
    assert db.query(InvoiceSyncLog).filter_by(invoice_id=invoice.id, action="cancel_step").count() >= 7
    assert db.query(ShippingOperationEvent).filter_by(scope=outbound_delete_service.SCOPE, request_id="7").one().action == "outbound_deleted"
    assert db.query(OkkiOutboundTask).filter_by(invoice_id=invoice.id).one().reason == "deleted:7"
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]


def test_existing_cancel_pending_can_continue_directly(db, invoice, receipt, live, user):
    invoice.status = "cancel_pending"
    invoice.cancellation = {"status": "blocked", "previous_status": "synced", "reason": "Wrong customer"}
    db.commit()
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert invoice.cancellation["previous_status"] == "synced"


@pytest.mark.parametrize("blocker", ["shipped", "shared", "batch", "inventory", "legacy_uncertain"])
def test_all_blockers_preflight_before_any_post(db, invoice, receipt, live, user, blocker):
    if blocker == "shipped":
        live["outbound"]["status"] = 2
    elif blocker == "shared":
        live["outbound"]["record_list"].append({"order_id": "other-order"})
    elif blocker == "batch":
        # An actual batch relationship is not necessary to exercise the guard.
        receipt.batch_id = 77
    elif blocker == "inventory":
        material = SemifinishedMaterial(material_code="INV-TEST", size="18", color_code="1", color_key="1")
        db.add(material)
        db.flush()
        db.add(InvoiceAllocation(invoice_id=invoice.id, material_id=material.id,
            allocated_qty_grams=0, pending_delta_grams=10, status="pending"))
    else:
        invoice.status = "cancel_pending"
        invoice.cancellation = {"status": "uncertain"}
    db.commit()
    assert execute(db, invoice, user)["status"] == "blocked"
    assert live["posts"] == []
    assert receipt.status == "active"


@pytest.mark.parametrize("changed", ["order", "outbound", "receipt", "local"])
def test_confirmation_version_changes_prevent_post(db, invoice, receipt, live, user, changed):
    version = deletion.preview(db, invoice, user)["version"]
    if changed == "local":
        receipt.bank_charge = 9
        receipt.version += 1
        db.commit()
    else:
        live[changed]["remark"] = "changed after preview"
    with pytest.raises(ValueError, match="变化"):
        deletion.run(db, invoice.id, user, version)
    assert live["posts"] == []


@pytest.mark.parametrize("kind", ["outbound", "receipt", "order"])
def test_unknown_delete_is_read_back_and_never_replayed(db, invoice, receipt, live, user, kind):
    live["uncertain"].add(kind)
    assert execute(db, invoice, user)["status"] == "uncertain"
    sent = list(live["posts"])
    assert execute(db, invoice, user)["status"] == "uncertain"
    assert live["posts"] == sent
    assert invoice.status == "cancel_pending"
    live[kind] = None  # Later complete live evidence proves the original attempt succeeded.
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]
    assert receipt.status == "remote_deleted"
    assert db.query(ReceiptLog).filter_by(receipt_id=receipt.id, action="remote_deleted").count() == 1


@pytest.mark.parametrize("missing", ["receipt:admin", "shipping_inspection:delete"])
def test_related_permissions_are_checked_before_post(db, invoice, receipt, live, user, missing):
    user["permissions"].remove(missing)
    with pytest.raises(HTTPException) as error:
        execute(db, invoice, user)
    assert error.value.status_code == 403 and live["posts"] == []


def test_receipt_scope_is_enforced_even_with_invoice_read_all(db, invoice, receipt, live, user):
    user["sub"] = "2"
    user["permissions"].append("invoice:read_all")
    with pytest.raises(HTTPException) as error:
        execute(db, invoice, user)
    assert error.value.status_code == 404 and live["posts"] == []


def test_outbound_scope_is_passed_to_lookup_and_missing_row_blocks(db, invoice, receipt, live, user, monkeypatch):
    from app.shipping_inspection import router
    user["permissions"].remove("shipping_inspection:read_all")
    monkeypatch.setattr(router, "_outbound_scope", lambda db, actor: "okki-sales-1")
    live["visible"] = False
    with pytest.raises(HTTPException) as error:
        execute(db, invoice, user)
    assert error.value.status_code == 404
    assert live["scope_calls"] == ["okki-sales-1"] and live["posts"] == []


@pytest.fixture
def client(db, user):
    app = FastAPI()
    app.include_router(deletion_router.router, prefix="/api/invoice")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as result:
        yield result


def test_api_requires_invoice_admin_and_explicit_confirmation(client, db, invoice, receipt, live, user):
    path = f"/api/invoice/invoices/{invoice.id}/deletion"
    user["permissions"].remove("invoice:admin")
    assert client.get(path).status_code == 403
    assert client.post(path, json={"expected_version": "a" * 64, "confirmed": True}).status_code == 403
    user["permissions"].append("invoice:admin")
    version = deletion.preview(db, invoice, user)["version"]
    assert client.post(path, json={"expected_version": version}).status_code == 409
    assert client.post(path, json={"expected_version": version, "confirmed": False}).status_code == 409
    assert live["posts"] == []


def test_api_invoice_data_scope_blocks_other_salesperson(client, invoice, receipt, live, user):
    user["sub"] = "2"
    assert client.get(f"/api/invoice/invoices/{invoice.id}/deletion").status_code in (403, 404)
    assert live["posts"] == []


def test_active_execution_lease_does_not_start_second_delete(db, invoice, receipt, live, user):
    invoice.status = "cancel_pending"
    invoice.cancellation = {"status": "cascade_running", "deletion": {
        "token": "existing-owner", "lease_until": (beijing_now() + timedelta(minutes=5)).isoformat(), "steps": {}}}
    db.commit()
    assert execute(db, invoice, user)["status"] == "running"
    assert live["posts"] == []


@pytest.mark.parametrize("target", ["invoice", "receipt"])
def test_local_change_between_discovery_and_lock_never_posts(db, invoice, receipt, live, user, monkeypatch, target):
    original = deletion._lock
    first = True
    def race(session, identity):
        nonlocal first
        if first:
            first = False
            if target == "invoice":
                session.execute(update(Invoice).where(Invoice.id == identity).values(total_amount=169),
                    execution_options={"synchronize_session": False})
            else:
                session.execute(update(Receipt).where(Receipt.id == receipt.id).values(amount=169, version=2),
                    execution_options={"synchronize_session": False})
            session.commit()
        return original(session, identity)
    monkeypatch.setattr(deletion, "_lock", race)
    with pytest.raises(ValueError, match="变化"):
        execute(db, invoice, user)
    assert live["posts"] == []


def test_outbound_changed_at_exact_delete_boundary_has_no_post(db, invoice, receipt, live, user, monkeypatch):
    def changed(*args):
        result = deepcopy(live["outbound"])
        result["record_list"][0]["outbound_count"] = 2
        return result
    monkeypatch.setattr(outbound_delete_client, "read", changed)
    assert execute(db, invoice, user)["status"] == "uncertain"
    assert live["posts"] == []


def test_receipt_changed_before_its_delete_preserves_completed_outbound(db, invoice, receipt, live, user, monkeypatch):
    original = lifecycle_remote.request
    def changed(token, kind, identity, remove=False):
        if kind == "receipt" and not remove:
            result = deepcopy(live["receipt"])
            result["amount"] = "159"
            return result
        return original(token, kind, identity, remove=remove)
    monkeypatch.setattr(lifecycle_remote, "request", changed)
    assert execute(db, invoice, user)["status"] == "blocked"
    assert live["posts"] == ["outbound"]
    assert invoice.cancellation["deletion"]["steps"]["outbound:7"]["status"] == "done"
    monkeypatch.setattr(lifecycle_remote, "request", original)
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]


def test_local_receipt_changed_during_delete_is_not_overwritten(db, invoice, receipt, live, user, monkeypatch):
    original = outbound_delete_client.remove
    def changed(*args):
        result = original(*args)
        db.execute(update(Receipt).where(Receipt.id == receipt.id).values(amount=169, version=2),
            execution_options={"synchronize_session": False})
        db.commit()
        return result
    monkeypatch.setattr(outbound_delete_client, "remove", changed)
    assert execute(db, invoice, user)["status"] == "blocked"
    assert live["posts"] == ["outbound", "receipt"]
    db.refresh(receipt)
    assert receipt.status == "active" and receipt.amount == Decimal("169")
    assert db.query(ReceiptLog).filter_by(receipt_id=receipt.id, action="remote_deleted").count() == 0
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]
    assert receipt.amount == Decimal("169")


@pytest.mark.parametrize("field,value", [("amount", "169"), ("account_date", "2026-10-02"),
    ("users", [{"id": "another-salesperson"}]), ("departments", ["another-department"]),
    (FIELD_ORDER_TYPE, "changed")])
def test_parent_changed_during_children_deletion_requires_new_confirmation(db, invoice, receipt, live, user, monkeypatch, field, value):
    original = lifecycle_remote.request
    def changed(token, kind, identity, remove=False):
        result = original(token, kind, identity, remove=remove)
        if kind == "receipt" and remove:
            live["order"][field] = value
        return result
    monkeypatch.setattr(lifecycle_remote, "request", changed)
    assert execute(db, invoice, user)["status"] == "blocked"
    assert live["posts"] == ["outbound", "receipt"]
    assert receipt.status == "remote_deleted"
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]


def test_missing_receipt_detail_with_active_index_blocks_all_deletes(db, invoice, receipt, live, user, monkeypatch):
    live["receipt"] = None
    monkeypatch.setattr(remote, "order_receipts", lambda *a: [{"cash_collection_id": "88"}])
    assert execute(db, invoice, user)["status"] == "blocked"
    assert live["posts"] == []


def test_unsent_local_receipt_is_voided_with_amount_and_proof_retained(db, invoice, receipt, live, user):
    live["receipt"] = None
    receipt.xiaoman_receipt_id = None
    receipt.sync_status = "pending"
    db.commit()
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "order"]
    assert receipt.status == "voided" and receipt.amount == Decimal("168")
    assert receipt.bank_charge == Decimal("8") and receipt.attachment_ids == ["proof-retained"]


def test_soft_deleted_order_detail_can_remain_readable_without_replaying(db, invoice, receipt, live, user, monkeypatch):
    original = lifecycle_remote.request
    before = deepcopy(live["order"])
    def soft_delete(token, kind, identity, remove=False):
        result = original(token, kind, identity, remove=remove)
        if kind == "order" and remove:
            live["order"] = before
            live["order_active"] = False
        return result
    monkeypatch.setattr(lifecycle_remote, "request", soft_delete)
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["order"] == before and invoice.status == "cancelled"
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]


def test_order_active_list_failure_after_post_keeps_unknown_and_does_not_replay(db, invoice, receipt, live, user, monkeypatch):
    original = lifecycle_remote.request
    before = deepcopy(live["order"])
    fail = False
    def deletion_timeout(token, kind, identity, remove=False):
        nonlocal fail
        result = original(token, kind, identity, remove=remove)
        if kind == "order" and remove:
            live["order"] = before
            live["order_active"] = False
            fail = True
        return result
    def active(*args):
        if fail:
            raise ValueError("Incomplete active-list response")
        return live.get("order_active", True)
    monkeypatch.setattr(lifecycle_remote, "request", deletion_timeout)
    monkeypatch.setattr(remote, "order_active", active)
    assert execute(db, invoice, user)["status"] == "uncertain"
    assert invoice.status == "cancel_pending"
    with pytest.raises(ValueError, match="Incomplete"):
        execute(db, invoice, user)
    assert live["posts"] == ["outbound", "receipt", "order"]
    fail = False
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    assert live["posts"] == ["outbound", "receipt", "order"]


def test_absent_outbound_does_not_hold_other_order_from_stale_mirror(db, invoice, receipt, live, user, monkeypatch):
    other = Invoice(invoice_no="OTHER-ORDER", order_type="stock", customer_id="101", customer_name="Other",
        sales_user_id=1, created_by=1, invoice_date=date(2026, 10, 1), currency="USD", total_amount=100,
        xiaoman_order_id="999", sync_status="synced", status="synced")
    db.add(other)
    db.flush()
    task = OkkiOutboundTask(invoice_id=other.id, order_id="999", status="pending", reason="untouched")
    db.add(task)
    db.commit()
    def absent(*args):
        live["outbound"] = None
        return None
    monkeypatch.setattr(outbound_delete_client, "read", absent)
    monkeypatch.setattr(outbound_delete_service, "_mirror_order_ids",
        lambda *args: pytest.fail("An absent outbound with exact expected order must not use stale mirror links"))
    assert execute(db, invoice, user)["status"] == "remote_deleted"
    db.refresh(task)
    assert task.status == "pending" and task.reason == "untouched"
    assert live["posts"] == ["receipt", "order"]
