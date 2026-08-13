from datetime import date

import pytest

from app.order_intelligence import service
from app.order_intelligence.filtering import AnalysisFilters, group_countries, model_expression, order_sql


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
    assert result["repeat_orders"] == 1
    assert result["first_return_customers"] == 1
    assert result["amount_usd"] == 290
    assert result["non_positive_orders"] == 1


def test_monthly_trend_counts_first_return_customers_and_repeat_orders():
    rows = [
        order("1", "A", date(2026, 1, 1), 100, "是"),
        order("2", "A", date(2026, 2, 1), 200, "否", "是"),
        order("3", "A", date(2026, 2, 5), 300, "否", "否"),
        order("4", "B", date(2026, 2, 8), 400, "是", "否"),
    ]

    trend = service._monthly_trend(rows)

    assert trend[0]["new_sign_customers"] == 1
    assert trend[0]["first_return_customers"] == 0
    assert trend[1]["new_sign_customers"] == 1
    assert trend[1]["first_return_customers"] == 1
    assert trend[1]["repeat_orders"] == 2
    assert trend[1]["repeat_amount_usd"] == 500


def test_monthly_trend_fills_empty_months_with_zeroes():
    rows = [order("1", "A", date(2026, 1, 1), 100, "是")]

    trend = service._monthly_trend(rows, date(2026, 1, 1), date(2026, 3, 31))

    assert [row["month"] for row in trend] == ["2026-01", "2026-02", "2026-03"]
    assert trend[1]["orders"] == 0
    assert trend[1]["new_sign_customers"] == 0
    assert trend[1]["first_return_customers"] == 0
    assert trend[1]["repeat_orders"] == 0
    assert trend[1]["repeat_amount_usd"] == 0


def test_filtered_customer_cycles_uses_current_period_customer_set(monkeypatch):
    history = [
        order("1", "A", date(2025, 1, 1), 100),
        order("2", "B", date(2025, 2, 1), 200),
    ]
    monkeypatch.setattr(service, "_load_orders", lambda *_args, **_kwargs: history)

    cycles = service._filtered_customer_cycles(
        object(),
        service.AnalysisScope("all", None, None, True),
        date(2026, 1, 1),
        [order("3", "A", date(2026, 1, 1), 300)],
    )

    assert set(cycles) == {"A"}


def test_analysis_filters_validate_source_and_render_parameterized_order_sql():
    filters = AnalysisFilters.build(
        countries=["美国", "加拿大", "美国"],
        models=["B1天才发帘"],
        colors=["#1B"],
        sources=["alibaba_inquiry"],
    )
    params = {}

    clause = order_sql(filters, params, "lsordertest")

    assert filters.countries == ("美国", "加拿大")
    assert "EXISTS" in clause
    assert "`lsordertest`.okki_order_items" in clause
    assert "美国" not in clause
    assert params["filter_country_0"] == "美国"
    assert params["filter_model_0"] == "B1天才发帘"
    assert params["filter_color_0"] == "#1B"


def test_model_filter_expression_does_not_infer_model_from_product_name():
    expression = model_expression("oi", "p", fallback_name=False)

    assert "p.model" in expression
    assert "oi.product_model" in expression
    assert "product_name" not in expression


def test_country_tree_groups_actual_countries_and_keeps_unknown_values():
    groups = group_countries(["美国", "德国", "澳大利亚", "未知", "火星"])
    by_name = {group["label"]: group for group in groups}

    assert by_name["北美洲"]["children"] == [{"label": "美国", "value": "美国"}]
    assert by_name["欧洲"]["children"] == [{"label": "德国", "value": "德国"}]
    assert by_name["大洋洲"]["children"] == [{"label": "澳大利亚", "value": "澳大利亚"}]
    assert {item["value"] for item in by_name["其他"]["children"]} == {"未知", "火星"}


def test_analysis_filters_reject_invalid_source_and_excessive_values():
    with pytest.raises(ValueError, match="无效选项"):
        AnalysisFilters.build(sources=["made_up"])
    with pytest.raises(ValueError, match="最多选择"):
        AnalysisFilters.build(models=[f"M{index}" for index in range(101)])


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
