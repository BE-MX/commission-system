"""Local stock-waiting rows share pagination, but cannot become printable documents."""
import json
from datetime import date, datetime

import pytest
from sqlalchemy import text

from app.invoice.models import Invoice, InvoiceItem, InvoiceSyncLog, OkkiOutboundTask
from app.shipping_inspection import outbound_queue_service as queue, outbound_service
from tests.test_shipping_inspection import _user, _bind_okki, _pc_client, outbound_scope_seed, product_display_source


@pytest.fixture
def waiting(db, outbound_scope_seed):
    sales = _user(db, "waiting-sales")
    _bind_okki(db, sales)
    other = _user(db, "other-sales")
    _bind_okki(db, other, "9002")
    invoice = Invoice(invoice_no="WAIT-0917", customer_id="C3", customer_name="Waiting Customer",
                      invoice_date=date(2026, 9, 17), sales_user_id=sales.id, sales_user_name="April",
                      xiaoman_order_id="ORDER-WAIT", sync_status="synced")
    db.add(invoice)
    db.flush()
    db.add(InvoiceSyncLog(invoice_id=invoice.id, action="create", success=1))
    db.add(InvoiceItem(invoice_id=invoice.id, product_name="Replacement Tapes", product_display="Tapes",
                       color="", quantity=10, sku_id=321))
    task = OkkiOutboundTask(invoice_id=invoice.id, order_id="ORDER-WAIT", status="waiting_stock",
        created_at=datetime(2026, 9, 18, 0, 0, 1), processed_at=datetime(2026, 9, 18, 10, 18),
        last_error=json.dumps({"outcome": "waiting_stock", "shortages": [
            {"sku_id": "321", "required": 10, "available": 0}]}))
    db.add(task)
    db.commit()
    return sales, other, task


def test_waiting_row_lists_shortages_and_blocks_direct_print_and_download(db, waiting):
    sales, _, task = waiting
    with _pc_client(db, sales, ["shipping_inspection:read"]) as client:
        base = "/api/shipping-inspection/outbound-records"
        response = client.get(base, params={"keyword": "WAIT-0917"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 1
        row = data["items"][0]
        assert row["outbound_state"] == "waiting_stock" and row["can_print"] is False
        assert row["outbound_date"] is None and row["requested_date"] == "2026-09-18"
        assert row["total_qty"] == 10 and row["item_count"] == 1
        assert row["stock_shortages"] == [{"product_name": "Replacement Tapes", "sku_id": "321",
            "required": 10, "available": 0, "shortage": 10}]
        for suffix in ("print-data", "word"):
            assert client.get(f"{base}/task:{task.id}/{suffix}").status_code == 404


def test_waiting_rows_obey_scope_and_all_permissions(db, waiting):
    _, other, _ = waiting
    with _pc_client(db, other, ["shipping_inspection:read"]) as client:
        assert client.get("/api/shipping-inspection/outbound-records", params={"keyword": "WAIT"}).json()["data"]["total"] == 0
    with _pc_client(db, other, ["shipping_inspection:read", "shipping_inspection:read_all"]) as client:
        assert client.get("/api/shipping-inspection/outbound-records", params={"keyword": "WAIT"}).json()["data"]["total"] == 1


def test_combined_pagination_and_beijing_date_boundaries(db, waiting, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    pages = [queue.list_outbound_records(db, page=page, page_size=1, okki_user_id="9001") for page in (1, 2, 3)]
    assert [total for _, total in pages] == [2, 2, 2]
    ids = [row["outbound_record_id"] for rows, _ in pages for row in rows]
    assert len(ids) == len(set(ids)) == 2
    for day, expected in [(17, 0), (18, 1), (19, 0)]:
        _, total = queue.list_outbound_records(db, keyword="WAIT", date_from=date(2026, 9, day), date_to=date(2026, 9, day))
        assert total == expected


@pytest.mark.parametrize("state", ["pending", "running", "done", "failed", "uncertain"])
def test_local_row_does_not_disappear_during_retry_or_sync(db, waiting, state):
    _, _, task = waiting
    task.status = state
    db.commit()
    rows, total = queue.list_outbound_records(db, keyword="WAIT")
    assert total == 1 and not rows[0]["can_print"]
    assert rows[0]["outbound_state"] == ("awaiting_sync" if state == "done" else state)


@pytest.mark.parametrize("renamed", [False, True])
def test_mirror_arrival_replaces_preview_even_before_task_finishes(db, waiting, renamed):
    db.execute(text("""INSERT INTO lsordertest.okki_outbound_records
        (id,outbound_no,company_id,customer_name,outbound_date)
        VALUES ('OB003','WAIT-0917','C3','Waiting Customer','2026-09-18')"""))
    if renamed:
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_no='Renamed' WHERE id='OB003'"))
        db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT"))
        db.execute(text("""INSERT INTO lsordertest.okki_outbound_record_items (id,outbound_record_id,order_id)
            VALUES ('IT004','OB003','ORDER-WAIT')"""))
        outbound_service._columns_cache.clear()
    db.commit()
    rows, total = queue.list_outbound_records(db, keyword="Waiting Customer")
    assert total == 1 and rows[0]["outbound_record_id"] == "OB003"
    assert rows[0]["can_print"] is True


@pytest.mark.parametrize("raw", ['{"shortages":', '{"shortages":[{"required":"NaN","available":0}]}', '[]'])
def test_invalid_shortage_logs_are_not_exposed(db, waiting, raw):
    waiting[2].last_error = raw
    db.commit()
    rows, _ = queue.list_outbound_records(db, keyword="WAIT")
    assert rows[0]["stock_shortages"] == []
    assert "last_error" not in rows[0]


def test_nonstandard_skipped_task_is_not_presented_as_stock_waiting(db, waiting):
    waiting[2].status, waiting[2].reason = "skipped", "generic custom line"
    db.commit()
    assert queue.list_outbound_records(db, keyword="WAIT")[1] == 0


def test_header_only_sync_keeps_preview_until_formal_row_is_visible_to_owner(db, waiting):
    db.execute(text("""INSERT INTO lsordertest.okki_outbound_records
        (id,outbound_no,company_id,customer_name,outbound_date)
        VALUES ('OB003','WAIT-0917','C3','Waiting Customer','2026-09-18')"""))
    db.commit()
    rows, total = queue.list_outbound_records(db, keyword="WAIT", okki_user_id="9001")
    assert total == 1 and rows[0]["record_source"] == "ark_task"
    db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT"))
    db.execute(text("""INSERT INTO lsordertest.okki_outbound_record_items (id,outbound_record_id,order_id)
        VALUES ('IT004','OB003','ORDER-WAIT')"""))
    outbound_service._columns_cache.clear()
    db.commit()
    rows, total = queue.list_outbound_records(db, keyword="WAIT", okki_user_id="9001")
    assert total == 1 and rows[0]["outbound_record_id"] == "OB003"
