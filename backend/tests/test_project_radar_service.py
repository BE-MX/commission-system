from datetime import timedelta

import pytest

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.project_radar.deep_link import issue_detail_token, verify_detail_token
from app.project_radar.models import RadarSource, RadarSubscription, RadarTarget
from app.project_radar.service import (
    remove_subscription, serialize_subscription, subscribe, update_subscription,
)


def _user(db, name="radar-user", dingtalk_id=None):
    row = ArkUser(username=name, real_name=name, password_hash="not-a-real-password", dingtalk_id=dingtalk_id)
    db.add(row)
    db.flush()
    return row


def _allow(_url):
    return True


def test_duplicate_subscription_only_appends_source_and_users_stay_isolated(db):
    first, second = _user(db, "radar-first"), _user(db, "radar-second")
    one = subscribe(db, first.id, "https://github.com/Microsoft/MarkItDown.git?utm_source=x", validator=_allow)
    duplicate = subscribe(db, first.id, "https://github.com/microsoft/markitdown/tree/main/docs", validator=_allow)
    other = subscribe(db, second.id, "https://github.com/microsoft/markitdown", validator=_allow)

    assert one.id == duplicate.id
    assert other.id != one.id and other.target_id == one.target_id
    assert db.query(RadarTarget).count() == 1
    assert db.query(RadarSubscription).count() == 2
    assert db.query(RadarSource).filter_by(subscription_id=one.id).count() == 2
    assert db.query(RadarSource).filter_by(subscription_id=other.id).count() == 1
    update_subscription(db, first.id, one.id, {"note": "only mine", "status": "trying"})
    db.refresh(other)
    assert other.remark == "" and other.status == "inbox"


def test_manual_override_wins_over_target_analysis_and_status_sets_watch_level(db):
    user = _user(db)
    subscription = subscribe(db, user.id, "https://github.com/a/b", validator=_allow)
    target = db.get(RadarTarget, subscription.target_id)
    target.one_liner = "AI version"
    update_subscription(db, user.id, subscription.id, {
        "status": "adopted", "overrides": {"one_liner": "我的人工结论"},
    })
    assert subscription.watch_level == "adopted"
    target.one_liner = "new AI version"
    assert serialize_subscription(db, subscription)["one_liner"] == "我的人工结论"

    update_subscription(db, user.id, subscription.id, {"status": "dropped"})
    assert subscription.watch_level == "silent"
    assert target.scan_enabled is False


def test_remove_is_soft_and_recent_reingest_restores_private_state(db):
    user = _user(db)
    subscription = subscribe(db, user.id, "https://example.com", note="keep me", tags=["Agent"], validator=_allow)
    update_subscription(db, user.id, subscription.id, {"status": "trying"})
    remove_subscription(db, user.id, subscription.id)
    assert subscription.removed_at is not None

    restored = subscribe(db, user.id, "https://example.com", validator=_allow)
    assert restored.id == subscription.id and restored.removed_at is None
    assert restored.remark == "keep me" and restored.tags == ["Agent"] and restored.status == "trying"


def test_expired_signature_and_cross_user_or_cross_item_tokens_fail_closed(db):
    user = _user(db)
    subscription = subscribe(db, user.id, "https://example.com", validator=_allow)
    now = beijing_now()
    token = issue_detail_token("test-secret", user.id, subscription.id, now=now)
    assert verify_detail_token("test-secret", token, user.id, subscription.id, now=now + timedelta(hours=23))
    assert not verify_detail_token("test-secret", token, user.id, subscription.id, now=now + timedelta(hours=25))
    assert not verify_detail_token("test-secret", token, user.id + 1, subscription.id, now=now)
    assert not verify_detail_token("test-secret", token, user.id, subscription.id + 1, now=now)
    assert not verify_detail_token("wrong-secret", token, user.id, subscription.id, now=now)
