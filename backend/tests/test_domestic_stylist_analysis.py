"""Stylist workload: report quantities, distinct lines, scope and source freshness."""
from datetime import date, datetime
import pytest
from fastapi import HTTPException
from app.domestic_decision.analytics import build_analysis
from app.domestic_decision import run_service, scope
from tests.test_domestic_decision_analytics import dd_seed
from tests.test_domestic_decision_operations import report


def test_stylist_report_grain_date_attributes_and_same_item_workers(db, dd_seed, report):
    s = dd_seed
    item = s.item(s.order(date(2026, 8, 1)), qty=10)
    first = report(item, datetime(2026, 9, 1), qty=2, process="做发型")
    second = report(item, datetime(2026, 9, 30, 23, 59, 59), qty=3, process="做发型")
    second.reported_by_user_id = s.users[1].id
    report(item, datetime(2026, 9, 4), qty=1, process="做发型")
    report(item, datetime(2026, 10, 1), qty=9, process="做发型")
    report(item, datetime(2026, 9, 5), qty=99, process="做发型", revoked=1)
    report(item, datetime(2026, 9, 5), qty=99, process="入库")
    report(s.item(s.order(customer=s.customers[1])), datetime(2026, 9, 2), qty=99, process="做发型")
    for status in (0, 4, 5, 6):
        report(s.item(s.order(status=status)), datetime(2026, 9, 2), qty=99, process="做发型")
    report(s.item(s.order(deleted=1)), datetime(2026, 9, 2), qty=99, process="做发型")
    report(item, datetime(2026, 8, 31, 23, 59, 59), qty=4, process="做发型")
    result = build_analysis(db, s.actor, s.request())
    styling = result["stylists"]
    assert styling["summary"] == {"quantity": 6, "item_count": 1, "order_count": 1, "report_count": 3, "active_days": 3, "stylist_count": 2}
    assert sorted(row["quantity"] for row in styling["people"]) == [3, 3]
    assert sum(row["item_count"] for row in styling["people"]) == 2
    assert styling["details"][0]["product_name"] == "Historical lace"
    assert styling["products"][0]["craft"] == "lace"
    assert sum(row["quantity"] for row in styling["dimensions"]["length"]) == 6
    assert sum(row["quantity"] for row in styling["trend"]) == 6
    assert next(row for row in styling["people"] if row["user_id"] == s.users[0].id)["previous_quantity"] == 4
    assert build_analysis(db, s.actor, s.request(filters={"color": ["red"]}))["stylists"]["summary"]["quantity"] == 0
    saved = run_service.create_run(db, scope.live_actor(db, s.actor), s.request())
    rows = run_service.rows(db, scope.live_actor(db, s.actor), saved["meta"]["run_id"], kind="stylist_reports", stylist_id=s.users[1].id, sort_field="domestic_no", sort_order="desc")
    assert rows["total"] == 1 and rows["items"][0]["id"] == second.id
    first.reported_by_user_id = s.users[1].id
    db.flush()
    with pytest.raises(HTTPException) as error:
        run_service.rows(db, scope.live_actor(db, s.actor), saved["meta"]["run_id"], kind="stylist_reports")
    assert error.value.status_code == 409


def test_stylist_production_scope_and_revocation(db, dd_seed, report):
    s = dd_seed
    order = s.order(kind="production")
    order.customer_id = None
    log = report(s.item(order), datetime(2026, 9, 10), process="做发型")
    s.grant("domestic_decision:read_all")
    query = s.request(scope="all")
    assert build_analysis(db, s.actor, query)["stylists"]["summary"]["quantity"] == 0
    s.grant("domestic:read_all")
    assert build_analysis(db, s.actor, query)["stylists"]["summary"]["quantity"] == 1
    assert build_analysis(db, s.actor, s.request(scope="all", customer_ids=[s.customers[0].id]))["stylists"]["summary"]["quantity"] == 0
    log.revoked = 1
    db.flush()
    assert build_analysis(db, s.actor, query)["stylists"]["summary"]["quantity"] == 0
