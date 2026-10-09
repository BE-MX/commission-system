"""Operational decision regressions on an isolated, synthetic database."""
from datetime import datetime, date, timezone, timedelta

import pytest

from tests.test_domestic_decision_analytics import dd_seed
from app.domestic.models import DomesticCustomer, DomesticCustomerLedger, DomesticItemProgress, DomesticReportLog
from app.production.models import Process, ProcessRoute
from app.domestic_decision.analytics import build_analysis
from app.domestic_decision import run_service, scope
from app.domestic_decision.models import DecisionRun, DecisionConfig
from app.domestic_decision.router import router
from app.core.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import ArkRolePermission
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def report(db, dd_seed):
    route = ProcessRoute(name="Decision operations")
    processes = [Process(name=name) for name in ("发货完成", "入库", "做发型", "毛坯出库")]
    db.add_all([route, *processes])
    db.flush()
    def add(item, stamp, qty=1, process="发货完成", revoked=0):
        proc = next(p for p in processes if p.name == process)
        progress = db.query(DomesticItemProgress).filter_by(item_id=item.id, process_id=proc.id).first()
        if progress is None:
            progress = DomesticItemProgress(item_id=item.id, route_id=route.id, process_id=proc.id, step_order=processes.index(proc) + 1)
            db.add(progress)
            db.flush()
        row = DomesticReportLog(item_id=item.id, progress_id=progress.id, process_id=proc.id, step_order=progress.step_order, report_qty=qty, reported_at=stamp, revoked=revoked, reported_by_user_id=dd_seed.users[0].id)
        db.add(row)
        db.flush()
        return row
    return add


def recharge(db, seed, customer, day, amount=1000, kind="recharge"):
    row = DomesticCustomerLedger(customer_id=customer.id, transaction_type=kind, amount=amount, balance_before=0, balance_after=amount, created_at=day, created_by=seed.users[0].id)
    db.add(row)
    db.flush()
    return row


def test_shipping_uses_report_date_quantity_and_current_valid_orders(db, dd_seed, report):
    s = dd_seed
    old = s.item(s.order(date(2026, 8, 1), total=1000), qty=10, price=100)
    report(old, datetime(2026, 9, 1), qty=2)
    report(old, datetime(2026, 9, 30, 23, 59, 59), qty=3)
    report(old, datetime(2026, 10, 1), qty=1)
    report(old, datetime(2026, 9, 5), qty=1, revoked=1)
    report(old, datetime(2026, 9, 5), qty=1, process="做发型")
    for status in (0, 4, 5, 6):
        report(s.item(s.order(status=status)), datetime(2026, 9, 10))
    report(s.item(s.order(deleted=1)), datetime(2026, 9, 10))
    report(s.item(s.order(kind="production"), price=0), datetime(2026, 9, 10))
    report(s.item(s.order(customer=s.customers[1])), datetime(2026, 9, 10))
    current = s.item(s.order(total=400), qty=4, price=100)
    report(current, datetime(2026, 10, 1), qty=4)
    result = build_analysis(db, s.actor, s.request())
    assert result["summary"]["business_order_amount"] == 400
    assert result["summary"]["shipped_amount"] == 500
    assert result["summary"]["shipped_quantity"] == 5
    assert result["summary"]["customer_count"] == 1
    assert sum(row["shipped_amount"] or 0 for row in result["trend"]) == 500
    assert len(result["evidence"]["reports"]) == 2
    assert result["comparison"]["summary"]["shipped_amount"] == 0
    assert result["products"][0]["shipped_quantity"] == 5
    filtered = build_analysis(db, s.actor, s.request(filters={"color": ["red"]}))
    assert filtered["summary"]["shipped_amount"] == 0


def test_report_revocation_and_edit_invalidate_data_version(db, dd_seed, report):
    line = dd_seed.item(dd_seed.order())
    log = report(line, datetime(2026, 9, 10))
    first = build_analysis(db, dd_seed.actor, dd_seed.request())
    log.report_qty = 2
    db.flush()
    second = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert second["meta"]["data_version"] != first["meta"]["data_version"]
    log.revoked = 1
    db.flush()
    third = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert third["meta"]["data_version"] != second["meta"]["data_version"]
    assert third["summary"]["shipped_amount"] == 0


def test_recharge_segments_historical_membership_and_discount_grain(db, dd_seed):
    s = dd_seed
    s.grant("domestic_decision_finance:read")
    other = DomesticCustomer(shop_name="No recharge", owner_user_id=s.users[0].id, created_by=s.users[0].id, settle_mode="credit")
    db.add(other)
    db.flush()
    recharge(db, s, s.customers[0], datetime(2026, 8, 1), 5000)
    recharge(db, s, s.customers[0], datetime(2026, 9, 1), 2000)
    recharge(db, s, s.customers[0], datetime(2026, 9, 30, 23, 59, 59), 1000)
    recharge(db, s, other, datetime(2026, 10, 1), 1000)
    recharge(db, s, other, datetime(2026, 9, 1), 300, "adjust")
    recharge(db, s, s.customers[1], datetime(2026, 9, 1), 90000)
    row = s.order(total=1600)
    line = s.item(row, qty=2, price=800)
    line.discount_amount = 200
    s.item(s.order(total=1000), price=1000)
    other_line = s.item(s.order(total=1000, customer=other), price=1000)
    other_line.labor_fee = 0
    db.flush()
    result = build_analysis(db, s.actor, s.request())
    assert result["summary"]["recharge_amount"] == 3000
    groups = {r["key"]: r for r in result["customer_segments"]["groups"]}
    assert groups["recharged"]["customer_count"] == 1
    assert groups["recharged"]["order_count"] == 2
    assert groups["recharged"]["amount"] == 2600
    assert groups["recharged"]["discount_amount"] == 400
    assert groups["non_recharged"]["customer_count"] == 1
    assert groups["non_recharged"]["order_count"] == 1
    other_row = next(r for r in result["customers"] if r["customer_id"] == other.id)
    assert other_row["recharge_behavior"] == "full_price_without_recharge"
    assert other_row["recharge_intent"] == "unconfirmed"
    filtered = build_analysis(db, s.actor, s.request(filters={"color": ["red"]}))
    assert filtered["summary"]["recharge_amount"] == 3000
    assert sum(r["order_count"] for r in filtered["customer_segments"]["groups"]) == 0


def test_no_finance_permission_does_not_expose_recharge_behavior(db, dd_seed):
    recharge(db, dd_seed, dd_seed.customers[0], datetime(2026, 9, 10))
    dd_seed.item(dd_seed.order())
    result = build_analysis(db, dd_seed.actor, dd_seed.request())
    assert result["summary"]["recharge_amount"] is None
    assert "customer_segments" not in result
    assert "recharge_behavior" not in result["customers"][0]


def test_store_retention_distinct_days_and_dormancy(db, dd_seed):
    s = dd_seed
    for day in (date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)):
        s.item(s.order(day))
    same = DomesticCustomer(shop_name="One buying day", owner_user_id=s.users[0].id, created_by=s.users[0].id)
    lost = DomesticCustomer(shop_name="Dormant", owner_user_id=s.users[0].id, created_by=s.users[0].id)
    db.add_all([same, lost])
    db.flush()
    for _ in range(3):
        s.order(customer=same)
    for day in (date(2026, 3, 1), date(2026, 3, 11), date(2026, 3, 21), date(2026, 4, 1)):
        s.order(day, customer=lost)
    result = build_analysis(db, s.actor, s.request())
    by_id = {r["customer_id"]: r for r in result["customers"]}
    assert by_id[s.customers[0].id]["retention_status"] == "sustained_repeat"
    assert by_id[same.id]["retention_status"] == "sample_accumulating"
    assert by_id[lost.id]["retention_status"] == "dormant"
    assert result["retention"]["summary"]["dormant"] == 1


def test_product_shipping_frequency_supply_and_unknown_profit(db, dd_seed, report):
    s = dd_seed
    other = DomesticCustomer(shop_name="Repeat peer", owner_user_id=s.users[0].id, created_by=s.users[0].id)
    db.add(other)
    db.flush()
    for i, day in enumerate((1, 10, 20)):
        line = s.item(s.order(date(2026, 8, 1 + i), customer=other if i == 1 else None), qty=2)
        report(line, datetime(2026, 9, day), qty=2)
    production = s.item(s.order(date(2026, 9, 1), kind="production"), qty=10, price=0)
    report(production, datetime(2026, 9, 6), qty=10, process="入库")
    result = build_analysis(db, s.actor, s.request())
    product = result["products"][0]
    assert product["demand_status"] == "steady_seller"
    assert product["shipping_days"] == 3
    assert product["shipping_customer_count"] == 2
    supply = result["production_operations"]["rows"][0]
    assert supply["production_received_quantity"] == 10
    assert supply["production_cycle_days"] == 5
    assert supply["supply_excess_quantity"] == 10
    assert product["gross_profit"] is None
    assert product["inventory_quantity"] is None
    assert product["profit_status"] == "missing_cost"
    report(s.item(s.order(date(2026, 8, 1)), color="red"), datetime(2026, 9, 10))
    changed = build_analysis(db, s.actor, s.request())
    assert any(row["demand_status"] == "occasional_shipping" for row in changed["products"])


def test_report_datetime_converts_offset_to_beijing_at_midnight():
    from app.domestic_decision.operations import report_evidence
    from types import SimpleNamespace
    log = SimpleNamespace(id=1, item_id=1, process_id=1, report_qty=2, reported_at=datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc), revoked=0)
    item = SimpleNamespace(id=1, order_id=1, unit_price=10)
    order = SimpleNamespace(customer_id=1)
    assert report_evidence(log, item, order, "发货完成")["reported_at"] == "2026-09-01T00:00:00"
    log.reported_at = datetime(2026, 9, 1, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert report_evidence(log, item, order, "发货完成")["amount"] == 20


def test_unassigned_production_requires_both_permissions_and_no_customer_narrowing(db, dd_seed, report):
    s = dd_seed
    order = s.order(date(2026, 9, 1), kind="production")
    order.customer_id = None
    item = s.item(order, qty=5, price=0)
    report(item, datetime(2026, 9, 5), qty=5, process="入库")
    s.grant("domestic_decision:read_all")
    query = s.request(scope="all")
    assert build_analysis(db, s.actor, query)["production_operations"]["rows"] == []
    s.grant("domestic:read_all")
    result = build_analysis(db, s.actor, query)
    assert result["production_operations"]["rows"][0]["production_received_quantity"] == 5
    assert result["meta"]["includes_unassigned_production"]
    narrowed = build_analysis(db, s.actor, s.request(scope="all", customer_ids=[s.customers[0].id]))
    assert not narrowed["meta"]["includes_unassigned_production"]
    assert narrowed["production_operations"]["rows"] == []
    actor = scope.live_actor(db, s.actor)
    saved = run_service.create_run(db, actor, query)
    db.query(ArkRolePermission).filter_by(permission_id=s.permissions["domestic:read_all"]).delete(synchronize_session=False)
    db.flush()
    with pytest.raises(HTTPException) as error:
        run_service.require_run(db, scope.live_actor(db, s.actor), saved["meta"]["run_id"])
    assert error.value.status_code == 403


def test_report_http_evidence_discount_and_snapshot_revocation(db, dd_seed, report):
    s = dd_seed
    line = s.item(s.order(), qty=2, price=900)
    line.discount_amount = 100
    log = report(line, datetime(2026, 9, 10))
    foreign_log = report(s.item(s.order(customer=s.customers[1])), datetime(2026, 9, 10))
    app = FastAPI()
    app.include_router(router, prefix="/api/domestic-decision")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: s.actor
    client = TestClient(app)
    result = client.post("/api/domestic-decision/analysis-runs", json=s.request().model_dump(mode="json"))
    assert result.status_code == 200
    run_id = result.json()["data"]["meta"]["run_id"]
    evidence = client.get(f"/api/domestic-decision/evidence/reports/{log.id}")
    assert evidence.status_code == 200
    assert evidence.json()["data"]["amount"] == 900
    assert client.get(f"/api/domestic-decision/evidence/reports/{foreign_log.id}").status_code == 404
    item = client.get(f"/api/domestic-decision/evidence/items/{line.id}").json()["data"]
    assert item["discount_amount"] == 100 and item["order_qty"] == 2
    rows_path = f"/api/domestic-decision/analysis-runs/{run_id}/rows"
    assert client.get(rows_path, params={"kind": "reports", "sort_field": "reported_at", "sort_order": "desc"}).json()["data"]["total"] == 1
    assert client.get(rows_path, params={"kind": "reports", "dimension": "craft", "value": "lace"}).status_code == 422
    log.revoked = 1
    db.flush()
    assert client.get(rows_path, params={"kind": "reports"}).status_code == 409


def test_multiple_final_styles_share_one_blank_supply_and_completion_is_full_quantity(db, dd_seed, report):
    s = dd_seed
    production = s.item(s.order(date(2026, 8, 25), kind="production"), qty=10, price=0)
    production.attrs_snapshot = {**production.attrs_snapshot, "hair_style_series": None}
    report(production, datetime(2026, 8, 28), qty=4, process="入库")
    report(production, datetime(2026, 9, 10), qty=6, process="入库")
    for style in ("straight", "curly"):
        item = s.item(s.order())
        item.attrs_snapshot = {**item.attrs_snapshot, "hair_style_series": style}
        report(item, datetime(2026, 9, 10), process="毛坯出库")
        report(item, datetime(2026, 9, 11))
    result = build_analysis(db, s.actor, s.request())
    assert len(result["products"]) == 2
    assert len(result["production_operations"]["rows"]) == 1
    supply = result["production_operations"]["rows"][0]
    assert supply["production_received_quantity"] == 6
    assert supply["blank_issued_quantity"] == 2
    assert supply["production_cycle_days"] == 16
    assert supply["production_wip_quantity"] == 0
    assert supply["supply_excess_quantity"] == 4
    assert supply["replenishment_status"] == "insufficient_sample"
    filtered = build_analysis(db, s.actor, s.request(filters={"hair_style_series": ["curly"]}))
    assert len(filtered["products"]) == 1
    assert filtered["production_operations"]["rows"][0]["production_received_quantity"] == 6


def test_aftersales_this_period_does_not_fake_sustained_commercial_repurchase(db, dd_seed):
    s = dd_seed
    db.add(DecisionConfig(key="aftersales_order_types", value=["remake"]))
    for day in (date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)):
        s.order(day)
    s.order(total=0, order_type="remake")
    result = build_analysis(db, s.actor, s.request())
    assert result["customers"][0]["retention_status"] != "sustained_repeat"


def test_related_funds_comparison_uses_each_period_matching_customers(db, dd_seed):
    s = dd_seed
    s.grant("domestic_decision_finance:read")
    s.item(s.order(date(2026, 8, 10)))
    recharge(db, s, s.customers[0], datetime(2026, 8, 5), 2000)
    result = build_analysis(db, s.actor, s.request(finance_related_customers=True))
    assert result["summary"]["recharge_amount"] == 0
    assert result["comparison"]["summary"]["recharge_amount"] == 2000


def test_old_metric_snapshot_requires_refresh(db, dd_seed):
    s = dd_seed
    saved = run_service.create_run(db, scope.live_actor(db, s.actor), s.request())
    row = db.get(DecisionRun, saved["meta"]["run_id"])
    row.result_json = {**row.result_json, "meta": {**row.result_json["meta"], "metric_version": "domestic-v1"}}
    db.flush()
    with pytest.raises(HTTPException) as error:
        run_service.require_run(db, scope.live_actor(db, s.actor), row.id)
    assert error.value.status_code == 409


def test_zero_and_aftersales_shipments_never_classified_as_steady_sellers(db, dd_seed, report):
    s = dd_seed
    db.add(DecisionConfig(key="aftersales_order_types", value=["remake"]))
    other = DomesticCustomer(shop_name="After sales", owner_user_id=s.users[0].id, created_by=s.users[0].id)
    db.add(other)
    db.flush()
    for i, day in enumerate((1, 10, 20)):
        line = s.item(s.order(date(2026, 8, 1 + i), total=1000, order_type="remake", customer=other if i == 1 else None))
        report(line, datetime(2026, 9, day))
    result = build_analysis(db, s.actor, s.request())
    assert result["summary"]["shipped_amount"] == 3000
    assert result["products"][0]["demand_status"] == "noncommercial_shipping"
    assert result["products"][0]["commercial_shipping_days"] == 0
