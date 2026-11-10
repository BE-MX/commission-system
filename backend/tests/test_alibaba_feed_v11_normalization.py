"""Synthetic offline v1.1 contracts; production-style autoflush=False sessions."""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session

from app.alibaba_feed.models import AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedMessage, AlibabaFeedPilot, AlibabaFeedSource
from app.alibaba_feed.normalization import safe_messages
from app.alibaba_feed.errors import FeedError
from app.alibaba_feed.worker import claim_batch, process_item, process_next_batch
from tests.test_alibaba_feed_core import NOW, ingest, payload


def v11_payload(run_id="v11-a", *, snapshot_revision=1, conversation_revision=1, message_revision=1):
    data = payload(run_id)
    data["schema"] = "ark_alibaba_feed_v1.1"
    data["source_account_uid"] = "test-shop"
    data["run"].update(collector_id="synthetic", collector_version="1", coverage={
        "selection": "created_window", "activity_window_start": None, "activity_window_end": None,
        "all_pages_read": True, "activity_scan_complete": False,
    })
    record = data["records"][0]
    record.update(buyer_id="buyer-a", conversation_id="conversation-a", assignee_external_user_id="employee-a",
                  observed_at="2026-11-05T05:20:00+08:00", snapshot_revision=snapshot_revision,
                  conversation_revision=conversation_revision, last_activity_at="2026-11-04T06:00:00+08:00",
                  coverage={"history_complete": True, "latest_complete": True, "has_more": False,
                            "covered_from": "2026-11-04T06:00:00+08:00", "covered_through": "2026-11-05T05:20:00+08:00",
                            "edits_observable": True, "deletions_observable": True})
    record["messages"][0].update(message_id="message-a", source_order=1, actor_type="human",
                                 sender_external_user_id=None, message_revision=message_revision, deleted_at=None)
    return data


@pytest.fixture
def v11_store(monkeypatch):
    monkeypatch.setattr("app.alibaba_feed.auth.recheck_feed_principal", lambda *args, **kwargs: None)
    engine = create_engine("sqlite://")
    for model in (AlibabaFeedSource, AlibabaFeedPilot, AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedMessage):
        model.__table__.create(engine)
    with Session(engine, autoflush=False) as db:
        source = AlibabaFeedSource(source_account_uid="test-shop", integration_app_id=1, name="Synthetic",
                                   ingest_enabled=True, consent_state="authorized")
        db.add(source)
        db.flush()
        db.add(AlibabaFeedPilot(id=1, source_id=source.id, user_id=1, enabled=True))
        db.commit()
        yield db, source
    engine.dispose()


def process(store, data):
    receipt = ingest(store, data)
    process_next_batch(store[0], now=NOW)
    return store[0].query(AlibabaFeedItem).filter_by(batch_id=receipt["batch_id"]).one()


def test_shared_conversation_ref_changes_do_not_duplicate(v11_store):
    first = process(v11_store, v11_payload())
    second = v11_payload("tm")
    second["records"][0].update(type="tm", inquiry_id="tm-a")
    second["records"][0]["messages"][0]["ref"] = "different-ref"
    copy = process(v11_store, second)
    db = v11_store[0]
    assert db.query(AlibabaFeedMessage).count() == 1
    assert not db.query(AlibabaFeedMessage).one().version_conflict
    assert safe_messages(db, first)[0]["ref"] == "m1"
    assert safe_messages(db, copy)[0]["ref"] == "different-ref"


@pytest.mark.parametrize("stable", [True, False])
def test_read_gate_refreshes_cached_withdrawal_or_legacy_block(v11_store, stable):
    item = process(v11_store, v11_payload() if stable else payload())
    db, source = v11_store
    if stable:
        cached = db.query(AlibabaFeedMessage).one()
        assert cached.tombstone_revision is None
        with db.get_bind().begin() as conn:
            conn.execute(update(AlibabaFeedMessage).where(AlibabaFeedMessage.id == cached.id)
                         .values(tombstone_revision=2, content=None))
        assert cached.tombstone_revision is None
    else:
        assert not source.legacy_identity_blocked
        with db.get_bind().begin() as conn:
            conn.execute(update(AlibabaFeedSource).where(AlibabaFeedSource.id == source.id)
                         .values(legacy_identity_blocked=True))
        assert not source.legacy_identity_blocked
    assert safe_messages(db, item) == []


def test_message_revision_independent_of_record_metadata(v11_store):
    first = process(v11_store, v11_payload(snapshot_revision=10))
    later = v11_payload("new-message", snapshot_revision=2, conversation_revision=2, message_revision=2)
    later["records"][0]["messages"][0]["text"] = "Edited synthetic"
    new = process(v11_store, later)
    db = v11_store[0]
    assert new.outcome == "history_only"
    assert db.query(AlibabaFeedMessage).one().message_revision == 2
    assert safe_messages(db, first) == []
    assert safe_messages(db, new)[0]["text"] == "Edited synthetic"
    old = process(v11_store, v11_payload("older-replay", snapshot_revision=1))
    assert safe_messages(db, old) == []
    assert db.query(AlibabaFeedMessage).one().message_revision == 2


def test_same_metadata_allows_new_conversation(v11_store):
    first = process(v11_store, v11_payload())
    data = v11_payload("new-view", conversation_revision=2, message_revision=2)
    data["records"][0]["messages"][0]["text"] = "new body"
    new = process(v11_store, data)
    assert not first.is_current and new.is_current
    assert "VERSION_CONFLICT" not in new.issues


def test_equal_message_revision_different_body_invalidates_both(v11_store):
    first = process(v11_store, v11_payload())
    data = v11_payload("conflict")
    data["records"][0]["messages"][0]["text"] = "conflicting"
    second = process(v11_store, data)
    assert "CONVERSATION_VERSION_CONFLICT" in first.issues
    assert "MESSAGE_VERSION_CONFLICT" in second.issues
    assert safe_messages(v11_store[0], first) == safe_messages(v11_store[0], second) == []


@pytest.mark.parametrize("conv,msg", [(1, 2), (3, 1)])
def test_message_conversation_version_inversion_is_not_arrival_winner(v11_store, conv, msg):
    process(v11_store, v11_payload(conversation_revision=2, message_revision=2))
    data = v11_payload("inversion", conversation_revision=conv, message_revision=msg)
    if msg == 2:
        data["records"][0]["messages"][0]["message_revision"] = 3
    item = process(v11_store, data)
    row = v11_store[0].query(AlibabaFeedMessage).one()
    assert "VERSION_ORDER_CONFLICT" in item.issues
    assert row.message_revision == 2 and row.content["text"] == "Synthetic secret text"
    assert row.version_conflict


def test_partial_does_not_poison_complete_peer(v11_store):
    first = process(v11_store, v11_payload())
    data = v11_payload("partial")
    data["records"][0].update(detail_scraped=False, scrape_status="partial", messages=[])
    incomplete = process(v11_store, data)
    assert first.is_current and not incomplete.is_current
    assert "CONVERSATION_VERSION_CONFLICT" not in first.issues
    assert safe_messages(v11_store[0], first)


@pytest.mark.parametrize("changed_id", [True, False])
def test_source_order_collision_and_identity_reordering(v11_store, changed_id):
    first = process(v11_store, v11_payload())
    data = v11_payload("order", conversation_revision=2, message_revision=2)
    if changed_id:
        data["records"][0]["messages"][0]["message_id"] = "message-b"
    else:
        data["records"][0]["messages"][0]["source_order"] = 2
    item = process(v11_store, data)
    assert "MESSAGE_ORDER_CONFLICT" in item.issues
    assert safe_messages(v11_store[0], first) == []
    assert all(row.order_conflict for row in v11_store[0].query(AlibabaFeedMessage))


def test_tombstone_blocks_old_new_copies_and_legacy_future_replays(v11_store):
    db, source = v11_store
    legacy = process(v11_store, payload("legacy"))
    first = process(v11_store, v11_payload())
    data = v11_payload("withdraw", conversation_revision=2, message_revision=2)
    data["records"][0]["messages"][0].update(deleted_at="2026-11-05T05:10:00+08:00", text="")
    withdrawn = process(v11_store, data)
    assert source.legacy_identity_blocked
    assert safe_messages(db, first) == safe_messages(db, legacy) == safe_messages(db, withdrawn) == []
    replay = v11_payload("new-inquiry")
    replay["records"][0]["inquiry_id"] = "new-inquiry"
    assert safe_messages(db, process(v11_store, replay)) == []
    resurrect = v11_payload("resurrect", conversation_revision=3, message_revision=3)
    assert safe_messages(db, process(v11_store, resurrect)) == []
    row = db.query(AlibabaFeedMessage).one()
    assert row.content is None and row.tombstone_revision == 2
    assert safe_messages(db, process(v11_store, payload("legacy-replay"))) == []


def test_activity_window_uses_last_activity_of_old_inquiry(v11_store):
    data = v11_payload()
    data["records"][0]["created_at"] = "2023-01-01"
    data["run"]["window"]["basis"] = "conversation_last_activity_at"
    data["run"]["coverage"].update(selection="activity_window", activity_scan_complete=True,
                                  activity_window_start=data["run"]["window"]["start"],
                                  activity_window_end=data["run"]["window"]["end"])
    item = process(v11_store, data)
    assert item.window_result == "in_window" and item.is_current
    assert item.coverage["selection"] == "activity_window"


def test_metadata_conflict_and_clock_inversion(v11_store):
    first = process(v11_store, v11_payload())
    data = v11_payload("metadata-conflict")
    data["records"][0]["buyer"]["name"] = "different buyer"
    item = process(v11_store, data)
    assert "VERSION_CONFLICT" in item.issues and not first.is_current
    data = v11_payload("clock-back", snapshot_revision=2, conversation_revision=2)
    data["records"][0]["observed_at"] = "2026-11-05T05:19:00+08:00"
    item = process(v11_store, data)
    assert "VERSION_ORDER_CONFLICT" in item.issues and not item.is_current


@pytest.mark.parametrize("missing", ["conversation", "message"])
def test_unresolved_identity_withdrawal_blocks_legacy_without_guessing(v11_store, missing):
    legacy = process(v11_store, payload("legacy"))
    data = v11_payload()
    record = data["records"][0]
    if missing == "conversation":
        record.update(conversation_id=None, conversation_revision=None)
    else:
        record["messages"][0]["message_id"] = None
    record["messages"][0]["deleted_at"] = "2026-11-05T05:10:00+08:00"
    item = process(v11_store, data)
    assert v11_store[1].legacy_identity_blocked
    assert safe_messages(v11_store[0], item) == safe_messages(v11_store[0], legacy) == []
    assert v11_store[0].query(AlibabaFeedMessage).count() == 0


def test_expired_fence_rolls_back_normalized_message_and_source_redaction(v11_store, monkeypatch):
    data = v11_payload()
    data["records"][0]["messages"][0]["deleted_at"] = "2026-11-05T05:10:00+08:00"
    ingest(v11_store, data)
    db = v11_store[0]
    batch_id, token = claim_batch(db, now=NOW, lease_seconds=10)
    elapsed = [NOW]
    monkeypatch.setattr("app.alibaba_feed.worker.beijing_now", lambda: elapsed[0])
    def after_flush(session, context):
        if any(isinstance(row, AlibabaFeedMessage) for row in session.new):
            elapsed[0] = NOW + timedelta(seconds=11)
    event.listen(db, "after_flush", after_flush)
    try:
        with pytest.raises(FeedError, match="LEASE_LOST"):
            process_item(db, batch_id, token, 0, data["records"][0], data["run"]["window"],
                         schema_version=data["schema"], run_coverage=data["run"]["coverage"])
        assert db.query(AlibabaFeedMessage).count() == db.query(AlibabaFeedItem).count() == 0
        assert not db.query(AlibabaFeedSource).one().legacy_identity_blocked
    finally:
        event.remove(db, "after_flush", after_flush)


def test_snapshot_clock_respects_offset_and_beijing_midnight(v11_store, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    data = v11_payload()
    data["records"][0]["observed_at"] = "2026-11-04T16:01:00Z"
    item = process(v11_store, data)
    assert item.observed_at.isoformat() == "2026-11-05T00:01:00"


def test_invalid_snapshot_does_not_poison_complete_version(v11_store):
    data = v11_payload("outside", snapshot_revision=99, conversation_revision=99, message_revision=99)
    data["records"][0]["created_at"] = "2023-01-01"
    invalid = process(v11_store, data)
    assert invalid.outcome == "quarantined"
    assert v11_store[0].query(AlibabaFeedMessage).count() == 0
    valid = process(v11_store, v11_payload())
    assert valid.is_current and safe_messages(v11_store[0], valid)


def test_latest_only_conflicting_tail_invalidates_same_conversation_revision(v11_store):
    data = v11_payload()
    data["records"][0]["coverage"]["history_complete"] = False
    first = process(v11_store, data)
    other = deepcopy(data)
    other["run"]["run_id"] = "different-tail"
    other["records"][0]["inquiry_id"] = "different-inquiry"
    other["records"][0]["messages"][0].update(message_id="message-b", source_order=2)
    second = process(v11_store, other)
    assert "CONVERSATION_VERSION_CONFLICT" in first.issues
    assert "CONVERSATION_VERSION_CONFLICT" in second.issues
    assert safe_messages(v11_store[0], first) == safe_messages(v11_store[0], second) == []


def test_latest_only_different_history_same_tail_is_not_conflicting(v11_store):
    data = v11_payload()
    data["records"][0]["coverage"]["history_complete"] = False
    data["records"][0]["messages"][0]["source_order"] = 2
    first = process(v11_store, data)
    other = deepcopy(data)
    other["run"]["run_id"] = "more-history"
    old = deepcopy(other["records"][0]["messages"][0])
    old.update(message_id="old-message", source_order=1, ref="old-ref")
    other["records"][0]["messages"].append(old)
    second = process(v11_store, other)
    assert "CONVERSATION_VERSION_CONFLICT" not in first.issues
    assert "CONVERSATION_VERSION_CONFLICT" not in second.issues


def test_shared_message_higher_revision_cannot_move_observation_backward(v11_store):
    first = process(v11_store, v11_payload())
    data = v11_payload("backwards", conversation_revision=2, message_revision=2)
    data["records"][0].update(inquiry_id="other-inquiry", observed_at="2026-11-05T05:19:00+08:00")
    data["records"][0]["messages"][0]["text"] = "too early"
    item = process(v11_store, data)
    assert "VERSION_ORDER_CONFLICT" in item.issues
    assert v11_store[0].query(AlibabaFeedMessage).one().message_revision == 1
    assert safe_messages(v11_store[0], first) == []
