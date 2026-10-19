"""Report-scoped human decisions: pure contracts and facts, no database access."""
from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from app.battle_report.schemas import AwardRules, ReportInput


def decision(**changes):
    return {"order_id": "101", "order_no": "22100", "company_id": "201", "owner_id": "301",
            "account_date": "2026-02-03", "role": "new_sign", "reason": "主管已核对原订单及客户历史", **changes}


def report_payload(decisions):
    return {"name": "年度奖", "start_date": "2026-01-01", "end_date": "2026-12-31",
            "target_deadline": "2026-10-19T09:00:00", "members": [{"ark_user_id": 1, "team": "A"}],
            "award_kind": "annual_repurchase", "award_rules": {
                "push_start_date": "2026-10-19", "order_decisions": decisions,
                "baselines": [{"ark_user_id": 1, "hired_date": "2020-01-01",
                               "gmv_2025_usd": "100", "target_gmv_usd": "130"}]}}


def source(**changes):
    return {"order_id": "101", "order_no": "22100", "company_id": "201", "user_id": "301",
            "account_date": date(2026, 2, 3), "amount_usd": "123.45", **changes}


def test_order_decisions_can_be_saved_with_nonparticipant_owner():
    report = ReportInput.model_validate(report_payload([decision(owner_id="999")]))
    saved = report.award_rules.model_dump(mode="json")["order_decisions"][0]
    assert saved == decision(owner_id="999")


@pytest.mark.parametrize("change", [
    {"order_id": ""}, {"order_id": "1 OR 1"}, {"order_id": "１２３"}, {"order_id": "1" * 101},
    {"company_id": "x"}, {"owner_id": "-1"}, {"owner_id": 301},
    {"order_no": " "}, {"order_no": "x" * 101}, {"reason": " \n "}, {"reason": "x" * 501},
    {"role": "include"}, {"include_gmv": False},
])
def test_decision_rejects_invalid_identity_or_unreviewable_input(change):
    with pytest.raises(ValidationError):
        ReportInput.model_validate(report_payload([decision(**change)]))


def test_decisions_reject_duplicate_order_id():
    with pytest.raises(ValidationError, match="重复"):
        ReportInput.model_validate(report_payload([decision(), decision(role="repeat")]))


def test_decisions_limit_batch_size():
    with pytest.raises(ValidationError):
        ReportInput.model_validate(report_payload([decision(order_id=str(i)) for i in range(201)]))


@pytest.mark.parametrize("day", ["2019-12-31", "2020-01-01", "2025-12-31", "2027-01-01"])
def test_decision_date_must_be_inside_report_period(day):
    with pytest.raises(ValidationError, match="周期"):
        ReportInput.model_validate(report_payload([decision(account_date=day)]))


def test_decision_dates_accept_period_edges():
    report = ReportInput.model_validate(report_payload([
        decision(account_date="2026-01-01"), decision(order_id="102", account_date="2026-12-31")]))
    assert len(report.award_rules.order_decisions) == 2


def test_decision_index_validates_saved_rules_and_supports_old_rules():
    from app.battle_report.order_decisions import decision_index
    assert decision_index(None) == {} and decision_index({}) == {}
    assert decision_index({"baselines": []}) == {}
    rules = AwardRules.model_validate({"push_start_date": "2026-10-19", "order_decisions": [decision()]})
    index = decision_index(rules)
    assert index["101"].account_date == date(2026, 2, 3)
    assert decision_index(rules.model_dump(mode="json")) == index
    with pytest.raises(ValueError, match="重复"):
        decision_index({"order_decisions": [decision(), decision()]})
    with pytest.raises(ValidationError):
        decision_index({"order_decisions": [decision(owner_id="invalid")]})


@pytest.mark.parametrize("mark,role", [("是", "new_sign"), ("否", "repeat")])
def test_legal_source_role_without_decision_is_unchanged(mark, role):
    from app.battle_report.order_decisions import resolve_order_role
    assert resolve_order_role(source(), mark, {}) == (role, None)


@pytest.mark.parametrize("mark", ["", None, "未知", True, 1])
def test_missing_decision_preserves_existing_pending_warning(mark):
    from app.battle_report.order_decisions import resolve_order_role
    role, issue = resolve_order_role(source(), mark, {})
    assert role == "pending"
    assert issue == "订单 101 新成交标记为空或非法；GMV保留，新签复购指标待核对"


@pytest.mark.parametrize("role", ["new_sign", "repeat", "exclude_metrics"])
def test_valid_human_role_resolves_blank_flag_without_mutating_source(role):
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    row = source()
    before = deepcopy(row)
    index = decision_index({"order_decisions": [decision(role=role)]})
    assert resolve_order_role(row, "", index) == (role, None)
    assert row == before and row["amount_usd"] == "123.45"


@pytest.mark.parametrize("change", [
    {"order_no": "22101"}, {"company_id": "202"}, {"user_id": "302"},
    {"account_date": date(2026, 2, 4)}, {"order_no": None},
])
def test_identity_drift_suspends_decision_even_when_source_flag_is_valid(change):
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    row = source(**change)
    index = decision_index({"order_decisions": [decision()]})
    role, issue = resolve_order_role(row, "是", index)
    assert role == "pending" and "裁定" in issue and "GMV保留" in issue
    assert row["amount_usd"] == "123.45"


@pytest.mark.parametrize("role,mark", [("new_sign", "否"), ("repeat", "是")])
def test_human_role_cannot_silently_override_opposite_valid_source_flag(role, mark):
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    index = decision_index({"order_decisions": [decision(role=role)]})
    resolved, issue = resolve_order_role(source(), mark, index)
    assert resolved == "pending" and "冲突" in issue and "GMV保留" in issue


@pytest.mark.parametrize("mark", ["是", "否", ""])
def test_explicit_metric_exclusion_remains_excluded_with_legal_source_flag(mark):
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    index = decision_index({"order_decisions": [decision(role="exclude_metrics")]})
    assert resolve_order_role(source(), mark, index) == ("exclude_metrics", None)


def test_decision_is_scoped_to_its_order_id_and_does_not_mark_same_customer_orders():
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    index = decision_index({"order_decisions": [decision()]})
    resolved, issue = resolve_order_role(source(order_id="102"), "", index)
    assert resolved == "pending" and "订单 102" in issue


def test_numeric_source_identifiers_match_digit_string_contract():
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    index = decision_index({"order_decisions": [decision()]})
    assert resolve_order_role(source(order_id=101, company_id=201, user_id=301), "", index) == ("new_sign", None)


def test_digit_zero_is_not_silently_treated_as_a_missing_identity():
    from app.battle_report.order_decisions import decision_index, resolve_order_role
    index = decision_index({"order_decisions": [decision(order_id="0", company_id="0", owner_id="0")]})
    assert resolve_order_role(source(order_id=0, company_id=0, user_id=0), "", index) == ("new_sign", None)
