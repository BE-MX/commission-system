"""Operational query sorting regression tests on isolated SQLite fixtures."""
from decimal import Decimal

from app.production.models import Process
from app.production.process_service import list_processes
from app.semifinished.models import InventoryBalance, SemifinishedMaterial
from app.semifinished.inventory_service import list_inventory


def test_process_sort_full_query_ties_nulls_and_clear(db):
    rows = [Process(name=name, description=description, sort_order=index, status=1) for index, (name, description) in enumerate((("Z", "same"), ("A", None), ("B", "first"), ("C", "same")))]
    db.add_all(rows); db.flush()
    assert [row.name for row in list_processes(db, page_size=2, sort_field="name", sort_order="asc")[0]] == ["A", "B"]
    assert [row.name for row in list_processes(db, page=2, page_size=2, sort_field="name", sort_order="asc")[0]] == ["C", "Z"]
    for direction in ("asc", "desc"):
        result, total = list_processes(db, page_size=100, sort_field="description", sort_order=direction)
        assert total == 4
        assert result[-1].name == "A"
        assert [row.name for row in result if row.description == "same"] == ["Z", "C"]
    assert [row.name for row in list_processes(db, page_size=100, sort_field="", sort_order="")[0]] == ["Z", "A", "B", "C"]
    assert [row.name for row in list_processes(db, name="B", sort_field="name", sort_order="desc")[0]] == ["B"]


def test_semifinished_available_sort_before_limit(db):
    for code, on_hand, reserved in (("SF-A", 100, 90), ("SF-B", 30, 0), ("SF-C", 80, 20)):
        material = SemifinishedMaterial(material_code=code, size="16", color_code=code, color_key=code, color_type="solid", safety_stock_grams=Decimal("20"), status="active")
        db.add(material); db.flush()
        db.add(InventoryBalance(material_id=material.id, on_hand_grams=on_hand, reserved_grams=reserved))
    db.flush()
    assert [row["material_code"] for row in list_inventory(db, 1, 2, sort_field="available_grams", sort_order="desc")["items"]] == ["SF-C", "SF-B"]
    assert list_inventory(db, 2, 2, sort_field="available_grams", sort_order="desc")["items"][0]["material_code"] == "SF-A"
    assert list_inventory(db, 1, 2, keyword="SF-A", sort_field="available_grams", sort_order="desc")["total"] == 1


class _EmptySqlResult:
    def scalar(self):
        return 1

    def mappings(self):
        return self

    def all(self):
        return []


class _CaptureSql:
    def __init__(self):
        self.sql = []

    def execute(self, statement, params=None):
        self.sql.append(str(statement))
        return _EmptySqlResult()


def test_stock_aggregate_and_joined_sort_sql_before_limit():
    from app.stock.production_order_service import get_order_list, get_order_item_list
    from app.stock.print_workstation_service import get_print_order_list
    for service, fields, identity in (
        (get_order_list, ("created_by_name", "item_count", "total_order_qty", "total_received_qty", "total_in_transit_qty"), "o.id"),
        (get_order_item_list, ("in_transit_qty", "status", "order_status", "is_urgent", "expected_delivery_date"), "i.id"),
        (get_print_order_list, ("item_count", "total_order_qty", "last_order_printed_at"), "o.id"),
    ):
        for field in fields:
            for direction in ("asc", "desc"):
                db = _CaptureSql()
                service(db, page=2, page_size=3, sort_field=field, sort_order=direction)
                sql = next(sql for sql in db.sql if "LIMIT :limit OFFSET :offset" in sql)
                assert "IS NULL) ASC" in sql
                assert f"{direction.upper()}, {identity} ASC" in sql
                assert sql.index("ORDER BY") < sql.index("LIMIT :limit OFFSET :offset")


def test_semifinished_component_summary_mysql_query_shape(db):
    from sqlalchemy import event
    from app.semifinished.material_service import list_mappings
    import pytest
    captured = []
    class CapturedSql(Exception):
        pass
    def before_execute(_conn, _cursor, statement, _params, _context, _many):
        if "GROUP_CONCAT" in statement:
            captured.append(statement)
            raise CapturedSql()
    connection = db.connection()
    event.listen(connection, "before_cursor_execute", before_execute)
    try:
        with pytest.raises(CapturedSql):
            list_mappings(db, 2, 5, None, False, sort_field="components", sort_order="desc")
    finally:
        event.remove(connection, "before_cursor_execute", before_execute)
    sql = captured[0]
    assert "WHERE sc.mapping_id = ark_semifinished_product_mappings.id" in sql
    assert "ORDER BY sc.component_order" in sql
    assert sql.index("GROUP_CONCAT") < sql.index("LIMIT")
    assert "IS NULL ASC" in sql


def test_invoice_and_receipt_joined_display_sort_before_paging(db):
    from datetime import date
    import json
    from app.auth.models import ArkUser
    from app.invoice.models import Invoice, InvoiceItem
    from app.invoice.service import list_invoices
    from app.receipt.models import Receipt
    from app.receipt.service import list_receipts
    db.connection().connection.driver_connection.create_function("json_length", 1, lambda value: len(json.loads(value)))
    user = ArkUser(username="sort-seller", real_name="Sorter", password_hash="x")
    db.add(user); db.flush()
    for number, name, amount, count in (("SORT-1", "Zulu", 100, 0), ("SORT-2", "Alpha", 20, 2), ("SORT-3", "Beta", 80, 1)):
        invoice = Invoice(invoice_no=number, customer_id=number, customer_name=name, invoice_date=date(2026, 10, 1), sales_user_id=user.id, created_by=user.id, total_amount=amount)
        db.add(invoice); db.flush()
        for index in range(count):
            db.add(InvoiceItem(invoice_id=invoice.id, sort_order=index, product_name=f"Item {index}", product_display=f"Item {index}", color="Black", quantity=1, price_per_piece=1, total_price=1))
        db.add(Receipt(receipt_no=f"RC-{number}", invoice_id=invoice.id, source="manual", request_key=number, request_hash=number, amount=amount, currency="USD", collection_date=date(2026, 10, 1), payment_type="bank", customer_id=number, created_by=user.id, attachment_ids=list(range(count))))
    db.flush()
    rows, total = list_invoices(db, page_size=2, sort_field="item_count", sort_order="desc", viewer_user_id=user.id)
    assert total == 3
    assert [row["invoice_no"] for row in rows] == ["SORT-2", "SORT-3"]
    assert list_invoices(db, page=2, page_size=2, sort_field="item_count", sort_order="desc", viewer_user_id=user.id)[0][0]["invoice_no"] == "SORT-1"
    viewer = {"sub": str(user.id), "permissions": []}
    assert [row["customer_name"] for row in list_receipts(db, viewer, page_size=2, sort_field="customer_name", sort_order="asc")["items"]] == ["Alpha", "Beta"]
    assert [row["attachment_count"] for row in list_receipts(db, viewer, page_size=2, sort_field="attachment_count", sort_order="desc")["items"]] == [2, 1]
    assert list_receipts(db, {"sub": str(user.id + 999), "permissions": []}, sort_field="amount", sort_order="desc")["total"] == 0
