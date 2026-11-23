"""upsert、状态事件、缺席不删除、指纹相同跳过、外部偏移时间换算北京时间。"""
from datetime import datetime

from app.devlog.ingest_service import ingest
from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogSyncRun
from app.devlog.schemas import IngestIn


def item(key="branch:codex/a", status="pending_merge", fingerprint="a" * 64, **extra):
    return {"key": key, "title": "Add thing", "type": "feature", "module": "invoice", "agent": "codex",
            "status": status, "status_at": "2026-11-23T09:00:00", "last_activity_at": "2026-11-23T09:00:00",
            "fingerprint": fingerprint, "evidences": [{"kind": "commit", "ref": "c" * 40, "at": "2026-11-23T09:00:00"}],
            **extra}


def run(*items):
    return IngestIn.model_validate({"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
                                    "sources": [{"name": name, "ok": True} for name in ("git", "fetch", "releases")], "items": list(items)})


def test_first_ingest_creates_item_event_and_sync_run(db):
    result = ingest(db, run(item()))
    assert result == {"created": 1, "updated": 0, "unchanged": 0, "transitions": 1, "failed": []}
    event = db.query(DevlogItemEvent).one()
    assert (event.from_status, event.to_status) == (None, "pending_merge")
    assert db.query(DevlogEvidence).count() == 1
    assert db.query(DevlogSyncRun).one().item_count == 1


def test_status_change_records_transition_and_same_fingerprint_is_skipped(db):
    ingest(db, run(item()))
    assert ingest(db, run(item()))["unchanged"] == 1
    result = ingest(db, run(item(status="released", fingerprint="b" * 64, released_revision="d" * 40,
                                 status_at="2026-11-23T14:02:00")))
    assert result["transitions"] == 1
    last = db.query(DevlogItemEvent).order_by(DevlogItemEvent.id.desc()).first()
    assert (last.from_status, last.to_status, last.occurred_at) == ("pending_merge", "released", datetime(2026, 11, 23, 14, 2))


def test_absent_items_are_not_deleted_or_downgraded(db):
    ingest(db, run(item(), item(key="branch:codex/b")))
    ingest(db, run(item()))
    assert db.query(DevlogItem).count() == 2
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/b").one().superseded is False


def test_full_snapshot_marks_absent_items_superseded_and_revives_on_return(db):
    ingest(db, run(item(), item(key="branch:codex/b")))
    full = run(item())
    full.snapshot = True
    ingest(db, full)
    row = db.query(DevlogItem).filter_by(item_key="branch:codex/b").one()
    assert row.superseded is True and row.status == "pending_merge"   # 不删除、不降级
    back = run(item(), item(key="branch:codex/b"))
    back.snapshot = True
    ingest(db, back)
    db.refresh(row)
    assert row.superseded is False


def test_snapshot_ignored_when_git_source_failed(db):
    ingest(db, run(item(), item(key="branch:codex/b")))
    broken = IngestIn.model_validate({"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
                                      "snapshot": True, "sources": [{"name": "git", "ok": False}], "items": [item()]})
    ingest(db, broken)
    assert db.query(DevlogItem).filter_by(superseded=True).count() == 0


def test_offset_times_convert_to_beijing_across_midnight(db):
    # 非东八区来源的 16:30Z = 北京次日 00:30，必须落在 11-23
    ingest(db, run(item(status_at="2026-11-22T16:30:00+00:00", last_activity_at="2026-11-22T16:30:00Z")))
    row = db.query(DevlogItem).one()
    assert row.status_at == datetime(2026, 11, 23, 0, 30)
    assert row.status_at.tzinfo is None


def test_one_bad_item_does_not_block_others(db, monkeypatch):
    import app.devlog.ingest_service as service
    original = service._upsert

    def flaky(db_, item_in, now):
        if item_in.key.endswith("/bad"):
            raise RuntimeError("boom")
        return original(db_, item_in, now)

    monkeypatch.setattr(service, "_upsert", flaky)
    result = ingest(db, run(item(key="branch:codex/bad"), item(key="branch:codex/good")))
    assert result["failed"] == ["branch:codex/bad"] and result["created"] == 1
    assert db.query(DevlogSyncRun).one().failed_keys == ["branch:codex/bad"]
