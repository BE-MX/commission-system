"""Ark-created orders remain visible while the OKKI order mirror is delayed."""
from datetime import date

import pytest
from sqlalchemy import text

from app.invoice.models import Invoice, InvoiceSyncLog
from app.shipping_inspection import outbound_service
from tests.test_shipping_inspection import (
    _bind_okki, _pc_client, _submit_one, _user,
    outbound_scope_seed, product_display_source, storage,
)


@pytest.fixture(params=[False, True], ids=["record-link", "invoice-bridge"])
def local_order(db, outbound_scope_seed, request):
    sales = _user(db, "local-sales")
    _bind_okki(db, sales)
    other = _user(db, "other-sales")
    _bind_okki(db, other, "9003")
    db.execute(text("DELETE FROM lsordertest.okki_orders WHERE company_id='C1'"))
    db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT"))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id='LOCAL-ORDER' WHERE outbound_record_id='OB001'"))
    if request.param:
        db.execute(text("ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN outbound_invoice_id TEXT"))
        db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN outbound_invoice_id TEXT"))
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='invoice-' || id"))
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='invoice-' || outbound_record_id, outbound_record_id='different-entity'"))
    invoice = Invoice(
        invoice_no="LOCAL-INVOICE", customer_id="C1", customer_name="客户甲",
        invoice_date=date(2026, 9, 18), sales_user_id=sales.id,
        created_by=other.id, xiaoman_order_id="LOCAL-ORDER", sync_status="synced",
    )
    db.add(invoice)
    db.flush()
    log = InvoiceSyncLog(invoice_id=invoice.id, action="create", success=1)
    db.add(log)
    db.commit()
    outbound_service._columns_cache.clear()
    return sales, other, invoice, log


def test_local_owner_can_list_print_and_read_inspection_without_order_mirror(db, local_order, storage, monkeypatch):
    sales, other, _, _ = local_order
    monkeypatch.setattr("app.invoice.okki_client.get_outbound_info", lambda _db, oid: {
        "outbound_invoice_id": oid, "handler_info": [{"nickname": "local-sales"}],
    })
    _submit_one(db, other)
    with _pc_client(db, sales, ["shipping_inspection:read"]) as client:
        path = "/api/shipping-inspection"
        result = client.get(path + "/outbound-records", params={"page_size": 1}).json()["data"]
        assert result["total"] == 1
        assert [r["outbound_record_id"] for r in result["items"]] == ["OB001"]
        assert client.get(path + "/outbound-records", params={"page": 2, "page_size": 1}).json()["data"]["items"] == []
        assert client.get(path + "/outbound-records/OB001/print-data").status_code == 200
        assert client.get(path + "/records").json()["data"]["total"] == 1
    # Creating the invoice or inspecting the goods does not confer sales ownership.
    with _pc_client(db, other, ["shipping_inspection:read"]) as client:
        assert client.get(path + "/outbound-records").json()["data"]["total"] == 0
        assert client.get(path + "/outbound-records/OB001/print-data").status_code == 404
        assert client.get(path + "/records").json()["data"]["total"] == 0


@pytest.mark.parametrize("invalid", ["different_order", "different_customer", "failed_create", "imported_update", "inactive_binding", "deleted_binding"])
def test_local_visibility_requires_exact_accepted_order_and_active_owner(db, local_order, invalid):
    sales, _, invoice, log = local_order
    if invalid == "different_order":
        invoice.xiaoman_order_id = "UNRELATED-ORDER"
    elif invalid == "different_customer":
        invoice.customer_id = "C2"
    elif invalid == "failed_create":
        log.success = 0
    elif invalid == "imported_update":
        log.action = "update"
    elif invalid == "inactive_binding":
        db.execute(text("UPDATE ark_user_external_bindings SET binding_status='inactive' WHERE ark_user_id=:uid"), {"uid": sales.id})
    else:
        db.execute(text("UPDATE ark_user_external_bindings SET deleted_at='2026-09-18 08:00:00' WHERE ark_user_id=:uid"), {"uid": sales.id})
    db.commit()
    rows, total = outbound_service.list_outbound_records(db, okki_user_id="9001")
    assert total == 0 and rows == []
    assert outbound_service.get_outbound_record(db, "OB001", okki_user_id="9001") is None


def test_mirror_arrival_does_not_duplicate_results_or_hide_local_owner(db, local_order):
    _, _, invoice, _ = local_order
    # A later failed edit must not invalidate the successfully created order.
    invoice.sync_status = "sync_failed"
    db.execute(text("INSERT INTO lsordertest.okki_orders (order_id,company_id,user_id) VALUES ('LOCAL-ORDER','C1','9001')"))
    db.commit()
    rows, total = outbound_service.list_outbound_records(db, okki_user_id="9001")
    assert total == 1 and len(rows) == 1


def test_same_customer_unrelated_outbound_is_not_granted_by_local_invoice(db, local_order):
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET company_id='C1' WHERE id='OB002'"))
    db.commit()
    rows, total = outbound_service.list_outbound_records(db, okki_user_id="9001")
    assert total == 1
    assert [r["outbound_record_id"] for r in rows] == ["OB001"]
