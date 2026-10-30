"""An old order for a customer never grants access to another seller's outbound."""
import pytest
from sqlalchemy import text

from app.shipping_inspection import outbound_queue_service as queue, outbound_service
from app.shipping_inspection.models import ShippingInspection
from tests.test_shipping_inspection import (
    _bind_okki, _pc_client, _user, outbound_scope_seed, product_display_source,
)


READ = "shipping_inspection:read"
BASE = "/api/shipping-inspection"


@pytest.fixture(params=[False, True], ids=["record-link", "invoice-bridge"])
def shared_customer(db, outbound_scope_seed, request, monkeypatch):
    historical = _user(db, "historical-seller")
    actual = _user(db, "actual-seller")
    _bind_okki(db, historical, "9001")
    _bind_okki(db, actual, "9002")
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET company_id='C1'"))
    db.execute(text("UPDATE lsordertest.okki_orders SET company_id='C1', "
                    "user_id=CASE order_id WHEN 'ORD1' THEN '9002' ELSE '9001' END"))
    db.execute(text("INSERT INTO lsordertest.okki_orders (order_id,company_id,user_id,account_date) "
                    "VALUES ('HISTORY','C1','9001','2023-07-10')"))
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id="
                    "CASE outbound_record_id WHEN 'OB001' THEN 'ORD1' ELSE 'ORD2' END"))
    if request.param:
        db.execute(text("ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN outbound_invoice_id TEXT"))
        db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN outbound_invoice_id TEXT"))
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='bridge-' || id"))
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items "
                        "SET outbound_invoice_id='bridge-' || outbound_record_id, outbound_record_id='other-entity'"))
    inspection = ShippingInspection(outbound_record_id="OB001", outbound_no="CK2026001", status="submitted")
    db.add(inspection)
    db.commit()
    outbound_service._columns_cache.clear()
    monkeypatch.setattr("app.invoice.okki_client.get_outbound_info", lambda _db, identity: {
        "outbound_invoice_id": identity, "handler_info": [{"nickname": "actual-seller"}],
    })
    return historical, actual, inspection


def test_historical_customer_relation_cannot_list_print_or_read_other_sellers_outbound(db, shared_customer):
    historical, actual, inspection = shared_customer
    with _pc_client(db, historical, [READ]) as client:
        listing = client.get(BASE + "/outbound-records").json()["data"]
        assert listing["total"] == 1
        assert [row["outbound_record_id"] for row in listing["items"]] == ["OB002"]
        assert client.get(BASE + "/outbound-records", params={"keyword": "CK2026001"}).json()["data"]["total"] == 0
        assert client.get(BASE + "/outbound-records", params={"page": 2, "page_size": 1}).json()["data"]["items"] == []
        for suffix in ("print-data", "word"):
            assert client.get(BASE + f"/outbound-records/OB001/{suffix}").status_code == 404
        assert client.get(BASE + "/records").json()["data"]["total"] == 0
        assert client.get(BASE + f"/records/{inspection.id}").status_code == 404
    with _pc_client(db, actual, [READ]) as client:
        listing = client.get(BASE + "/outbound-records").json()["data"]
        assert listing["total"] == 1
        assert [row["outbound_record_id"] for row in listing["items"]] == ["OB001"]
        assert client.get(BASE + "/outbound-records/OB001/print-data").status_code == 200
        assert client.get(BASE + "/outbound-records/OB001/word").status_code == 200
        assert client.get(BASE + f"/records/{inspection.id}").status_code == 200


def test_direct_record_and_invoice_bridge_lookups_share_order_scope(db, shared_customer):
    for scope, visible in [("9001", False), ("9002", True)]:
        assert (outbound_service.get_outbound_record(db, "OB001", okki_user_id=scope) is not None) == visible
        if "outbound_invoice_id" in outbound_service._table_columns(db, outbound_service.RECORDS_TABLE):
            record = outbound_service.get_record_by_outbound_invoice_id(db, "bridge-OB001", okki_user_id=scope)
            assert (record is not None) == visible


@pytest.mark.parametrize("invalid", ["missing_order", "no_order_link", "different_customer", "no_owner"])
def test_unresolved_or_mismatched_order_cannot_fall_back_to_customer_history(db, shared_customer, invalid):
    if invalid == "missing_order":
        db.execute(text("DELETE FROM lsordertest.okki_orders WHERE order_id='ORD1'"))
    elif invalid == "no_order_link":
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id=NULL WHERE order_id='ORD1'"))
    elif invalid == "different_customer":
        db.execute(text("UPDATE lsordertest.okki_orders SET company_id='OTHER' WHERE order_id='ORD1'"))
    else:
        db.execute(text("UPDATE lsordertest.okki_orders SET user_id=NULL WHERE order_id='ORD1'"))
    db.commit()
    for scope in ("9001", "9002"):
        rows, total = queue.list_outbound_records(db, keyword="CK2026001", okki_user_id=scope)
        assert (rows, total) == ([], 0)
        assert outbound_service.get_outbound_record(db, "OB001", okki_user_id=scope) is None


def test_explicit_all_scope_and_super_admin_keep_access(db, shared_customer):
    historical, _, _ = shared_customer
    for permissions, roles in [([READ, "shipping_inspection:read_all"], []), ([READ], ["super_admin"])]:
        with _pc_client(db, historical, permissions, roles=roles) as client:
            assert client.get(BASE + "/outbound-records").json()["data"]["total"] == 2
            assert client.get(BASE + "/outbound-records/OB001/print-data").status_code == 200


def test_missing_order_link_column_fails_closed(db, shared_customer):
    db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items DROP COLUMN order_id"))
    outbound_service._columns_cache.clear()
    with pytest.raises(outbound_service.OutboundTableError, match="订单关联"):
        outbound_service.get_outbound_record(db, "OB001", okki_user_id="9001")


def test_multi_order_outbound_is_visible_only_to_its_linked_sellers_without_duplicate_rows(db, shared_customer):
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id='ORD2' WHERE id='IT002'"))
    db.execute(text("INSERT INTO lsordertest.okki_orders (order_id,company_id,user_id) "
                    "VALUES ('UNRELATED','C1','9003')"))
    db.commit()
    for scope in ("9001", "9002"):
        rows, total = queue.list_outbound_records(db, keyword="CK2026001", okki_user_id=scope, page_size=1)
        assert total == 1 and [row["outbound_record_id"] for row in rows] == ["OB001"]
    assert queue.list_outbound_records(db, keyword="CK2026001", okki_user_id="9003") == ([], 0)
