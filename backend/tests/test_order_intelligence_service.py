from datetime import date

import pytest

from app.order_intelligence import service
from app.order_intelligence.filtering import AnalysisFilters, group_countries, model_expression, order_sql
from app.order_intelligence.profile_analysis import analyze_customer_profiles, model_family, normalize_customer_nature


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
        "source_category": "alibaba_inquiry",
        "customer_nature": "沙龙\r",
    }


def product(order_id, company_id, model, size="18", color="#1B", quantity=10, new_deal="否"):
    return {
        "order_id": order_id,
        "company_id": company_id,
        "product_name": f"{model}/{size}/{color}/20g",
        "model": model,
        "filter_model": model,
        "size": size,
        "color": color,
        "quantity": quantity,
        "new_deal": new_deal,
    }


def test_classify_source_prioritizes_owned_social_and_referral():
    assert service.classify_source("Ins开发，阿里巴巴") == "social_owned"
    assert service.classify_source("阿里询盘，TM咨询") == "alibaba_inquiry"
    assert service.classify_source("Ins分配") == "social_assigned"
    assert service.classify_source("开发客户熟人介绍，阿里巴巴") == "referral"
    assert service.classify_source("") == "unknown"


@pytest.mark.parametrize("source_raw", [None, "", False, 0, [], {}])
def test_decorate_order_falls_back_to_customer_origin_for_empty_extracted_source(source_raw):
    row = service._decorate_order({
        "source_raw": source_raw,
        "origin_name": "阿里询盘",
        "new_deal": None,
        "first_return": None,
        "country_name": "",
        "amount_usd": None,
        "company_id": None,
        "user_id": None,
    })

    assert row["source_raw"] == "阿里询盘"
    assert row["source_category"] == "alibaba_inquiry"
    assert row["new_deal"] == ""
    assert row["first_return"] == ""
    assert row["country"] == "未知"
    assert row["amount_usd"] == 0


def test_decorate_order_preserves_extracted_business_flags_and_source():
    row = service._decorate_order({
        "source_raw": "Ins开发",
        "origin_name": "阿里询盘",
        "new_deal": "是",
        "first_return": "否",
        "country_name": "美国",
        "amount_usd": "12.50",
        "company_id": 123,
        "user_id": 456,
    })

    assert row["source_category"] == "social_owned"
    assert row["new_deal"] == "是"
    assert row["first_return"] == "否"
    assert row["country"] == "美国"
    assert row["amount_usd"] == 12.5
    assert row["company_id"] == "123"
    assert row["user_id"] == "456"


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


def test_profile_helpers_clean_nature_and_classify_only_explicit_b1_b3():
    assert normalize_customer_nature(" 沙龙\r\n") == "沙龙"
    assert normalize_customer_nature("无") == "未知"
    assert model_family([{"filter_model": "B1天才发帘"}]) == "B1"
    assert model_family([{"filter_model": "B1"}, {"filter_model": "B3天才发帘"}]) == "B1+B3"
    assert model_family([{"filter_model": "AB12"}]) == "其他/未知"


def test_order_loader_sources_customer_nature_from_trail_status_name():
    captured = {}

    class EmptyResult:
        def mappings(self):
            return []

    class FakeDb:
        def execute(self, statement, params):
            captured["sql"] = str(statement)
            captured["params"] = params
            return EmptyResult()

    result = service._load_orders(
        FakeDb(),
        service.AnalysisScope("all", None, None, True),
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    assert result == []
    assert "ci.trail_status_name customer_nature" in captured["sql"]
    select_list = captured["sql"].split("FROM `lsordertest`.okki_orders o", 1)[0]
    assert "               o.custom_fields," not in select_list
    assert "new_deal" in select_list
    assert "first_return" in select_list
    assert "source_raw" in select_list
    assert "NULLIF(NULLIF(JSON_UNQUOTE" in select_list


def test_product_loader_extracts_only_required_order_json_fields():
    captured = {}

    class EmptyResult:
        def mappings(self):
            return []

    class FakeDb:
        def execute(self, statement, params):
            captured["sql"] = str(statement)
            return EmptyResult()

    result = service._load_product_rows(
        FakeDb(),
        service.AnalysisScope("all", None, None, True),
        date(2026, 1, 1),
        date(2026, 1, 31),
    )

    assert result == []
    select_list = captured["sql"].split("FROM `lsordertest`.okki_orders o", 1)[0]
    assert "               o.custom_fields," not in select_list
    assert "JSON_UNQUOTE(JSON_EXTRACT(o.custom_fields" in captured["sql"]
    assert "new_deal" in captured["sql"]
    assert "source_raw" in captured["sql"]
    assert "NULLIF(NULLIF(JSON_UNQUOTE" in select_list


def test_profile_dimensions_split_country_source_nature_and_first_new_model():
    first = order("1", "A", date(2026, 1, 1), 100, "是")
    second = order("2", "B", date(2026, 1, 1), 100, "是")
    second.update({
        "country": "加拿大",
        "source_category": "social_owned",
        "customer_nature": "批发商",
    })
    products = [
        product("1", "A", "B1天才发帘", new_deal="是"),
        product("2", "B", "B3天才发帘", new_deal="是"),
    ]

    result = analyze_customer_profiles(
        [first, second],
        products,
        [first, second],
        products,
        date(2026, 1, 31),
        service.SOURCE_LABELS,
    )

    dimensions = {
        (item["country"], item["source_code"], item["customer_nature"], item["new_sign_model_family"])
        for item in result["items"]
    }
    assert dimensions == {
        ("美国", "alibaba_inquiry", "沙龙", "B1"),
        ("加拿大", "social_owned", "批发商", "B3"),
    }


def test_customer_profiles_compute_cycles_distributions_and_profile_alerts():
    orders = [
        order("1", "A", date(2026, 1, 1), 100, "是"),
        order("2", "A", date(2026, 1, 31), 150, "否", "是"),
        order("3", "A", date(2026, 3, 2), 200, "否"),
        order("4", "B", date(2026, 1, 1), 100, "是"),
        order("5", "B", date(2026, 3, 2), 200, "否", "是"),
    ]
    products = [
        product("1", "A", "B1天才发帘", "18", new_deal="是"),
        product("2", "A", "B3天才发帘", "20", quantity=20),
        product("3", "A", "B1天才发帘", "22", quantity=30),
        product("4", "B", "B1天才发帘", "18", new_deal="是"),
        product("5", "B", "B3天才发帘", "24", quantity=40),
    ]

    result = analyze_customer_profiles(
        orders,
        products,
        orders,
        products,
        date(2026, 5, 2),
        service.SOURCE_LABELS,
    )

    assert result["total"] == 1
    profile = result["items"][0]
    assert result["summary"] == {
        "active_customer_count": 2,
        "profile_count": 1,
        "customer_nature_coverage": 100.0,
        "new_sign_b1_b3_coverage": 100.0,
        "repeat_cycle_coverage": 100.0,
    }
    assert profile["new_sign_model_family"] == "B1"
    assert profile["customer_nature"] == "沙龙"
    assert profile["avg_first_return_cycle_days"] == 45
    assert profile["avg_repeat_cycle_days"] == 45
    assert profile["repeat_interval_count"] == 3
    assert {item["name"]: item["quantity"] for item in profile["repeat_models"]} == {
        "B3天才发帘": 60, "B1天才发帘": 30,
    }
    assert {item["name"]: item["quantity"] for item in profile["period_amplitudes"]} == {
        "16": 0, "18": 20, "20": 20, "22": 30, "24": 40,
    }
    assert result["customer_cycles"]["A"]["risk_status"] == "due"
    assert result["customer_cycles"]["B"]["risk_status"] == "due"


def test_profile_alert_marks_strictly_more_than_twice_average_as_abnormal():
    orders = [
        order("1", "A", date(2026, 1, 1), 100, "是"),
        order("2", "A", date(2026, 1, 31), 100),
    ]
    products = [product("1", "A", "B1天才发帘", new_deal="是")]

    at_boundary = analyze_customer_profiles(
        orders, products, orders, products, date(2026, 4, 1), service.SOURCE_LABELS,
    )["customer_cycles"]["A"]
    past_boundary = analyze_customer_profiles(
        orders, products, orders, products, date(2026, 4, 2), service.SOURCE_LABELS,
    )["customer_cycles"]["A"]

    assert at_boundary["risk_status"] == "due"
    assert past_boundary["risk_status"] == "abnormal"


def test_profile_uses_only_first_new_order_model_and_allows_same_day_first_return():
    orders = [
        order("9", "A", date(2026, 1, 1), 100, "是"),
        order("10", "A", date(2026, 1, 1), 120, "是", "是"),
    ]
    products = [
        product("9", "A", "B1天才发帘", new_deal="是"),
        product("10", "A", "B3天才发帘", new_deal="是"),
    ]

    result = analyze_customer_profiles(
        orders, products, orders, products, date(2026, 1, 1), service.SOURCE_LABELS,
    )

    assert result["items"][0]["new_sign_model_family"] == "B1"
    assert result["items"][0]["avg_first_return_cycle_days"] == 0


def test_profile_alert_can_include_historical_customer_outside_period():
    orders = [
        order("1", "A", date(2026, 1, 1), 100, "是"),
        order("2", "A", date(2026, 1, 31), 100),
        order("3", "B", date(2026, 1, 1), 100, "是"),
        order("4", "B", date(2026, 1, 31), 100),
    ]
    products = [
        product("1", "A", "B1天才发帘", new_deal="是"),
        product("3", "B", "B1天才发帘", new_deal="是"),
    ]

    result = analyze_customer_profiles(
        orders,
        products,
        [orders[0]],
        [products[0]],
        date(2026, 3, 2),
        service.SOURCE_LABELS,
        alert_company_ids={"A", "B"},
    )

    assert set(result["customer_cycles"]) == {"A", "B"}


def test_profile_analysis_cache_reuses_result_and_is_mutation_safe(monkeypatch):
    service._clear_profile_cache()
    calls = {"orders": 0, "products": 0}

    def load_orders(*_args, **_kwargs):
        calls["orders"] += 1
        return []

    def load_products(*_args, **_kwargs):
        calls["products"] += 1
        return []

    monkeypatch.setattr(service, "_load_orders", load_orders)
    monkeypatch.setattr(service, "_load_product_rows", load_products)
    scope = service.AnalysisScope("filtered", "CACHE-TEST", None, True)
    filters = AnalysisFilters()

    first = service._profile_analysis(
        None, scope, date(2026, 1, 1), date(2026, 1, 31), filters, [], [],
    )
    first["summary"]["mutated"] = True
    second = service._profile_analysis(
        None, scope, date(2026, 1, 1), date(2026, 1, 31), filters, [], [],
    )

    assert calls == {"orders": 1, "products": 1}
    assert "mutated" not in second["summary"]
    service._clear_profile_cache()


def test_profile_analysis_cache_separates_scope_and_filters(monkeypatch):
    service._clear_profile_cache()
    calls = {"orders": 0}

    def load_orders(*_args, **_kwargs):
        calls["orders"] += 1
        return []

    monkeypatch.setattr(service, "_load_orders", load_orders)
    monkeypatch.setattr(service, "_load_product_rows", lambda *_args, **_kwargs: [])
    common = (None, date(2026, 1, 1), date(2026, 1, 31))

    service._profile_analysis(
        common[0], service.AnalysisScope("self", "U1", None, False),
        common[1], common[2], AnalysisFilters(), [], [],
    )
    service._profile_analysis(
        common[0], service.AnalysisScope("self", "U2", None, False),
        common[1], common[2], AnalysisFilters(), [], [],
    )
    service._profile_analysis(
        common[0], service.AnalysisScope("self", "U1", None, False),
        common[1], common[2], AnalysisFilters.build(countries=["美国"]), [], [],
    )

    # 3 个独立冷计算；带筛选的一次还会追加加载命中客户集。
    assert calls["orders"] == 4
    service._clear_profile_cache()


def test_filter_options_cache_reuses_result_and_separates_scope(monkeypatch):
    service._clear_filter_cache()
    calls = {"orders": 0, "products": 0}

    def load_orders(*_args, **_kwargs):
        calls["orders"] += 1
        return []

    def load_products(*_args, **_kwargs):
        calls["products"] += 1
        return []

    monkeypatch.setattr(service, "_load_orders", load_orders)
    monkeypatch.setattr(service, "_load_product_rows", load_products)
    scope_u1 = service.AnalysisScope("self", "U1", None, False)
    scope_u2 = service.AnalysisScope("self", "U2", None, False)

    first = service.get_filter_options(None, scope_u1, date(2026, 1, 1), date(2026, 1, 31))
    first["countries"].append("污染值")
    second = service.get_filter_options(None, scope_u1, date(2026, 1, 1), date(2026, 1, 31))
    service.get_filter_options(None, scope_u2, date(2026, 1, 1), date(2026, 1, 31))

    assert calls == {"orders": 2, "products": 0}
    assert "污染值" not in second["countries"]
    service._clear_filter_cache()


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
