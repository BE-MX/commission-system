"""Signed ledger bridge, actual cash recharges, and maturity boundaries."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from fastapi import HTTPException

from app.domestic.models import DomesticCustomerLedger, DomesticCustomerRequest
from app.domestic_decision.analytics import build_analysis, filter_options
from app.domestic_decision.models import DecisionConfig
from app.domestic_decision.finance import recharge_cohorts
from tests.test_domestic_decision_analytics import dd_seed


@pytest.fixture
def ledger_seed(db, dd_seed):
    s = dd_seed
    s.grant("domestic_decision_finance:read")
    sequence = [0]
    def entry(kind, amount, before, after, when=datetime(2026, 9, 10, 12), customer=None, order_id=None):
        sequence[0] += 1
        row = DomesticCustomerLedger(customer_id=(customer or s.customers[0]).id, transaction_type=kind, amount=amount, balance_before=before, balance_after=after, created_at=when, created_by=s.users[1].id, business_key=f"ddentry{sequence[0]}", order_id=order_id)
        db.add(row)
        db.flush()
        return row
    s.entry = entry
    def request(amount=5000, status="pending", when=datetime(2026, 9, 12), customer=None):
        sequence[0] += 1
        row = DomesticCustomerRequest(customer_id=(customer or s.customers[0]).id, request_type="recharge", amount=amount, status=status, request_id=f"ddrequest{sequence[0]}", business_key=f"ddrequestkey{sequence[0]}", created_by=s.users[0].id, created_at=when, voucher_path="SENSITIVE_BANK_VOUCHER", remark="SENSITIVE_REMARK")
        db.add(row)
        db.flush()
        return row
    s.fund_request = request
    return s


def test_a01_a02_recharge_never_multiplies_orders(db, ledger_seed):
    s = ledger_seed
    order = s.order()
    s.item(order, qty=2, price=1000)
    s.item(order, qty=3, price=800)
    s.entry("recharge", 5000, 1000, 6000)
    s.entry("recharge", 2000, 6000, 8000)
    result = build_analysis(db, s.actor, s.request())
    assert result["summary"]["amount"] == 4400
    assert result["summary"]["quantity"] == 5
    assert result["finance"]["summary"]["recharge_amount"] == 7000
    assert result["finance"]["summary"]["recharge_count"] == 2


def test_a05_exact_bridge_signed_adjustment_refund(db, ledger_seed):
    s = ledger_seed
    for kind, amount, before, after in [("recharge", 5000, 1000, 6000), ("order_charge", -3000, 6000, 3000), ("order_adjustment", -200, 3000, 2800), ("order_refund", 300, 2800, 3100), ("adjust", -100, 3100, 3000)]:
        s.entry(kind, amount, before, after)
    result = build_analysis(db, s.actor, s.request())
    finance = result["finance"]
    assert finance["customers"][0]["opening_balance"] == 1000
    assert finance["customers"][0]["closing_balance"] == 3000
    assert finance["summary"]["recharge_amount"] == 5000
    assert finance["summary"]["net_order_deduction"] == 2900
    assert finance["customers"][0]["bridge_difference"] == 0
    assert finance["customers"][0]["reliable"]


def test_a06_credit_debt_positive_balance_separate(db, ledger_seed):
    s = ledger_seed
    s.customers[0].settle_mode = "credit"
    s.entry("recharge", 1500, -2000, -500)
    result = build_analysis(db, s.actor, s.request())
    row = result["finance"]["customers"][0]
    assert row["opening_balance"] == -2000
    assert row["closing_balance"] == -500
    assert row["positive_balance"] == 0
    assert row["debt"] == 500
    assert row["debt_improvement"] == 1500
    assert result["finance"]["summary"]["recharge_amount"] == 1500
    assert all(insight["requires_finance"] for insight in result["insights"] if insight["rule_key"] == "credit_account_check")


def test_a07_a08_a22_actual_recharge_only_pending_suppression_safe_evidence(db, ledger_seed):
    s = ledger_seed
    s.entry("init", 5000, 0, 5000)
    s.entry("order_refund", 500, 5000, 5500)
    s.entry("level_adjust", 0, 5500, 5500)
    s.entry("recharge", 0, 5500, 5500)
    s.fund_request(status="pending")
    s.fund_request(status="rejected")
    s.fund_request(status="approved")
    result = build_analysis(db, s.actor, s.request())
    assert result["finance"]["summary"]["recharge_amount"] == 0
    assert result["finance"]["summary"]["recharge_count"] == 0
    assert result["finance"]["summary"]["pending_recharge_amount"] == 5000
    assert "SENSITIVE" not in json.dumps(result)
    assert "voucher_path" not in json.dumps(result)
    assert any(r["rule_key"] == "pending_recharge_review" and r["requires_finance"] for r in result["insights"])
    assert not any(r["rule_key"] == "recharge_required" for r in result["insights"])


def test_a23_beijing_naive_inclusive_days_exclusive_next_day(db, ledger_seed, monkeypatch):
    s = ledger_seed
    monkeypatch.setattr("app.domestic_decision.finance.beijing_now", lambda: datetime(2026, 10, 8, 0, 10))
    s.entry("recharge", 100, 10, 110, datetime(2026, 8, 31, 23, 59, 59))
    s.entry("recharge", 200, 110, 310, datetime(2026, 9, 1, 0, 0))
    s.entry("recharge", 300, 310, 610, datetime(2026, 9, 30, 23, 59, 59))
    s.entry("recharge", 400, 610, 1010, datetime(2026, 10, 1, 0, 0))
    s.customers[0].balance = 1010
    result = build_analysis(db, s.actor, s.request())
    row = result["finance"]["customers"][0]
    assert row["opening_balance"] == 110
    assert row["closing_balance"] == 610
    assert row["current_reconciliation_difference"] is None
    assert result["finance"]["summary"]["recharge_amount"] == 500


def test_a24_unknown_opening_does_not_use_current_future_balance(db, ledger_seed):
    ledger_seed.customers[0].balance = 10000
    result = build_analysis(db, ledger_seed.actor, ledger_seed.request())
    row = result["finance"]["customers"][0]
    assert row["opening_balance"] is None
    assert row["closing_balance"] is None
    assert not row["reliable"]
    assert result["finance"]["summary"]["unknown_balance_customer_count"] == 1


def test_continuity_and_current_reconciliation_only_today(db, ledger_seed, monkeypatch):
    s = ledger_seed
    s.entry("recharge", 100, 0, 100)
    s.entry("recharge", 100, 200, 300)
    result = build_analysis(db, s.actor, s.request())
    assert not result["finance"]["customers"][0]["reliable"]
    assert any(r["type"] == "continuity" for r in result["finance"]["anomalies"])
    monkeypatch.setattr("app.domestic_decision.finance.beijing_today", lambda: date(2026, 9, 30))
    monkeypatch.setattr("app.domestic_decision.finance.beijing_now", lambda: datetime(2026, 9, 30, 12))
    result = build_analysis(db, s.actor, s.request())
    assert result["finance"]["customers"][0]["current_reconciliation_difference"] == -300


def test_product_filters_do_not_silently_narrow_finance(db, ledger_seed):
    s = ledger_seed
    s.entry("recharge", 5000, 0, 5000)
    request = s.request(filters={"color": ["NEVER"]})
    result = build_analysis(db, s.actor, request)
    assert result["summary"]["amount"] == 0
    assert result["finance"]["summary"]["recharge_amount"] == 5000
    result = build_analysis(db, s.actor, request.model_copy(update={"finance_related_customers": True}))
    assert result["finance"]["summary"]["recharge_amount"] == 0


def test_finance_permission_required_for_filters_and_profile_fields(db, dd_seed):
    s = dd_seed
    for request in [s.request(filters={"settle_mode": ["prepay"]}), s.request(filters={"membership_level": ["silver"]}), s.request(finance_related_customers=True), s.request(dimensions=["settle_mode"])]:
        with pytest.raises(HTTPException) as error:
            build_analysis(db, s.actor, request)
        assert error.value.status_code == 403
    result = build_analysis(db, s.actor, s.request())
    assert "settle_mode" not in result["customers"][0]
    assert "membership_level" not in result["customers"][0]
    options = filter_options(db, s.actor)
    assert "settle_mode" not in options["dimensions"]
    assert "membership_level" not in options["dimensions"]


def test_a30_month_anchors_and_customer_anchors_separate(db, ledger_seed):
    s = ledger_seed
    entries = [s.entry("recharge", 100, 0, 100, datetime(2026, 7, 10)), s.entry("recharge", 100, 100, 200, datetime(2026, 7, 20)), s.entry("recharge", 100, 200, 300, datetime(2026, 8, 1))]
    orders = [s.order(date(2026, 7, 25), total=1000), s.order(date(2026, 8, 8), total=1000)]
    result = recharge_cohorts(entries, orders, date(2026, 9, 30))
    assert len(result["monthly"]) == 2
    assert sum(r["observations"][1]["mature_count"] for r in result["monthly"]) == 2
    assert result["period_customers"][1]["mature_count"] == 1
    assert result["period_customers"][1]["purchase_count"] == 1


def test_monthly_anchor_uses_first_in_whole_month_not_first_after_query_start(db, ledger_seed):
    s = ledger_seed
    s.entry("recharge", 100, 0, 100, datetime(2026, 7, 1))
    s.entry("recharge", 100, 100, 200, datetime(2026, 7, 20))
    s.order(date(2026, 7, 10), total=1000)
    result = build_analysis(db, s.actor, s.request(start_date="2026-07-15", end_date="2026-08-31"))
    cohorts = result["finance"]["cohorts"]
    assert cohorts["monthly"][0]["observations"][1]["purchase_count"] == 1
    assert cohorts["period_customers"][1]["purchase_count"] == 0
    assert result["finance"]["summary"]["recharge_amount"] == 100


def test_prepaid_coverage_requires_verified_history_and_pending_suppresses(db, ledger_seed):
    s = ledger_seed
    db.add(DecisionConfig(key="coverage_start", value="2025-01-01"))
    db.flush()
    s.entry("init", 6100, 0, 6100, datetime(2026, 6, 1))
    balance = 6100
    for day in (date(2026, 7, 10), date(2026, 7, 20), date(2026, 8, 1), date(2026, 8, 10)):
        order = s.order(day, total=1500)
        s.item(order, price=1500)
        s.entry("order_charge", -1500, balance, balance - 1500, datetime.combine(day, datetime.min.time()), order_id=order.id)
        balance -= 1500
    result = build_analysis(db, s.actor, s.request())
    row = result["finance"]["customers"][0]
    assert row["coverage_status"] == "available"
    assert row["coverage_days"] == 1.5
    assert any(insight["rule_key"] == "low_balance_observation" for insight in result["insights"])
    s.fund_request(amount=5000)
    result = build_analysis(db, s.actor, s.request())
    assert not any(insight["rule_key"] == "low_balance_observation" for insight in result["insights"])
    assert any(insight["rule_key"] == "pending_recharge_review" for insight in result["insights"])


def test_credit_coverage_never_predicted_and_unknown_history_degrades(db, ledger_seed):
    s = ledger_seed
    s.customers[0].settle_mode = "credit"
    s.entry("recharge", 100, -200, -100)
    row = build_analysis(db, s.actor, s.request())["finance"]["customers"][0]
    assert row["coverage_days"] is None
    assert row["coverage_status"] == "not_applicable_credit"


def test_recharge_waiting_day_grain_and_review_duration(db, ledger_seed):
    s = ledger_seed
    s.entry("recharge", 100, 0, 100, datetime(2026, 9, 10, 14))
    s.order(date(2026, 9, 12), total=1000)
    request = s.fund_request(status="approved", when=datetime(2026, 9, 10, 13))
    request.reviewed_at = datetime(2026, 9, 10, 15)
    db.flush()
    result = build_analysis(db, s.actor, s.request())
    assert result["finance"]["recharge_purchase_waiting"][0]["first_purchase_wait_days"] == 2
    assert result["finance"]["review_metrics"]["median_review_seconds"] == 7200
    s.order(date(2026, 9, 10), total=1000)
    result = build_analysis(db, s.actor, s.request())
    assert result["finance"]["recharge_purchase_waiting"][0]["first_purchase_wait_days"] is None
    assert result["finance"]["recharge_purchase_waiting"][0]["status"] == "same_day_ordering_unknown"


def test_credit_debt_growth_uses_three_recorded_complete_months(db, ledger_seed):
    s = ledger_seed
    s.customers[0].settle_mode = "credit"
    s.entry("order_charge", -100, 0, -100, datetime(2026, 7, 1))
    s.entry("order_charge", -100, -100, -200, datetime(2026, 8, 1))
    s.entry("order_charge", -100, -200, -300, datetime(2026, 9, 1))
    result = build_analysis(db, s.actor, s.request())
    assert [row["debt"] for row in result["finance"]["customers"][0]["monthly_balances"]] == [100, 200, 300]
    assert any(insight["rule_key"] == "credit_debt_growth" and insight["requires_finance"] for insight in result["insights"])
    assert len(result["evidence"]["history_ledger"]) == 2


@pytest.mark.parametrize("return_type", ["order_refund", "order_adjustment"])
def test_terminated_order_returns_suppress_coverage_prediction(db, ledger_seed, return_type):
    s = ledger_seed
    db.add(DecisionConfig(key="coverage_start", value="2025-01-01"))
    db.flush()
    s.entry("init", 100000, 0, 100000, datetime(2026, 6, 1))
    balance = 100000
    for day in (date(2026, 7, 10), date(2026, 7, 20), date(2026, 8, 1)):
        order = s.order(day, total=1000)
        s.item(order, price=1000)
        s.entry("order_charge", -1000, balance, balance - 1000, datetime.combine(day, datetime.min.time()), order_id=order.id)
        balance -= 1000
    terminated = s.order(date(2026, 8, 10), total=90000, status=4)
    s.entry("order_charge", -90000, balance, balance - 90000, datetime(2026, 8, 10), order_id=terminated.id)
    balance -= 90000
    s.entry(return_type, 90000, balance, balance + 90000, datetime(2026, 8, 11), order_id=terminated.id)
    result = build_analysis(db, s.actor, s.request())
    row = result["finance"]["customers"][0]
    assert row["coverage_purchase_days_90d"] == 3
    assert row["coverage_gross_deduction_90d"] == 3000
    assert row["coverage_returns_90d"] == 90000
    assert row["coverage_days"] is None
    assert row["coverage_status"] == "refund_adjustment_variation"
    assert not any(insight["rule_key"] == "low_balance_observation" for insight in result["insights"])


def test_unverifiable_order_deduction_does_not_make_prepaid_forecast(db, ledger_seed):
    s = ledger_seed
    db.add(DecisionConfig(key="coverage_start", value="2025-01-01"))
    db.flush()
    s.entry("init", 10000, 0, 10000, datetime(2026, 6, 1))
    balance = 10000
    for day in (date(2026, 7, 10), date(2026, 7, 20), date(2026, 8, 1)):
        order = s.order(day, total=1000)
        s.entry("order_charge", -1000, balance, balance - 1000, datetime.combine(day, datetime.min.time()), order_id=order.id)
        balance -= 1000
    s.entry("order_adjustment", -500, balance, balance - 500, datetime(2026, 8, 20), order_id=None)
    row = build_analysis(db, s.actor, s.request())["finance"]["customers"][0]
    assert row["coverage_purchase_days_90d"] == 3
    assert row["coverage_days"] is None
    assert row["coverage_status"] == "unverifiable_commercial_deduction_history"


def test_server_recommendations_are_claimable_rules_once_per_customer(db, dd_seed):
    from app.core.time import beijing_today
    from app.domestic_decision import run_service, state_service
    from app.domestic_decision.profiles import customer_profile
    from app.domestic_decision.scope import live_actor
    from app.domestic_decision.state_schemas import ActionCreate
    s = dd_seed
    s.grant("domestic_decision_action:write")
    s.item(s.order(total=1000))
    actor = live_actor(db, s.actor)
    run = run_service.create_run(db, actor, s.request())
    recommendations = run["customers"][0]["recommendations"]
    for recommendation in recommendations:
        matching = [insight for insight in run["insights"] if insight["customer_id"] == s.customers[0].id and insight["rule_key"] == recommendation["rule_key"]]
        assert len(matching) == 1
        assert matching[0]["evidence_refs"] == recommendation["evidence_refs"]
        command = ActionCreate(run_id=run["meta"]["run_id"], customer_id=s.customers[0].id, rule_key=recommendation["rule_key"], request_key="recommendation-" + recommendation["rule_key"], due_date=beijing_today())
        first = state_service.create_action(db, actor, command)
        duplicate = state_service.create_action(db, actor, command.model_copy(update={"request_key": "repeat-" + recommendation["rule_key"]}))
        assert first["id"] == duplicate["id"]
    profile = customer_profile(db, actor, s.customers[0].id, s.request())
    assert {row["rule_key"] for row in profile["customer"]["recommendations"]}.issubset({row["rule_key"] for row in profile["insights"]})


@pytest.mark.parametrize("status,lifecycle", [(0, None), (1, "paused"), (1, "custom_no_contact")])
def test_inactive_contact_policy_suppresses_recommendation_actions(db, dd_seed, status, lifecycle):
    s = dd_seed
    s.customers[0].status = status
    s.customers[0].lifecycle_status = lifecycle
    db.add(DecisionConfig(key="inactive_lifecycle_statuses", value=["paused", "custom_no_contact"]))
    s.item(s.order(total=1000))
    db.flush()
    result = build_analysis(db, s.actor, s.request())
    assert result["customers"][0]["preferences"]["recent_180_days"]
    assert result["customers"][0]["recommendations"] == []
    assert not any(insight["rule_key"] in ("own_repeat_combination", "own_half_year_change") for insight in result["insights"])
