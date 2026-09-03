import time
from collections import OrderedDict
from datetime import date, datetime, timedelta

import pytest
from fastapi import Request

from app.auth.models import ArkRole, ArkUser
from app.core.time import beijing_now
from app.whatsapp_translation.auth import DeviceIdentity
from app.whatsapp_translation.quota_service import (
    BoundedSlidingWindowLimiter,
    estimate_p95,
    record_failure,
    record_success,
    reserve_daily_input,
)
from app.whatsapp_translation.translation_service import TranslationCoordinator
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import TranslationDevice, TranslationUsageDaily


def usage_for(db, usage_date, device_id):
    return (
        db.query(TranslationUsageDaily)
        .filter(
            TranslationUsageDaily.usage_date == usage_date,
            TranslationUsageDaily.device_id == device_id,
        )
        .one_or_none()
    )


@pytest.fixture
def device(db):
    role = ArkRole(name="quota_worker", label="quota_worker")
    db.add(role)
    db.flush()
    user = ArkUser(username="quota_worker", password_hash="test", real_name="quota_worker")
    db.add(user)
    db.flush()
    user.roles.append(role)
    device = TranslationDevice(
        user_id=user.id,
        token_hash="a" * 64,
        device_name="Quota Device",
        browser_name="Chrome",
        browser_version="140.0.0.0",
        extension_version="1.0.0",
        expires_at=beijing_now().replace(year=2099),
    )
    db.add(device)
    db.commit()
    identity = DeviceIdentity(
        user_id=user.id,
        device_id=device.id,
        real_name=user.real_name,
        extension_version="1.0.0",
        expires_at=device.expires_at,
        is_admin=False,
    )
    return device, identity


def test_minute_limiter_allows_thirty_and_returns_retry_after():
    limiter = BoundedSlidingWindowLimiter(limit=30, window_seconds=60)
    for _ in range(30):
        allowed, retry_after = limiter.allow("device")
        assert allowed is True
        assert retry_after == 0
    allowed, retry_after = limiter.allow("device")
    assert allowed is False
    assert 1 <= retry_after <= 60


def test_limiter_evicts_oldest_keys():
    limiter = BoundedSlidingWindowLimiter(limit=10, window_seconds=60, max_keys=2)
    limiter.allow("oldest")
    limiter.allow("middle")
    limiter.allow("newest")
    assert len(limiter.windows) <= 2
    assert limiter.windows.get("oldest") is None


def test_daily_quota_changes_at_beijing_midnight(db, device, monkeypatch):
    _, identity = device
    import app.whatsapp_translation.quota_service as quota_service

    monkeypatch.setattr(quota_service, "beijing_today", lambda: date(2026, 9, 3))
    reserve_daily_input(db, identity, 200_000)
    with pytest.raises(WhatsAppTranslationError) as error:
        reserve_daily_input(db, identity, 1)
    assert error.value.error_code == "daily_quota_exceeded"

    monkeypatch.setattr(quota_service, "beijing_today", lambda: date(2026, 9, 4))
    reserve_daily_input(db, identity, 1)
    assert usage_for(db, date(2026, 9, 4), identity.device_id).input_chars == 1


def test_two_devices_share_user_daily_limit(db, device):
    _, first_identity = device
    second_device = TranslationDevice(
        user_id=first_identity.user_id,
        token_hash="b" * 64,
        device_name="Second Device",
        browser_name="Chrome",
        browser_version="140.0.0.0",
        extension_version="1.0.0",
        expires_at=beijing_now().replace(year=2099),
    )
    db.add(second_device)
    db.commit()
    second_identity = DeviceIdentity(
        user_id=first_identity.user_id,
        device_id=second_device.id,
        real_name=first_identity.real_name,
        extension_version="1.0.0",
        expires_at=second_device.expires_at,
        is_admin=False,
    )
    reserve_daily_input(db, first_identity, 150_000)
    reserve_daily_input(db, second_identity, 50_000)
    with pytest.raises(WhatsAppTranslationError) as error:
        reserve_daily_input(db, second_identity, 1)
    assert error.value.error_code == "daily_quota_exceeded"


def test_accepted_success_and_failure_are_counted(db, device):
    _, identity = device
    row = reserve_daily_input(db, identity, 20)
    record_success(
        db,
        row,
        direction="incoming",
        source_language="en", target_language="zh-CN",
        duration_ms=750,
        input_tokens=10,
        output_tokens=20,
    )
    failed_row = reserve_daily_input(db, identity, 5)
    record_failure(db, failed_row, direction="outgoing", error_code="ai_timeout")
    row = usage_for(db, date(2026, 9, 3), identity.device_id)
    assert row.request_count == 2
    assert row.success_count == 1
    assert row.failure_count == 1
    assert row.direction_counts["incoming"] == 1
    assert row.language_pair_counts["en\u2192zh-CN"] == 1
    assert row.duration_buckets["lt_1000"] == 1
    assert row.error_counts["ai_timeout"] == 1
    assert estimate_p95(row.duration_buckets) == 1000


def test_rejected_requests_do_not_reserve(db, device):
    _, identity = device
    assert usage_for(db, date(2026, 9, 3), identity.device_id) is None


def test_translation_coordinator_runs_request_id_once(db, device):
    coordinator = TranslationCoordinator()
    calls = []

    def callback():
        calls.append("run")
        return "result"

    first = coordinator.execute(1, "same-request-id", callback, timeout_seconds=1)
    second = coordinator.execute(1, "same-request-id", callback, timeout_seconds=1)
    assert first == second == "result"
    assert calls == ["run"]
    coordinator.clear()


def test_translation_coordinator_waiter_timeout_returns_ai_unavailable():
    import threading

    coordinator = TranslationCoordinator()
    start_event = threading.Event()
    stop_event = threading.Event()

    def callback():
        start_event.set()
        stop_event.wait(timeout=2)
        return "late"

    outcome = {}

    def owner():
        outcome["value"] = coordinator.execute(1, "slow", callback, timeout_seconds=2)

    thread = threading.Thread(target=owner)
    thread.start()
    start_event.wait(timeout=1)
    assert coordinator.execute(1, "slow", lambda: "duplicate", timeout_seconds=0.1) == "ai_unavailable"
    stop_event.set()
    thread.join()
    assert outcome["value"] == "late"
    coordinator.clear()


