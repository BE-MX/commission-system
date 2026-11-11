from types import SimpleNamespace

import pytest

from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.project_radar.digest import prepare_digest
from app.project_radar.dingtalk_sender import deliver_pending_outbox
from app.project_radar.models import (
    RadarDelivery, RadarDigest, RadarOutbox, RadarTarget, RadarUpdate,
)
from app.project_radar.service import subscribe


def _subscription(db, watch="normal"):
    user = ArkUser(username="digest-user", real_name="digest", password_hash="x", dingtalk_id="dt-user")
    db.add(user)
    db.flush()
    subscription = subscribe(db, user.id, "https://github.com/a/b", validator=lambda url: True)
    subscription.watch_level = watch
    target = db.get(RadarTarget, subscription.target_id)
    target.title = "Radar project"
    return user, subscription, target


def _update(db, target, level="key", event="release-1", notes="Breaking API"):
    row = RadarUpdate(target_id=target.id, event_key=event, detected_at=beijing_now(),
                      rule_level=level, ai_level=level, summary=["API changed"],
                      raw_ref={"release_notes": notes}, created_at=beijing_now())
    db.add(row)
    db.flush()
    return row


def test_normal_watch_only_includes_key_and_digest_is_unique_per_user_day(db):
    user, subscription, target = _subscription(db)
    _update(db, target, level="normal", event="normal-1")
    assert prepare_digest(db, user.id) is None
    update = _update(db, target, level="key")

    digest = prepare_digest(db, user.id)
    assert digest is not None and digest.item_count == 1
    assert "【关键】" in digest.content and "Radar project" in digest.content
    assert prepare_digest(db, user.id).id == digest.id
    assert db.query(RadarDigest).count() == 1 and db.query(RadarOutbox).count() == 1

    class Sender:
        settings = SimpleNamespace(PROJECT_RADAR_PUBLIC_BASE_URL="https://ark.example")

        def send(self, recipient, **kwargs):
            assert recipient.id == user.id
            return "receipt-1"

    assert deliver_pending_outbox(db, sender=Sender()) == 1
    assert digest.status == "sent"
    assert db.query(RadarDelivery).filter_by(subscription_id=subscription.id, update_id=update.id).count() == 1
    assert deliver_pending_outbox(db, sender=Sender()) == 0


def test_normal_updates_respect_seven_day_cooldown(db):
    from datetime import timedelta
    user, subscription, target = _subscription(db, watch="key")
    _update(db, target, level="normal")
    subscription.last_normal_pushed_at = beijing_now() - timedelta(days=3)
    assert prepare_digest(db, user.id) is None
    subscription.last_normal_pushed_at = beijing_now() - timedelta(days=8)
    assert prepare_digest(db, user.id).item_count == 1


def test_failed_delivery_marks_digest_and_health_failed(db):
    user, _, target = _subscription(db)
    _update(db, target)
    digest = prepare_digest(db, user.id)

    class Sender:
        settings = SimpleNamespace(PROJECT_RADAR_PUBLIC_BASE_URL="https://ark.example")

        def send(self, recipient, **kwargs):
            raise RuntimeError("synthetic delivery failure")

    with pytest.raises(RuntimeError, match="投递失败"):
        deliver_pending_outbox(db, sender=Sender())
    assert digest.status == "failed"
    outbox = db.query(RadarOutbox).one()
    assert outbox.status == "failed" and outbox.last_error
    assert db.query(RadarDelivery).count() == 0


def test_stale_sending_is_failed_without_automatic_replay(db):
    from datetime import timedelta
    user, _, target = _subscription(db)
    _update(db, target)
    digest = prepare_digest(db, user.id)
    outbox = db.query(RadarOutbox).one()
    outbox.status = "sending"
    outbox.claimed_at = beijing_now() - timedelta(minutes=16)
    db.commit()
    calls = []

    class Sender:
        settings = SimpleNamespace(PROJECT_RADAR_PUBLIC_BASE_URL="https://ark.example")

        def send(self, recipient, **kwargs):
            calls.append(1)
            return "must-not-send"

    with pytest.raises(RuntimeError, match="投递失败"):
        deliver_pending_outbox(db, sender=Sender())
    assert calls == []
    assert outbox.status == "failed" and "不自动重发" in outbox.last_error
    assert digest.status == "failed"
