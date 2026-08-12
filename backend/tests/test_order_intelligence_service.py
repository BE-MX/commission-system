from datetime import date

from app.order_intelligence import service


def order(
    order_id: str,
    company_id: str,
    account_date: date,
    amount: float,
    new_deal: str = "否",
    first_return: str = "否",
):
    return {
        "order_id": order_id,
        "company_id": company_id,
        "account_date": account_date,
        "amount_usd": amount,
        "new_deal": new_deal,
        "first_return": first_return,
        "country": "美国",
        "company_name": f"客户{company_id}",
        "user_id": "U1",
        "user_name": "业务员",
        "team": "团队一",
    }


def test_classify_source_prioritizes_owned_social_and_referral():
    assert service.classify_source("Ins开发，阿里巴巴") == "social_owned"
    assert service.classify_source("阿里询盘，TM咨询") == "alibaba_inquiry"
    assert service.classify_source("Ins分配") == "social_assigned"
    assert service.classify_source("开发客户熟人介绍，阿里巴巴") == "referral"
    assert service.classify_source("") == "unknown"


def test_aggregate_deduplicates_customer_counts_and_keeps_order_amount():
    rows = [
        order("1", "A", date(2026, 1, 1), 100, "是"),
        order("2", "A", date(2026, 2, 1), 200, "否", "是"),
        order("3", "B", date(2026, 2, 2), -10, "是"),
    ]
    result = service._aggregate(rows)
    assert result["orders"] == 3
    assert result["customers"] == 2
    assert result["new_sign_customers"] == 2
    assert result["repeat_customers"] == 1
    assert result["first_return_customers"] == 1
    assert result["amount_usd"] == 290
    assert result["non_positive_orders"] == 1


def test_customer_cycle_uses_recent_interval_median_and_marks_overdue():
    rows = [
        order("1", "A", date(2026, 1, 1), 100),
        order("2", "A", date(2026, 1, 31), 100),
        order("3", "A", date(2026, 3, 2), 100),
    ]
    result = service._customer_cycles(rows, date(2026, 4, 15))["A"]
    assert result["typical_cycle_days"] == 30
    assert result["expected_order_date"] == date(2026, 4, 1)
    assert result["overdue_days"] == 14
    assert result["risk_status"] == "overdue"


def test_customer_cycle_uses_peer_fallback_for_one_order_customer():
    rows = [order("1", "A", date(2026, 1, 1), 100)]
    result = service._customer_cycles(rows, date(2026, 4, 15))["A"]
    assert result["typical_cycle_days"] == 90
    assert result["cycle_source"] == "global_peer"
    assert result["cycle_evidence"] == "low"
    assert result["risk_status"] == "overdue"


def test_customer_cycle_prefers_country_peer_for_one_order_customer():
    rows = [
        order("1", "A", date(2026, 1, 1), 100),
        order("2", "B", date(2026, 1, 1), 100),
        order("3", "B", date(2026, 2, 10), 100),
    ]
    result = service._customer_cycles(rows, date(2026, 4, 15))["A"]
    assert result["typical_cycle_days"] == 40
    assert result["cycle_source"] == "country_peer"


def test_forecast_requires_three_months_and_caps_growth():
    short = [order("1", "A", date(2026, 1, 1), 100)]
    assert service._forecast_next_month(short) == (None, "insufficient_data")
    rows = [
        order("1", "A", date(2026, 1, 1), 100),
        order("2", "A", date(2026, 2, 1), 200),
        order("3", "A", date(2026, 3, 1), 1000),
    ]
    value, method = service._forecast_next_month(rows)
    assert value == 875.0
    assert method == "weighted_3m_trend"


def test_marketing_advice_never_recommends_scaling_low_sample():
    result = service._marketing_advice({
        "customers": 4,
        "top_source_code": "social_owned",
        "top_models": [{"name": "Genius Weft"}],
        "top_colors": [{"name": "#1B"}],
    })
    assert result["channel"] == "small_test"
    assert "不宜放大" in result["title"]


def test_top_attributes_exposes_equal_window_quantity_change():
    current = [{"model": "A", "quantity": 15}, {"model": "B", "quantity": 4}]
    previous = [{"model": "A", "quantity": 10}]
    result = service._top_attributes(current, "model", previous_rows=previous)
    assert result[0] == {
        "name": "A", "quantity": 15, "previous_quantity": 10, "quantity_growth": 50.0,
    }
    assert result[1]["quantity_growth"] is None
