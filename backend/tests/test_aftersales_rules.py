from decimal import Decimal

import pytest

from app.aftersales.rules import (
    WorkflowError,
    classify_compensation,
    evaluate_evidence,
    next_status,
    validate_actions,
)


@pytest.mark.parametrize(
    ("actions", "expected_total"),
    [
        ([{"code": "replacement", "estimated_cost_usd": "360"}], Decimal("360.00")),
        ([{"code": "cash_refund", "amount_usd": "125.50"}], Decimal("125.50")),
        ([{"code": "freight_subsidy", "amount_usd": "60"}], Decimal("60.00")),
        ([{"code": "custom", "company_bears_cost": True, "estimated_cost_usd": "90"}], Decimal("90.00")),
    ],
)
def test_value_bearing_actions_are_always_compensation(actions, expected_total):
    assert classify_compensation(actions) == (True, expected_total)


def test_return_inspection_is_not_compensation_when_customer_pays_freight():
    actions = [{"code": "return_inspection", "freight_payer": "customer"}]

    assert classify_compensation(actions) == (False, Decimal("0.00"))


def test_return_inspection_is_compensation_when_company_pays_freight():
    actions = [
        {
            "code": "return_inspection",
            "freight_payer": "company",
            "freight_cost_usd": "45",
        }
    ]

    assert classify_compensation(actions) == (True, Decimal("45.00"))


def test_company_paid_freight_is_compensation_even_for_paid_rework():
    actions = [{"code": "paid_rework", "freight_payer": "company", "freight_cost_usd": "35"}]

    assert classify_compensation(actions) == (True, Decimal("35.00"))


def test_explanation_and_care_guidance_are_not_compensation():
    actions = [{"code": "explanation"}, {"code": "care_guidance"}]

    assert classify_compensation(actions) == (False, Decimal("0.00"))


def test_evidence_reports_missing_required_items_and_score():
    result = evaluate_evidence(
        issue_type="脱发",
        batch_no="BATCH-2407",
        care_note="客户正常安装，每周清洗一次，低温吹干并避光存放。",
        evidence=[{"evidence_type": "overview_image"}],
    )

    assert result.is_sufficient is False
    assert set(result.missing_items) == {"问题近景图", "问题视频", "包装/批次标签"}
    assert result.score == 50


def test_evidence_is_sufficient_when_all_applicable_items_exist():
    result = evaluate_evidence(
        issue_type="脱发",
        batch_no="BATCH-2407",
        care_note="客户正常安装，每周清洗一次，低温吹干并避光存放。",
        evidence=[
            {"evidence_type": "overview_image"},
            {"evidence_type": "closeup_image"},
            {"evidence_type": "video"},
            {"evidence_type": "batch_label"},
        ],
    )

    assert result.is_sufficient is True
    assert result.missing_items == []
    assert result.score == 100


def test_non_dynamic_issue_does_not_require_video():
    result = evaluate_evidence(
        issue_type="褪色",
        batch_no=None,
        care_note="客户使用无硫酸盐洗发水，低温护理，未游泳或暴晒。",
        evidence=[
            {"evidence_type": "overview_image"},
            {"evidence_type": "closeup_image"},
        ],
    )

    assert result.is_sufficient is True
    assert "问题视频" not in result.missing_items


@pytest.mark.parametrize(
    ("current", "actor", "decision", "compensation", "expected"),
    [
        ("awaiting_supervisor", "supervisor", "approve", False, "approved"),
        ("awaiting_supervisor", "supervisor", "approve", True, "awaiting_director"),
        ("awaiting_supervisor", "supervisor", "return", False, "returned"),
        ("awaiting_supervisor", "supervisor", "reject", False, "rejected"),
        ("awaiting_director", "director", "approve", True, "approved"),
        ("awaiting_director", "director", "return", True, "returned"),
        ("awaiting_director", "director", "reject", True, "rejected"),
    ],
)
def test_review_transition_matrix(current, actor, decision, compensation, expected):
    assert next_status(current, actor, decision, compensation) == expected


@pytest.mark.parametrize(
    ("current", "actor", "decision", "compensation"),
    [
        ("draft", "supervisor", "approve", False),
        ("awaiting_supervisor", "director", "approve", True),
        ("awaiting_director", "supervisor", "approve", True),
        ("awaiting_director", "director", "approve", False),
        ("approved", "director", "approve", True),
    ],
)
def test_illegal_review_transition_is_rejected(current, actor, decision, compensation):
    with pytest.raises(WorkflowError):
        next_status(current, actor, decision, compensation)


def test_action_details_are_validated_before_submission():
    with pytest.raises(ValueError, match="退回地址"):
        validate_actions([{"code": "return_inspection", "freight_payer": "customer"}])
    with pytest.raises(ValueError, match="数量"):
        validate_actions([{"code": "replacement", "estimated_cost_usd": "100"}])

    validate_actions(
        [
            {
                "code": "replacement",
                "quantity": "2",
                "product": "Invisible Weft #2B 20 inch",
                "estimated_cost_usd": "360",
                "delivery_date": "2026-07-20",
            }
        ]
    )
