"""Warehouse inspection board: pending queue, priority marks, today's KPIs and 7-day trend."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.time import beijing_today
from app.invoice.customer_profile_service import save_customer_grade
from app.invoice.models import Invoice
from app.shipping_inspection import board_service, outbound_service
from app.shipping_inspection.models import ShippingInspection
from tests.test_shipping_inspection import _pc_client, _user


@pytest.fixture
def board(db):
    outbound_service._columns_cache.clear()
    for column in ("company_id TEXT", "create_time TEXT"):
        db.execute(text(f"ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN {column}"))
    db.execute(text("ALTER TABLE lsordertest.okki_outbound_record_items ADD COLUMN order_id TEXT"))
    today = beijing_today()
    stamp = lambda days, hour: f"{(today - timedelta(days=days)).isoformat()} {hour:02d}:00:00"
    db.execute(text("DELETE FROM lsordertest.okki_outbound_records"))
    db.execute(text("DELETE FROM lsordertest.okki_outbound_record_items"))
    rows = [
        # id, no, company, customer, created
        ("R1", "CK-NEW", "C1", "New Co", stamp(0, 9)),
        ("R2", "CK-S", "C2", "Grade S", stamp(1, 9)),
        ("R3", "CK-OLD", "C3", "Plain", stamp(3, 9)),
        ("R4", "CK-DONE", "C2", "Grade S", stamp(1, 10)),
        ("R5", "CK-DONE2", "C3", "Plain", stamp(2, 10)),
        ("R6", "CK-ANCIENT", "C3", "Plain", stamp(90, 10)),
    ]
    for rid, no, company, name, created in rows:
        db.execute(text("""INSERT INTO lsordertest.okki_outbound_records
            (id, outbound_no, outbound_date, customer_name, company_id, create_time)
            VALUES (:rid, :no, :d, :name, :company, :created)"""),
            {"rid": rid, "no": no, "d": created[:10], "name": name, "company": company, "created": created})
    items = [("I1", "R1", 10, "O1"), ("I2", "R1", 5, "O1"), ("I3", "R2", 7, "O2"),
             ("I4", "R3", 3, "O3"), ("I5", "R4", 20, "O4"), ("I6", "R4", 1, "O4"), ("I7", "R5", 4, "O5")]
    for iid, rid, qty, order in items:
        db.execute(text("""INSERT INTO lsordertest.okki_outbound_record_items
            (id, outbound_record_id, product_name, quantity, unit, order_id)
            VALUES (:iid, :rid, 'P', :qty, '件', :order)"""), {"iid": iid, "rid": rid, "qty": qty, "order": order})
    for order, company, amount in [("O1", "C1", 100), ("O2", "C2", 200), ("O3", "C3", 300),
                                   ("O4", "C2", 400.5), ("O5", "C3", 50)]:
        db.execute(text("INSERT INTO lsordertest.okki_orders(order_id, company_id, amount_usd) VALUES (:o,:c,:a)"),
                   {"o": order, "c": company, "a": amount})
    save_customer_grade(db, "C2", "S", None)
    db.add(Invoice(invoice_no="INV1", customer_id="C1", customer_name="New Co", invoice_date=date(2026, 10, 1),
                   currency="USD", sync_status="synced", total_amount=Decimal("100"), xiaoman_order_id="O1",
                   okki_new_deal=1, inspection_requirement="detail", sales_user_name="Tessie"))
    inspector = _user(db, "inspector-zhang")
    now = datetime.combine(beijing_today(), time(9, 30))
    db.add_all([
        ShippingInspection(outbound_record_id="R4", outbound_no="CK-DONE", customer_name="Grade S",
                           status="submitted", submitted_at=now, submitted_by=inspector.id, photo_count=1),
        ShippingInspection(outbound_record_id="R5", outbound_no="CK-DONE2", customer_name="Plain",
                           status="submitted", submitted_at=now - timedelta(days=2), submitted_by=inspector.id,
                           photo_count=1),
        ShippingInspection(outbound_record_id="R3", outbound_no="CK-OLD", customer_name="Plain", status="draft"),
    ])
    db.commit()
    yield inspector
    outbound_service._columns_cache.clear()


def test_pending_excludes_submitted_and_out_of_window_and_marks_priority(db, board):
    data = board_service.build_board(db)
    pending = {row["outbound_record_id"]: row for row in data["pending"]}
    assert set(pending) == {"R1", "R2", "R3"}
    assert pending["R1"]["is_new_deal"] is True
    assert pending["R1"]["inspection_requirement"] == "detail"
    assert pending["R1"]["item_count"] == 2 and pending["R1"]["total_qty"] == 15
    assert pending["R2"]["customer_grade"] == "S" and pending["R2"]["is_new_deal"] is False
    assert pending["R3"]["inspecting"] is True
    assert pending["R1"]["created_at"].startswith(beijing_today().isoformat())


def test_today_kpis_and_trend_count_only_today_submissions(db, board):
    data = board_service.build_board(db)
    assert data["today"] == {"orders": 1, "qty": 21, "customers": 1, "amount_usd": 400.5,
                             "amount_missing_orders": 0}
    assert data["done"][0]["outbound_no"] == "CK-DONE"
    assert data["done"][0]["inspector_name"] == "inspector-zhang"
    assert data["done"][0]["customer_grade"] == "S"
    assert data["inspectors"] == [{"name": "inspector-zhang", "count": 1}]
    trend = {row["date"]: row for row in data["trend"]}
    assert len(trend) == 7
    assert trend[beijing_today().isoformat()] == {"date": beijing_today().isoformat(), "orders": 1, "qty": 21}
    two_days = (beijing_today() - timedelta(days=2)).isoformat()
    assert trend[two_days]["orders"] == 1 and trend[two_days]["qty"] == 4


def test_split_outbound_counts_order_amount_once_and_flags_missing(db, board):
    db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id='O4' WHERE id='I7'"))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET company_id='C2' WHERE id='R5'"))
    db.query(ShippingInspection).filter_by(outbound_record_id="R5").update(
        {"submitted_at": datetime.combine(beijing_today(), time(10, 0))})
    db.commit()
    assert board_service.build_board(db)["today"]["amount_usd"] == 400.5
    db.execute(text("DELETE FROM lsordertest.okki_orders WHERE order_id='O4'"))
    db.commit()
    today = board_service.build_board(db)["today"]
    assert today["amount_usd"] == 0 and today["amount_missing_orders"] == 1


def test_beijing_midnight_boundary_uses_beijing_calendar(db, board, monkeypatch):
    """Submission at 23:59 yesterday Beijing time is not today's work, regardless of server zone."""
    db.query(ShippingInspection).filter_by(outbound_record_id="R4").update(
        {"submitted_at": datetime.combine(beijing_today() - timedelta(days=1), time(23, 59, 59))})
    db.commit()
    data = board_service.build_board(db)
    assert data["today"]["orders"] == 0
    yesterday = (beijing_today() - timedelta(days=1)).isoformat()
    assert {row["date"]: row for row in data["trend"]}[yesterday]["orders"] == 1


def test_non_beijing_server_timezone_does_not_shift_today(db, board, monkeypatch):
    import time as systime
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    if hasattr(systime, "tzset"):
        systime.tzset()
    try:
        assert board_service.build_board(db)["today"]["orders"] == 1
    finally:
        monkeypatch.delenv("TZ", raising=False)
        if hasattr(systime, "tzset"):
            systime.tzset()


def test_board_endpoint_requires_read_permission_and_scope(db, board):
    with _pc_client(db, board, []) as client:
        assert client.get("/api/shipping-inspection/board").status_code == 403
    with _pc_client(db, board, ["shipping_inspection:read", "shipping_inspection:read_all"]) as client:
        response = client.get("/api/shipping-inspection/board")
        assert response.status_code == 200
        assert response.json()["data"]["today"]["orders"] == 1
    with _pc_client(db, board, ["shipping_inspection:read"]) as client:
        # No OKKI binding: fail closed instead of showing every customer.
        assert client.get("/api/shipping-inspection/board").status_code == 422
