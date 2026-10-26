"""统计口径单元测试：边界、工作日进度、四指标聚合与人工裁定优先。"""
from datetime import date
from decimal import Decimal

import pytest

from app.perf_goal import statistics as stats


def test_period_bounds_and_prev():
    assert stats.period_bounds("year", 2026) == (date(2026, 1, 1), date(2026, 12, 31))
    assert stats.period_bounds("quarter", 2026, 2) == (date(2026, 4, 1), date(2026, 6, 30))
    assert stats.period_bounds("month", 2026, 2, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert stats.prev_period("year", 2026, None, None) == (2025, None, None)
    assert stats.prev_period("quarter", 2026, 1, None) == (2025, 4, None)
    assert stats.prev_period("month", 2026, 1, 1) == (2025, 4, 12)
    with pytest.raises(ValueError):
        stats.period_bounds("quarter", 2026, None)
    with pytest.raises(ValueError):
        stats.period_bounds("week", 2026)


def test_workday_progress():
    # 2026-01-01 是周四；01-01~01-07 含 5 个工作日
    assert stats.workdays_between(date(2026, 1, 1), date(2026, 1, 7)) == 5
    assert stats.workdays_between(date(2026, 1, 3), date(2026, 1, 4)) == 0
    assert stats.workdays_between(date(2026, 1, 8), date(2026, 1, 1)) == 0
    start, end = date(2026, 1, 1), date(2026, 1, 31)
    total = stats.workdays_between(start, end)
    assert total == 22
    assert stats.workday_time_progress(start, end, date(2025, 12, 31)) == 0.0
    assert stats.workday_time_progress(start, end, date(2026, 2, 1)) == 1.0
    mid = stats.workday_time_progress(start, end, date(2026, 1, 15))
    assert mid == round(11 / 22, 4)


def test_rate_delta_status_projection():
    assert stats.rate_of(Decimal("50"), Decimal("200")) == 0.25
    assert stats.rate_of(Decimal("50"), None) is None
    assert stats.rate_of(Decimal("50"), Decimal("0")) is None
    assert stats.delta_pp(0.25, 0.5) == -25.0
    assert stats.delta_pp(None, 0.5) is None
    assert stats.status_for(None, None) == "no_target"
    assert stats.status_for(1.01, 50) == "completed"
    assert stats.status_for(0.5, -4.9) == "on_track"
    assert stats.status_for(0.4, -10) == "lagging"
    assert stats.status_for(0.2, -20.0) == "critical"
    assert stats.projected_rate(Decimal("100"), Decimal("400"), 10, 30) == 1.0
    assert stats.projected_rate(Decimal("50"), Decimal("400"), 10, 30) == 0.5
    assert stats.projected_rate(Decimal("50"), None, 10, 30) is None
    assert stats.projected_rate(Decimal("50"), Decimal("400"), 0, 30) is None


def _fetch(db, okki_ids, start, end, decisions=None):
    return stats.fetch_order_facts(db, okki_ids, start, end, decisions)


def test_four_metrics_and_attribution(db, perf):
    facts, issues = _fetch(db, ["90001", "90002", "90003"], date(2026, 1, 1), date(2026, 12, 31))
    totals = stats.aggregate(facts)
    u1 = stats.owner_total(totals, "90001")
    # GMV 含 pending 订单；取消单与个人 trail 单被口径排除
    assert u1["gmv"] == Decimal("1500.00")
    assert u1["new_sign"] == 1 and u1["repeat_customers"] == 1 and u1["repeat_amount"] == Decimal("500.00")
    u2 = stats.owner_total(totals, "90002")
    # 1004 无新成交标记：GMV 保留，新签/复购均不计
    assert u2["gmv"] == Decimal("1100.00")
    assert u2["new_sign"] == 1 and u2["repeat_customers"] == 0 and u2["repeat_amount"] == Decimal("0.00")
    u3 = stats.owner_total(totals, "90003")
    # 复购归下单业务员
    assert u3["repeat_customers"] == 1 and u3["repeat_amount"] == Decimal("2000.00") and u3["new_sign"] == 0
    assert any("1004" in issue for issue in issues)
    assert all(f["order_id"] not in ("1007", "1008") for f in facts)


def test_manual_decision_overrides_mark(db, perf):
    # 1004 无新成交标记（默认 pending），人工裁定为 repeat 后计入复购；裁定优先于空标记
    decisions = {"order_decisions": [
        {"order_id": "1004", "order_no": "NO4", "company_id": "5003", "owner_id": "90002",
         "account_date": "2026-03-05", "role": "repeat", "reason": "人工确认为老客复购"},
    ]}
    facts, issues = _fetch(db, ["90002"], date(2026, 1, 1), date(2026, 12, 31), decisions)
    totals = stats.aggregate(facts)
    u2 = stats.owner_total(totals, "90002")
    assert u2["new_sign"] == 1 and u2["repeat_customers"] == 1
    assert u2["repeat_amount"] == Decimal("300.00")
    assert u2["gmv"] == Decimal("1100.00")
    decided = next(f for f in facts if f["order_id"] == "1004")
    assert decided["role"] == "repeat" and "manual_decision" in decided["flags"]
    assert issues == []


def test_pending_decision_keeps_gmv_only(db, perf):
    decisions = {"order_decisions": [
        {"order_id": "1004", "order_no": "NO-DRIFTED", "company_id": "5003", "owner_id": "90002",
         "account_date": "2026-03-05", "role": "repeat", "reason": "订单号漂移"},
    ]}
    facts, issues = _fetch(db, ["90002"], date(2026, 1, 1), date(2026, 12, 31), decisions)
    totals = stats.aggregate(facts)
    u2 = stats.owner_total(totals, "90002")
    assert u2["gmv"] == Decimal("1100.00")
    assert u2["repeat_customers"] == 0
    assert any("不一致" in issue or "冲突" in issue for issue in issues)
