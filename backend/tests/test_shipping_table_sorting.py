"""Shipping sorts the scoped merged query before LIMIT, including verified overlays."""
from datetime import datetime

import pytest
from sqlalchemy import event, text

from app.shipping_inspection import outbound_queue_service as queue, outbound_service, service
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from tests.test_shipping_outbound_queue import waiting
from tests.test_shipping_record_filters import records_with_sales
from tests.test_shipping_inspection_scope import scoped_inspections
from tests.test_shipping_inspection import outbound_scope_seed, product_display_source, storage


@pytest.mark.parametrize("field", sorted(queue.QUEUE_SORT_FIELDS))
def test_merged_queue_all_fields_sort_before_page_and_keep_scope(db, waiting, field):
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first, total = queue.list_outbound_records(db, page=1, page_size=1, okki_user_id="9001", sort_field=field, sort_order="asc")
        second, again = queue.list_outbound_records(db, page=2, page_size=1, okki_user_id="9001", sort_field=field, sort_order="asc")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert total == again == 2
    assert first[0]["outbound_record_id"] != second[0]["outbound_record_id"]
    page_sql = [s for s in statements if "COUNT(*) OVER ()" in s]
    assert len(page_sql) == 2
    assert all("sort_value IS NULL ASC, sort_value ASC" in s and "LIMIT" in s for s in page_sql)
    assert all("OB002" != r["outbound_record_id"] for r in first + second)
    if field in ("status", "photo_count"):
        assert second[0]["record_source"] == "ark_task"  # its display is missing, so remains last
    full, _ = queue.list_outbound_records(db, page_size=20, okki_user_id="9001", sort_field=field, sort_order="asc")
    assert [r["outbound_record_id"] for r in first + second] == [r["outbound_record_id"] for r in full]


def test_queue_draft_photo_counts_and_stored_counts_are_numeric(db, waiting):
    db.add(ShippingInspection(outbound_record_id="OB001", status="draft", photo_count=100))
    db.add(ShippingInspection(outbound_record_id="OB002", status="submitted", photo_count=10))
    db.flush()
    draft = db.query(ShippingInspection).filter_by(outbound_record_id="OB001").one()
    db.add_all([ShippingInspectionPhoto(inspection_id=draft.id, file_path=f"{i}.jpg") for i in range(2)])
    db.commit()
    rows, _ = queue.list_outbound_records(db, page_size=1, sort_field="photo_count", sort_order="asc")
    assert rows[0]["outbound_record_id"] == "OB001"
    rows, _ = queue.list_outbound_records(db, page_size=1, sort_field="photo_count", sort_order="desc")
    assert rows[0]["outbound_record_id"] == "OB002"


def test_queue_sorts_visible_verified_header_and_counts(db, waiting):
    # This newer snapshot is exactly what apply_header presents before mirror catch-up.
    db.add(ShippingOperationEvent(scope="outbound-invoice-sync", request_id="OB001", outbound_record_id="OB001",
        source="pc", action="sync_done", login_user_id=waiting[0].id, operator_user_id=waiting[0].id, operator_name="Sort", login_name="Sort", result={"verified": {"update_time": "2026-10-04 12:00:00",
        "serial_id": "ZZZZ-verified", "remark": "verified", "items": [{"qty": 1} for _ in range(12)]}}))
    db.commit()
    rows, _ = queue.list_outbound_records(db, page_size=1, sort_field="outbound_no", sort_order="desc")
    assert rows[0]["outbound_no"] == "ZZZZ-verified"
    rows, _ = queue.list_outbound_records(db, page_size=1, sort_field="item_count", sort_order="desc")
    assert rows[0]["outbound_record_id"] == "OB001" and rows[0]["item_count"] == 12


@pytest.mark.parametrize("field", ["outbound_no", "order_id", "customer_name", "photo_count", "salesperson_name", "submitted_by_name", "submitted_at", "remark"])
def test_inspection_sort_fields_use_linked_values_before_pagination(db, records_with_sales, field):
    full, total = service.list_records(db, page_size=20, sort_field=field, sort_order="asc")
    first, again = service.list_records(db, page_size=1, page=1, sort_field=field, sort_order="asc")
    second, _ = service.list_records(db, page_size=1, page=2, sort_field=field, sort_order="asc")
    assert total == again == 2
    assert [r["id"] for r in first + second] == [r["id"] for r in full]
    if field == "salesperson_name":
        assert [r["salesperson_name"] for r in full] == ["Eva", "Tessie"]


def test_queue_unknown_field_cannot_become_sql(db, waiting):
    default, total = queue.list_outbound_records(db, page_size=20)
    rows, again = queue.list_outbound_records(db, page_size=20, sort_field="customer_name; DROP TABLE ark_users", sort_order="desc")
    assert rows == default and again == total
