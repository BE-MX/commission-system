from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.aftersales.models import AfterSalesCase, AfterSalesNotificationLog
from app.aftersales.notification_service import (
    deliver_notification,
    enqueue_notification,
    process_due_notifications,
)
from app.auth.models import ArkUser


def _records(db):
    user = ArkUser(
        username="notify-user",
        password_hash="test-hash",
        real_name="Notify User",
        dingtalk_id="ding-notify-user",
    )
    db.add(user)
    db.flush()
    case = AfterSalesCase(
        case_no="AS-20260710-N1",
        creator_user_id=user.id,
        creator_name_snapshot=user.real_name,
        customer_id="CUST001",
        customer_name_snapshot="客户A",
        customer_grade="A",
        order_id="ORD001",
        order_no_snapshot="NO001",
        purchase_date=date(2026, 7, 1),
        feedback_date=date(2026, 7, 10),
        product_name_snapshot="Invisible Weft",
        is_custom_product=False,
        color_value="#2B",
        length_value="20 inch",
        weight_value=Decimal("100"),
        weight_unit="g",
        quantity=Decimal("2"),
        primary_issue_type="褪色",
        problem_description="客户使用三周后出现明显褪色，已经影响终端客户继续销售。",
        occurred_stage="使用几天",
        affects_end_customer="yes",
        affected_goods_value=Decimal("1150"),
        affected_goods_currency="USD",
    )
    db.add(case)
    db.flush()
    return user, case


def test_enqueue_is_idempotent_per_business_event_and_recipient(db):
    user, case = _records(db)
    first = enqueue_notification(
        db, case, "case:1:submitted", user, "awaiting_supervisor", {"title": "待审核"}
    )
    second = enqueue_notification(
        db, case, "case:1:submitted", user, "awaiting_supervisor", {"title": "待审核"}
    )

    assert first.id == second.id
    assert db.query(AfterSalesNotificationLog).count() == 1


@pytest.mark.asyncio
async def test_delivery_success_is_persisted(db):
    user, case = _records(db)
    log = enqueue_notification(
        db, case, "case:1:approved", user, "approved", {"title": "已通过", "content": "请执行"}
    )

    class Notifier:
        async def send_oa_notice(self, **kwargs):
            return True

    result = await deliver_notification(db, log.id, notifier=Notifier())

    assert result.status == "success"
    assert result.attempt_count == 1
    assert result.sent_at is not None


@pytest.mark.asyncio
async def test_delivery_failure_does_not_rollback_business_state(db):
    user, case = _records(db)
    case.current_status = "approved"
    log = enqueue_notification(
        db, case, "case:1:approved", user, "approved", {"title": "已通过", "content": "请执行"}
    )
    db.commit()

    class Notifier:
        async def send_oa_notice(self, **kwargs):
            raise RuntimeError("network token=secret-value")

    result = await deliver_notification(db, log.id, notifier=Notifier())

    db.refresh(case)
    assert case.current_status == "approved"
    assert result.status == "failed"
    assert result.attempt_count == 1
    assert result.next_retry_at is not None
    assert "secret-value" not in result.last_error_summary


@pytest.mark.asyncio
async def test_automatic_retry_stops_after_three_attempts(db):
    user, case = _records(db)
    log = enqueue_notification(
        db, case, "case:1:retry", user, "approved", {"title": "已通过", "content": "请执行"}
    )

    class Notifier:
        calls = 0

        async def send_oa_notice(self, **kwargs):
            self.calls += 1
            return False

    notifier = Notifier()
    for _ in range(4):
        await deliver_notification(db, log.id, notifier=notifier)

    assert notifier.calls == 3
    assert log.attempt_count == 3
    assert log.status == "failed"


@pytest.mark.asyncio
async def test_manual_retry_can_recover_after_auto_limit(db):
    user, case = _records(db)
    log = enqueue_notification(
        db, case, "case:1:manual", user, "approved", {"title": "已通过", "content": "请执行"}
    )
    log.status = "failed"
    log.attempt_count = 3

    class Notifier:
        async def send_oa_notice(self, **kwargs):
            return True

    result = await deliver_notification(db, log.id, notifier=Notifier(), manual=True)

    assert result.status == "success"
    assert result.attempt_count == 4


@pytest.mark.asyncio
async def test_due_retry_worker_only_processes_due_failed_notifications(db):
    user, case = _records(db)
    due = enqueue_notification(db, case, "case:1:due", user, "approved", {"title": "已通过"})
    future = enqueue_notification(db, case, "case:1:future", user, "approved", {"title": "已通过"})
    due.status = future.status = "failed"
    due.attempt_count = future.attempt_count = 1
    due.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
    future.next_retry_at = datetime.utcnow() + timedelta(hours=1)
    db.commit()

    class Notifier:
        async def send_oa_notice(self, **kwargs):
            return True

    processed = await process_due_notifications(db, notifier=Notifier())

    assert processed == 1
    assert due.status == "success"
    assert future.status == "failed"
