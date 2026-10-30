from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import text

from app.sales_return.models import ReturnEffect
from app.sales_return.gmv import adjustments, breakdown
from app.dingtalk.gmv_daily_service import build_report, calculate_report, load_valid_orders
from app.perf_goal.statistics import fetch_order_facts, aggregate, owner_total
from app.perf_goal.trend import _count_between, _amount_between
from app.battle_report.statistics import source_orders, summarize
from app.battle_report.award_statistics import calculate
from app.festival.service import get_gmv_total


def effect(db, rid, amount="-200", owner="old-A", day=date(2026, 10, 1), role="repeat", kind="activate", eligible=1):
    row = ReturnEffect(return_id=rid, effect_kind=kind, order_id=f"old-{rid}", owner_okki_user_id=owner,
                       customer_id=f"customer-{rid}", currency="USD", amount=amount, amount_usd=amount,
                       effective_date=day, gmv_eligible=eligible, order_role=role,
                       departments=[{"department_id": 1, "name": "Original team", "rate": 100}],
                       snapshot={"order_no": f"OLD-{rid}", "customer_name": "Old customer"})
    db.add(row)
    db.flush()
    return row


def test_cross_year_adjustments_without_current_orders_and_counts(db):
    effect(db, 1)
    effect(db, 2, amount="-50", eligible=0)
    facts, issues = fetch_order_facts(db, ["old-A"], date(2026, 10, 1), date(2026, 10, 31))
    assert not issues and len(facts) == 1
    assert facts[0]["source_type"] == "sales_return"
    totals = owner_total(aggregate(facts), "old-A")
    assert totals == {"gmv": Decimal("-200"), "new_sign": 0, "repeat_customers": 0, "repeat_amount": Decimal("-200")}
    assert _count_between(facts, "old-A", "repeat", date(2026, 10, 1), date(2026, 10, 31)) == 0
    assert _amount_between(facts, "old-A", None, date(2026, 10, 1), date(2026, 10, 31)) == -200
    assert adjustments(db, date(2025, 1, 1), date(2025, 12, 31)) == []


def test_daily_net_negative_archived_owner_department_and_reversal(db):
    effect(db, 1, owner="archived")
    facts = load_valid_orders(db, date(2026, 10, 1))
    config = {"teams": [{"department_id": 1, "name": "Original team", "captain_okki_user_id": "captain", "members": []}]}
    report = calculate_report(date(2026, 10, 1), config, facts)
    assert report["company_total_gmv"] == Decimal("-200")
    assert report["company_sales_gmv"] == 0 and report["company_return_adjustment_gmv"] == -200
    assert report["teams"][0]["total_gmv"] == -200
    assert report["teams"][0]["members"][0]["okki_user_id"] == "archived"
    assert report["anomalies"]
    effect(db, 1, amount="200", owner="archived", day=date(2026, 11, 1), kind="reverse")
    assert breakdown(adjustments(db, date(2026, 10, 1), date(2026, 11, 30)))["net_gmv"] == 0


def test_battle_report_adjustment_is_not_an_order(db):
    effect(db, 1)
    member = SimpleNamespace(id=1, okki_user_id="old-A", user_name="A", team="Original", target_usd=100,
                             ark_user_id=1, is_captain=False)
    report = SimpleNamespace(start_date=date(2026, 10, 1), end_date=date(2026, 10, 31), award_rules={})
    rows, issues = source_orders(db, report, [member], datetime(2026, 10, 30))
    summary = summarize([member], rows, issues)
    assert summary["gmv"] == "-200.00" and summary["order_count"] == 0
    assert summary["progress_percent"] == -200
    assert summary["adjustment_count"] == 1


def test_award_amounts_reduce_without_new_customer_or_repeat_count(db):
    effect(db, 1, role="new_sign")
    effect(db, 2, amount="-70", role="repeat")
    facts = adjustments(db, date(2026, 10, 1), date(2026, 10, 31))
    member = SimpleNamespace(id=1, okki_user_id="old-A", user_name="A", team="Original", ark_user_id=1, is_captain=False)
    report = SimpleNamespace(start_date=date(2026, 10, 1), end_date=date(2026, 10, 31), award_rules={}, award_kind="new_sign_pk")
    result = calculate(report, [member], facts, datetime(2026, 10, 30))
    person = result["people"][0]
    assert person["gmv"] == "-270.00"
    assert person["new_amount"] == "-200.00"
    assert person["repeat_amount"] == "-70.00"
    assert person["new_count"] == person["repeat_count"] == person["repeat_orders"] == 0


def test_festival_company_total_keeps_archived_adjustment_without_roster(db):
    db.execute(text("CREATE TABLE lsordertest.user_rel_team (user_id TEXT, is_active INTEGER)"))
    effect(db, 1, owner="archived")
    # The active roster query has project-specific archived attributes; isolate
    # that unrelated mirror shape while exercising actual persisted effects.
    from unittest.mock import patch
    with patch("app.festival.service._active_roster_filter", return_value=""):
        assert get_gmv_total(db, "2026-10-01", "2026-10-31", source="okki") == -200


def test_performance_team_refund_uses_original_department_after_owner_transfer(db):
    from app.perf_goal.trend import _facts, _historical_people
    from app.perf_goal.statistics import sum_totals
    effect(db, 1, owner="transferred")
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    old_team_people = [{"okki_user_id": "remaining", "user_id": 1, "name": "Remaining"}]
    old_team_people = _historical_people(db, old_team_people, {}, "team", start, end, 1)
    assert old_team_people[-1]["historical_return_owner"]
    old_facts, _ = _facts(db, old_team_people, start, end, 1)
    assert sum_totals(aggregate(old_facts), [p["okki_user_id"] for p in old_team_people])["gmv"] == -200
    new_team_people = [{"okki_user_id": "transferred", "user_id": 2, "name": "Transferred"}]
    new_facts, _ = _facts(db, new_team_people, start, end, 2)
    assert sum_totals(aggregate(new_facts), ["transferred"])["gmv"] == 0
