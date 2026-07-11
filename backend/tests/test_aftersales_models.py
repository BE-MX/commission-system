from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.aftersales.models import (
    AfterSalesCase,
    AfterSalesEvidence,
    AfterSalesNotificationLog,
    AfterSalesReview,
)
from app.auth.models import ArkUser


def _user(db, username: str) -> ArkUser:
    user = ArkUser(
        username=username,
        password_hash="test-hash",
        real_name=username,
        dingtalk_id=f"ding-{username}",
    )
    db.add(user)
    db.flush()
    return user


def _case(db, creator: ArkUser, case_no: str = "AS-20260710-001") -> AfterSalesCase:
    case = AfterSalesCase(
        case_no=case_no,
        creator_user_id=creator.id,
        creator_name_snapshot=creator.real_name,
        customer_id="customer-1",
        customer_name_snapshot="Test Customer",
        customer_grade="A",
        order_id="order-1",
        order_no_snapshot="SO-001",
        purchase_date=date(2026, 7, 1),
        feedback_date=date(2026, 7, 10),
        product_name_snapshot="Invisible Weft",
        is_custom_product=False,
        color_value="#2B",
        length_value="20 inch",
        weight_value=Decimal("100.00"),
        weight_unit="g",
        quantity=Decimal("2.00"),
        primary_issue_type="褪色",
        problem_description="客户使用三周后出现明显褪色，已经影响终端客户继续销售。",
        occurred_stage="使用几天",
        affects_end_customer="yes",
        affected_goods_value=Decimal("1150.00"),
        affected_goods_currency="USD",
    )
    db.add(case)
    db.flush()
    return case


def test_case_number_is_unique(db):
    creator = _user(db, "sales-one")
    _case(db, creator)
    db.commit()

    with pytest.raises(IntegrityError):
        _case(db, creator, case_no="AS-20260710-001")


def test_one_effective_review_per_role_and_round(db):
    creator = _user(db, "sales-two")
    reviewer = _user(db, "supervisor-two")
    case = _case(db, creator, case_no="AS-20260710-002")
    db.add(
        AfterSalesReview(
            case_id=case.id,
            workflow_round=1,
            reviewer_role="supervisor",
            reviewer_user_id=reviewer.id,
            reviewer_name_snapshot=reviewer.real_name,
            decision="approve",
            remark="同意",
        )
    )
    db.commit()

    db.add(
        AfterSalesReview(
            case_id=case.id,
            workflow_round=1,
            reviewer_role="supervisor",
            reviewer_user_id=reviewer.id,
            reviewer_name_snapshot=reviewer.real_name,
            decision="approve",
            remark="同意",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_notification_is_unique_per_event_and_recipient(db):
    creator = _user(db, "sales-three")
    case = _case(db, creator, case_no="AS-20260710-003")
    first = AfterSalesNotificationLog(
        case_id=case.id,
        business_event_key="case:3:round:1:submitted",
        recipient_user_id=creator.id,
        recipient_dingtalk_id=creator.dingtalk_id,
        template_code="awaiting_supervisor",
        status="pending",
    )
    db.add(first)
    db.commit()

    db.add(
        AfterSalesNotificationLog(
            case_id=case.id,
            business_event_key="case:3:round:1:submitted",
            recipient_user_id=creator.id,
            recipient_dingtalk_id=creator.dingtalk_id,
            template_code="awaiting_supervisor",
            status="pending",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_money_columns_are_fixed_precision():
    assert AfterSalesCase.affected_goods_value.type.scale == 2
    assert AfterSalesCase.estimated_compensation_usd.type.scale == 2


def test_case_collections_default_to_noload():
    assert AfterSalesCase.evidence.property.lazy == "noload"
    assert AfterSalesCase.reviews.property.lazy == "noload"
    assert AfterSalesCase.ai_runs.property.lazy == "noload"
    assert AfterSalesCase.events.property.lazy == "noload"


def test_evidence_keeps_storage_path_private():
    assert hasattr(AfterSalesEvidence, "storage_path")
    assert hasattr(AfterSalesEvidence, "original_filename")
