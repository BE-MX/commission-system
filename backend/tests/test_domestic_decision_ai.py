"""AI cannot manufacture facts or turn language into unauthorized SQL."""
import json
import pytest
from fastapi import HTTPException
from app.domestic_decision.ai_contract import validate_suggestions, anonymous_facts
from app.domestic_decision.plan_service import _validate, _rules
from app.domestic_decision.schemas import AnalysisRequest
from app.core.time import beijing_today

OPTIONS = [{"code": "record_gap", "label": "可能存在记录缺口，需要核对"}, {"code": "product_mix", "label": "可能存在需求结构变化，需要询问"}]
FACTS = [{"fact_id": 0, "title": "客户A复购观察", "explanation": "客户A距上次购买45天", "next_step": "询问客户A采购计划", "evidence_refs": [{"type": "orders", "id": 3}]}]


@pytest.mark.parametrize("attack", [
    {"suggestions": [{"fact_id": 99, "hypothesis_code": "record_gap", "alternative_code": "product_mix"}]},
    {"suggestions": [{"fact_id": 0, "hypothesis_code": "增长三成", "alternative_code": "product_mix"}]},
    {"suggestions": [{"fact_id": 0, "hypothesis": "其他客户李某已经停止经营", "next_step": "立即联系李某"}]},
    {"suggestions": [{"fact_id": 0, "hypothesis_code": "record_gap", "alternative_code": "product_mix", "profit": 10000}]},
    {"suggestions": [{"fact_id": 0, "hypothesis_code": "record_gap", "alternative_code": "product_mix"}], "customer": "不可见客户"},
])
def test_ai_free_text_numbers_extra_customers_and_unregistered_refs_rejected(attack):
    with pytest.raises(ValueError):
        validate_suggestions(attack, FACTS, OPTIONS)


def test_ai_only_selects_registered_hypotheses_with_original_facts():
    accepted = validate_suggestions({"suggestions": [{"fact_id": 0, "hypothesis_code": "record_gap", "alternative_code": "product_mix"}]}, FACTS, OPTIONS)
    assert accepted[0]["next_step"] == FACTS[0]["next_step"]
    assert accepted[0]["evidence_refs"] == FACTS[0]["evidence_refs"]
    anonymous = anonymous_facts(FACTS, [{"shop_name": "客户A", "customer_id": 42}])
    assert "客户A" not in json.dumps(anonymous, ensure_ascii=False)
    assert "客户A" in FACTS[0]["title"]


def test_enriched_browser_fields_never_enter_model_payload():
    enriched = [{**FACTS[0], "facts": [{"description": "客户A敏感经营细节"}], "recommended_action": "联系客户A", "scope": {"internal": "secret"}}]
    safe = anonymous_facts(enriched, [{"shop_name": "客户A", "customer_id": 42}])
    serialized = json.dumps(safe, ensure_ascii=False)
    assert "客户A" not in serialized and "secret" not in serialized
    assert "facts" not in safe[0] and "recommended_action" not in safe[0]
    assert safe[0]["evidence_refs"] == FACTS[0]["evidence_refs"]


def test_finance_customers_outside_product_selection_are_anonymized(db, monkeypatch):
    from app.domestic_decision.models import DecisionConfig
    from app.domestic_decision.job_service import _brief
    db.add(DecisionConfig(key="ai_hypothesis_options", value=OPTIONS))
    db.flush()
    sent = []
    def chat(*args, **kwargs):
        sent.extend(kwargs["messages"])
        return {"content": '{"suggestions": []}'}
    monkeypatch.setattr("app.ai.service.chat", chat)
    result = {"meta": {"warnings": []}, "summary": {},
              "customers": [{"customer_id": 1, "shop_name": "产品命中客户"}],
              "finance": {"summary": {}, "customers": [{"customer_id": 2, "shop_name": "非匹配信用店"}]},
              "insights": [{**FACTS[0], "title": "非匹配信用店有账户欠款", "explanation": "非匹配信用店欠款需核对", "next_step": "核对非匹配信用店约定", "facts": [{"description": "非匹配信用店"}]}]}
    _, source = _brief(db, {"id": 1}, result, "executive")
    assert source == "ai" and sent
    assert "非匹配信用店" not in json.dumps(sent, ensure_ascii=False)
    assert "客户匿名标识2" in json.dumps(sent, ensure_ascii=False)


@pytest.fixture
def choices():
    return {"customers": [{"value": 1, "label": "上海门店"}], "owners": [{"value": 2, "label": "业务员乙"}], "dimensions": {"product_type": [{"value": "cap", "label": "头套"}], "craft": [{"value": "c1", "label": "工艺甲"}], "length": [{"value": "15厘米", "label": "15厘米"}]}, "permissions": {"finance": False, "all": False}}


def test_plan_preview_keeps_dates_values_and_scope_bounded(choices):
    base = AnalysisRequest(start_date=beijing_today(), end_date=beijing_today())
    plan = _validate(_rules("近90天上海门店的头套数量", base, choices), choices)
    assert (plan.end_date - plan.start_date).days == 89
    assert plan.customer_ids == [1]
    assert plan.filters == {"product_type": ["cap"]}
    assert plan.metric == "quantity"


@pytest.mark.parametrize("update", [{"customer_ids": [99]}, {"owner_ids": [99]}, {"scope": "all"}, {"filters": {"settle_mode": ["credit"]}}, {"filters": {"craft": ["invisible"]}}, {"finance_related_customers": True}])
def test_plan_cannot_expand_ids_scope_finance_or_runtime_values(choices, update):
    query = AnalysisRequest(start_date=beijing_today(), end_date=beijing_today()).model_copy(update=update)
    with pytest.raises(HTTPException):
        _validate(query, choices)


def test_query_schema_rejects_sql_and_unknown_fields():
    with pytest.raises(ValueError):
        AnalysisRequest.model_validate({"start_date": "2026-01-01", "end_date": "2026-01-31", "sql": "DELETE FROM ark_domestic_orders"})
