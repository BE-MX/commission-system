"""Isolated SQLite tests: immutable ingestion, record quality and fencing."""
import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.alibaba_feed.canonical import parse_json
from app.alibaba_feed.errors import FeedError
from app.alibaba_feed.models import AlibabaFeedBatch, AlibabaFeedItem, AlibabaFeedSource
from app.alibaba_feed.service import accept_batch, get_receipt
from app.alibaba_feed.validation import parse_envelope, record_quality
from app.alibaba_feed.worker import claim_batch, process_item, process_next_batch

NOW = datetime(2026, 11, 5, 12)


def payload(run_id="run-a", observed="2026-11-05T05:20:00+08:00"):
    return {
        "schema": "ark_alibaba_feed_v1",
        "run": {"run_id": run_id, "source": "test", "delivery": "file_only_p0", "status": "ok", "error": None,
                "window": {"start": "2026-11-04T05:00:00+08:00", "end": "2026-11-05T05:00:00+08:00", "timezone": "Asia/Shanghai", "interval": "[start,end)", "basis": "inquiry_created_at"},
                "scraped_at": observed, "reply_status_snapshot_at": observed},
        "stats": {"records_total": 1, "inquiry_records": 1, "tm_raw": 0},
        "by_assignee": [{"assignee_name": None, "counts": {"total": 1, "replied": 0, "pending": 1, "unreplied": 0, "unknown": 0}, "inquiry_ids": ["item-a"]}],
        "records": [{"inquiry_id": "item-a", "type": "inquiry", "buyer": {"name": "Synthetic"}, "assignee_name": None,
                     "created_at": "2026-11-04", "created_at_precision": "day", "reply_status": "pending",
                     "detail_scraped": True, "scrape_status": "success", "trust": "untrusted_external",
                     "messages": [{"ref": "m1", "dir": "buyer", "at": "2026-11-04 06:00", "text": "Synthetic secret text"}]}],
    }


def raw(data):
    return json.dumps(data).encode()


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr("app.alibaba_feed.auth.recheck_feed_principal", lambda *args, **kwargs: None)
    engine = create_engine("sqlite://")
    for model in (AlibabaFeedSource, AlibabaFeedBatch, AlibabaFeedItem):
        model.__table__.create(engine)
    with Session(engine, autoflush=False) as db:
        source = AlibabaFeedSource(source_account_uid="test-shop", integration_app_id=1, name="Synthetic", ingest_enabled=True, consent_state="authorized")
        db.add(source)
        db.commit()
        yield db, source
    engine.dispose()


def ingest(store, data):
    db, source = store
    return accept_batch(db, source, raw(data), data["run"]["run_id"], now=NOW)


def test_canonical_replay_and_mismatch(store):
    data = payload()
    first = ingest(store, data)
    second = accept_batch(store[0], store[1], json.dumps(data, sort_keys=True, indent=4).encode(), "run-a", now=NOW)
    assert second["batch_id"] == first["batch_id"] and second["replayed"]
    data["records"][0]["messages"][0]["text"] = "different"
    with pytest.raises(FeedError, match="IDEMPOTENCY_PAYLOAD_MISMATCH"):
        ingest(store, data)
    assert store[0].query(AlibabaFeedBatch).count() == 1


@pytest.mark.parametrize("body", [b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":NaN}', b'{"a":"\\ud800"}', b'[' * 34 + b'0' + b']' * 34])
def test_noncanonical_json_rejected(body):
    with pytest.raises(FeedError):
        parse_json(body)


def test_window_offset_and_safe_receipt(store, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    receipt = ingest(store, payload())
    process_next_batch(store[0], now=NOW)
    result = get_receipt(store[0], "test-shop", batch_id=receipt["batch_id"])
    assert result["quality"]["window_uncertain"] == 1
    assert result["outcomes"]["current_updated"] == 1
    assert "Synthetic secret text" not in json.dumps(result)
    with pytest.raises(FeedError, match="BATCH_NOT_FOUND"):
        get_receipt(store[0], "other-shop", batch_id=receipt["batch_id"])
    data = payload()
    record = data["records"][0]
    record["created_at_precision"] = "minute"
    record["created_at"] = "2026-11-03T21:00:00Z"
    assert record_quality(record, data["run"]["window"])[0] == "in_window"


def test_failed_and_partial_do_not_erase_complete(store):
    ingest(store, payload())
    process_next_batch(store[0], now=NOW)
    partial = payload("partial", "2026-11-05T06:00:00+08:00")
    partial["run"]["status"] = "partial"
    partial["records"][0].update(detail_scraped=False, scrape_status="failed", messages=[])
    ingest(store, partial)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).one().snapshot["messages"]
    failed = payload("failed")
    failed["run"].update(status="failed", error="Synthetic failure")
    failed.update(records=[], stats={"records_total": 0, "inquiry_records": 0, "tm_raw": 0}, by_assignee=[])
    result = ingest(store, failed)
    process_next_batch(store[0], now=NOW)
    assert get_receipt(store[0], "test-shop", batch_id=result["batch_id"])["processing_state"] == "recorded_source_failure"
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).count() == 1


def test_late_arrival_and_equal_version_conflict(store):
    ingest(store, payload())
    process_next_batch(store[0], now=NOW)
    old = payload("old", "2026-11-05T05:19:00+08:00")
    old["records"][0]["messages"][0]["text"] = "older"
    ingest(store, old)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).one().snapshot["messages"][0]["text"] == "Synthetic secret text"
    conflict = payload("conflict")
    conflict["records"][0]["messages"][0]["text"] = "conflicting observation"
    ingest(store, conflict)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).count() == 0
    assert store[0].query(AlibabaFeedItem).filter_by(outcome="quarantined").count() == 1


def test_stale_worker_cannot_commit_and_resume_same_batch(store):
    data = payload()
    receipt = ingest(store, data)
    db = store[0]
    batch_id, old_token = claim_batch(db, now=NOW, lease_seconds=10)
    same_id, new_token = claim_batch(db, now=NOW + timedelta(seconds=11))
    assert same_id == batch_id == receipt["batch_id"] and new_token != old_token
    with pytest.raises(FeedError, match="LEASE_LOST"):
        process_item(db, batch_id, old_token, 0, data["records"][0], data["run"]["window"], now=NOW + timedelta(seconds=12))
    assert db.query(AlibabaFeedItem).count() == 0
    process_item(db, batch_id, new_token, 0, data["records"][0], data["run"]["window"], now=NOW + timedelta(seconds=12))
    process_item(db, batch_id, new_token, 0, data["records"][0], data["run"]["window"], now=NOW + timedelta(seconds=13))
    assert db.query(AlibabaFeedItem).count() == 1


def test_duplicate_ids_all_quarantined_and_pending_limit(store):
    data = payload()
    data["records"].append(copy.deepcopy(data["records"][0]))
    ingest(store, data)
    ingest(store, payload("second"))
    with pytest.raises(FeedError, match="SOURCE_BACKPRESSURE"):
        ingest(store, payload("third"))
    assert ingest(store, data)["replayed"]
    process_next_batch(store[0], now=NOW)
    batch = store[0].query(AlibabaFeedBatch).filter_by(run_id="run-a").one()
    if batch.status == "queued":
        process_next_batch(store[0], now=NOW)
    items = store[0].query(AlibabaFeedItem).filter_by(batch_id=batch.id).all()
    assert len(items) == 2 and all(item.outcome == "quarantined" for item in items)


def test_disabled_source_before_worker_is_quarantined(store):
    ingest(store, payload())
    store[1].ingest_enabled = False
    store[0].commit()
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).one().outcome == "quarantined"


def test_rate_limit_counts_completed_batches(store):
    config = SimpleNamespace(ALIBABA_FEED_SOURCE_REQUESTS_PER_MINUTE=1)
    ingest(store, payload())
    process_next_batch(store[0], now=NOW)
    with pytest.raises(FeedError, match="SOURCE_BACKPRESSURE"):
        accept_batch(store[0], store[1], raw(payload("second")), "second", now=NOW, limits=config)


def test_stats_and_unknown_fields_are_not_silently_trusted(store):
    data = payload()
    data["stats"]["records_total"] = 99
    ingest(store, data)
    process_next_batch(store[0], now=NOW)
    batch = store[0].query(AlibabaFeedBatch).one()
    assert batch.status == "completed_with_issues"
    assert batch.issues[0]["code"] == "STATS_MISMATCH"
    data["records"][0]["customer_id"] = "forged"
    with pytest.raises(FeedError):
        parse_envelope(raw(data), "run-a", NOW)


def test_frozen_message_limit_quarantines_without_truncation(store):
    data = payload()
    config = SimpleNamespace(ALIBABA_FEED_MAX_MESSAGE_BYTES=4)
    accepted = accept_batch(store[0], store[1], raw(data), "run-a", now=NOW, limits=config)
    assert accepted["processing_state"] == "queued"
    process_next_batch(store[0], now=NOW)
    item = store[0].query(AlibabaFeedItem).one()
    assert item.outcome == "quarantined"
    assert "MESSAGE_TOO_LARGE" in item.issues
    assert item.snapshot["messages"][0]["text"] == data["records"][0]["messages"][0]["text"]


def test_recovery_preserves_committed_item_and_finishes_same_batch(store):
    data = payload()
    accepted = ingest(store, data)
    batch_id, token = claim_batch(store[0], now=NOW, lease_seconds=10)
    process_item(store[0], batch_id, token, 0, data["records"][0], data["run"]["window"], now=NOW, lease_seconds=10)
    process_next_batch(store[0], now=NOW + timedelta(seconds=11))
    result = get_receipt(store[0], "test-shop", batch_id=accepted["batch_id"])
    assert result["processed_records"] == 1
    assert result["processing_state"] == "completed_with_issues"
    assert store[0].query(AlibabaFeedItem).count() == 1


def test_three_worker_failures_produce_safe_terminal_receipt(store, monkeypatch):
    ingest(store, payload())

    def fail(*args, **kwargs):
        raise RuntimeError("private error content")

    monkeypatch.setattr("app.alibaba_feed.worker.process_item", fail)
    for attempt in range(3):
        with pytest.raises(RuntimeError):
            process_next_batch(store[0], now=NOW + timedelta(seconds=attempt * 11), lease_seconds=10)
    result = get_receipt(store[0], "test-shop", run_id="run-a")
    assert result["processing_state"] == "processing_failed"
    assert "private error content" not in json.dumps(result)


def test_minute_window_beijing_midnight_from_utc():
    data = payload()
    data["run"]["window"].update(start="2026-11-05T00:00:00+08:00", end="2026-11-06T00:00:00+08:00")
    record = data["records"][0]
    record.update(created_at="2026-11-04T16:00:00Z", created_at_precision="minute")
    assert record_quality(record, data["run"]["window"])[0] == "in_window"
    record["created_at"] = "2026-11-05T16:00:00Z"
    assert record_quality(record, data["run"]["window"])[0] == "out_of_window"


def test_conflict_restores_previous_current_without_autoflush(store):
    old = payload("older", "2026-11-05T05:19:00+08:00")
    ingest(store, old)
    process_next_batch(store[0], now=NOW)
    newer = payload("newer")
    newer["records"][0]["messages"][0]["text"] = "newer"
    ingest(store, newer)
    process_next_batch(store[0], now=NOW)
    conflict = payload("conflict")
    conflict["records"][0]["messages"][0]["text"] = "conflict"
    ingest(store, conflict)
    process_next_batch(store[0], now=NOW)
    current = store[0].query(AlibabaFeedItem).filter_by(is_current=True).one()
    assert current.observed_at == datetime(2026, 11, 5, 5, 19)


def test_out_of_range_record_is_isolated_and_envelope_rejected(store):
    data = payload()
    bad = copy.deepcopy(data["records"][0])
    bad.update(inquiry_id="invalid-date", created_at="9999-12-31")
    data["records"].append(bad)
    ingest(store, data)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).count() == 1
    assert store[0].query(AlibabaFeedItem).filter_by(outcome="quarantined").count() == 1
    data["run"]["scraped_at"] = "9999-12-31T23:59:59-12:00"
    with pytest.raises(FeedError):
        parse_envelope(raw(data), "run-a", NOW)


@pytest.mark.parametrize("phase", ["batch_lock", "source_lock", "flush"])
def test_elapsed_lock_or_flush_time_cannot_extend_expired_lease(store, monkeypatch, phase):
    data = payload()
    ingest(store, data)
    db = store[0]
    batch_id, token = claim_batch(db, now=NOW, lease_seconds=10)
    elapsed = [NOW]
    monkeypatch.setattr("app.alibaba_feed.worker.beijing_now", lambda: elapsed[0])

    def before_execute(connection, cursor, statement, parameters, context, executemany):
        if phase == "batch_lock" and "FROM ark_alibaba_feed_batches" in statement:
            elapsed[0] = NOW + timedelta(seconds=11)
        if phase == "source_lock" and "FROM ark_alibaba_feed_sources" in statement:
            elapsed[0] = NOW + timedelta(seconds=11)

    def after_flush(session, context):
        if phase == "flush":
            elapsed[0] = NOW + timedelta(seconds=11)

    event.listen(db.bind, "before_cursor_execute", before_execute)
    event.listen(db, "after_flush", after_flush)
    try:
        with pytest.raises(FeedError, match="LEASE_LOST"):
            process_item(db, batch_id, token, 0, data["records"][0], data["run"]["window"])
        assert db.query(AlibabaFeedItem).count() == 0
    finally:
        event.remove(db.bind, "before_cursor_execute", before_execute)
        event.remove(db, "after_flush", after_flush)


def test_record_ids_preserve_case_and_trailing_spaces(store):
    data = payload()
    for identifier in ("ITEM-A", "item-a "):
        record = copy.deepcopy(data["records"][0])
        record["inquiry_id"] = identifier
        data["records"].append(record)
    ingest(store, data)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).count() == 3
    from sqlalchemy.dialects.mysql import dialect
    assert "utf8mb4_0900_bin" in AlibabaFeedItem.__table__.c.inquiry_id.type.compile(dialect=dialect())


def test_existing_receipt_reclassifies_after_later_version_conflict(store):
    data = payload()
    data["records"][0].update(created_at="2026-11-04T06:00:00+08:00", created_at_precision="minute")
    original = copy.deepcopy(data)
    first = ingest(store, data)
    process_next_batch(store[0], now=NOW)
    assert get_receipt(store[0], "test-shop", batch_id=first["batch_id"])["processing_state"] == "completed"
    data["run"]["run_id"] = "conflict"
    data["records"][0]["messages"][0]["text"] = "different observation"
    ingest(store, data)
    process_next_batch(store[0], now=NOW)
    assert get_receipt(store[0], "test-shop", batch_id=first["batch_id"])["processing_state"] == "completed_with_issues"
    page = get_receipt(store[0], "test-shop", run_id="run-a", issue_offset=999)
    assert page["issues"] == [] and page["issues_total"] > 0
    assert page["processing_state"] == "completed_with_issues"
    replay = ingest(store, original)
    assert replay["replayed"] and replay["processing_state"] == "completed_with_issues"


@pytest.mark.parametrize("incomplete_first", [False, True])
def test_same_observation_incomplete_snapshot_never_displaces_complete(store, incomplete_first):
    complete = payload("complete")
    incomplete = payload("incomplete")
    incomplete["run"]["status"] = "partial"
    incomplete["records"][0].update(detail_scraped=False, scrape_status="failed", messages=[])
    ordered = (incomplete, complete) if incomplete_first else (complete, incomplete)
    for data in ordered:
        ingest(store, data)
        process_next_batch(store[0], now=NOW)
    current = store[0].query(AlibabaFeedItem).filter_by(is_current=True).one()
    assert current.snapshot["messages"][0]["text"] == "Synthetic secret text"
    incomplete_batch = store[0].query(AlibabaFeedBatch).filter_by(run_id="incomplete").one()
    partial_item = store[0].query(AlibabaFeedItem).filter_by(batch_id=incomplete_batch.id).one()
    assert partial_item.outcome == "history_only"
    assert partial_item.issues == ["DETAIL_INCOMPLETE", "WINDOW_PRECISION_INSUFFICIENT"]
    assert all("VERSION_CONFLICT" not in item.issues for item in store[0].query(AlibabaFeedItem))


@pytest.mark.parametrize("invalid_kind", ["duplicate", "outside"])
def test_invalid_observation_cannot_poison_later_complete_snapshot(store, invalid_kind):
    invalid = payload("invalid", "2026-11-05T05:21:00+08:00")
    if invalid_kind == "duplicate":
        invalid["records"].append(copy.deepcopy(invalid["records"][0]))
    else:
        invalid["records"][0]["created_at"] = "2026-11-01"
    ingest(store, invalid)
    process_next_batch(store[0], now=NOW)
    complete = payload("complete")
    ingest(store, complete)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).count() == 1
    same_time = payload("same-time", "2026-11-05T05:21:00+08:00")
    ingest(store, same_time)
    process_next_batch(store[0], now=NOW)
    assert store[0].query(AlibabaFeedItem).filter_by(is_current=True).one().observed_at == datetime(2026, 11, 5, 5, 21)
