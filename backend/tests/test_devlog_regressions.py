"""Boundary regressions for the devlog ingestion and reporting contract."""
from datetime import date, datetime
import hashlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import get_settings
from app.devlog.ingest_service import ingest
from app.devlog.models import DevlogItem, DevlogItemEvent, DevlogRelease, DevlogSyncRun
from app.devlog.query_service import health, summary
from app.devlog.release_service import backfill, record_release
from app.devlog.schemas import IngestIn, ReleaseIn
from tests.test_devlog_ingest import item, run
from tests.test_devlog_api import client, TOKEN, BODY


def test_release_identity_conflict_is_not_silently_accepted(db):
    values = dict(revision="a" * 40, release_id="same", scope="office-and-cloud",
                  released_at=datetime(2026, 11, 23), source="deployer")
    assert record_release(db, **values)
    with pytest.raises(HTTPException) as err:
        record_release(db, **{**values, "revision": "b" * 40})
    assert err.value.status_code == 409
    assert db.query(DevlogRelease).one().revision == "a" * 40


def test_release_retry_preserves_original_time(db):
    values = dict(revision="a" * 40, release_id="same", scope="office-and-cloud", source="deployer")
    record_release(db, **values, released_at=datetime(2026, 11, 23, 1))
    assert not record_release(db, **values, released_at=datetime(2026, 11, 23, 2))
    assert db.query(DevlogRelease).one().released_at.hour == 1


def test_backfill_failure_rolls_back_batch(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_BACKFILL_ENABLED", True)
    initial = ReleaseIn(revision="a" * 40, release_id="existing", scope="office-and-cloud", released_at="2026-11-23T00:00:00")
    backfill(db, [initial])
    new = initial.model_copy(update={"release_id": "new"})
    conflict = initial.model_copy(update={"revision": "b" * 40})
    with pytest.raises(HTTPException):
        backfill(db, [new, conflict])
    assert [row.release_id for row in db.query(DevlogRelease).all()] == ["existing"]


def test_delayed_snapshot_rejected_without_overwriting(db):
    ingest(db, run(item()))
    old = run(item(status="dev"))
    old.started_at = datetime(2026, 11, 23, 14)
    old.finished_at = datetime(2026, 11, 23, 14, 1)
    old.snapshot = True
    with pytest.raises(HTTPException) as err:
        ingest(db, old)
    assert err.value.status_code == 409
    assert db.query(DevlogItem).one().status == "pending_merge"
    assert db.query(DevlogSyncRun).count() == 1


def test_partial_failure_snapshot_does_not_hide_absent_items(db, monkeypatch):
    import app.devlog.ingest_service as svc
    ingest(db, run(item(key="branch:codex/retained")))
    original = svc._upsert
    def fail_one(db_, value, now):
        if value.key.endswith("bad"):
            raise RuntimeError("injected")
        return original(db_, value, now)
    monkeypatch.setattr(svc, "_upsert", fail_one)
    payload = run(item(key="branch:codex/good"), item(key="branch:codex/bad"))
    payload.snapshot = True
    result = ingest(db, payload)
    assert result["failed"] == ["branch:codex/bad"]
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/retained").one().superseded is False
    assert health(db)["is_stale"] is True


def test_kpi_counts_only_released_data_and_unique_release_items(db):
    ingest(db, run(item(type="data")))
    args = dict(start=date(2026, 11, 23), end=date(2026, 11, 23))
    assert summary(db, **args)["kpis"]["data"] == 0
    ingest(db, run(item(type="data", status="released", fingerprint="b" * 64)))
    row = db.query(DevlogItem).one()
    db.add(DevlogItemEvent(item_id=row.id, to_status="released", occurred_at=datetime(2026, 11, 23, 10)))
    db.flush()
    assert summary(db, **args)["kpis"]["data"] == 1


def test_beijing_event_at_midnight_inclusive_end_exclusive(db):
    ingest(db, run(item(key="branch:codex/start", status="released", status_at="2026-11-22T16:00:00Z"),
                   item(key="branch:codex/end", status="released", status_at="2026-11-23T16:00:00Z")))
    data = summary(db, start=date(2026, 11, 23), end=date(2026, 11, 23))
    assert data["kpis"]["features"] == 1
    assert [i["key"] for i in data["columns"]["released"]] == ["branch:codex/start"]


def test_maximum_date_is_rejected_not_overflow(db):
    with pytest.raises(HTTPException) as err:
        summary(db, start=date.max, end=date.max)
    assert err.value.status_code == 422


def test_health_six_hour_boundary_uses_unrounded_age(db, monkeypatch):
    import app.devlog.query_service as qs
    ingest(db, run())
    monkeypatch.setattr(qs, "beijing_now", lambda: datetime(2026, 11, 23, 21, 1, 1))
    assert health(db)["is_stale"] is True


def test_recent_failed_source_is_not_healthy(db, monkeypatch):
    import app.devlog.query_service as qs
    payload = run()
    payload.sources[0].ok = False
    ingest(db, payload)
    monkeypatch.setattr(qs, "beijing_now", lambda: datetime(2026, 11, 23, 15, 2))
    assert health(db)["is_stale"] is True


@pytest.mark.parametrize("patch", [
    {"sources": [{"name": "git", "ok": True}, {"name": "git", "ok": False}]},
    {"finished_at": "2026-11-23T14:00:00"},
    {"items": [item(evidences=[{"kind": "commit", "ref": "not-a-sha", "at": "2026-11-23T00:00:00"}])]},
])
def test_reject_ambiguous_or_invalid_payload(patch):
    with pytest.raises(ValidationError):
        IngestIn.model_validate({**BODY, **patch})


def test_forged_small_content_length_cannot_bypass_limit(db, monkeypatch):
    import app.devlog.machine_auth as auth
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    monkeypatch.setattr(auth, "MAX_BODY_BYTES", 128)
    with client(db) as c:
        response = c.post("/api/devlog/ingest", content=b" " * 129,
                          headers={"X-Devlog-Token": TOKEN, "Content-Length": "1", "Content-Type": "application/json"})
    assert response.status_code == 413


def test_query_rejects_unknown_filters(db):
    with client(db) as c:
        response = c.get("/api/devlog/summary", params={"start": "2026-11-23", "end": "2026-11-23", "type": "transcript"})
    assert response.status_code == 422



@pytest.mark.parametrize("source", ["fetch", "releases"])
def test_failed_source_prevents_downgrade_and_snapshot_hiding(db, source):
    ingest(db, run(item(status="released"), item(key="branch:codex/absent")))
    payload = run(item(status="pending_merge", fingerprint="b" * 64))
    next(state for state in payload.sources if state.name == source).ok = False
    payload.snapshot = True
    ingest(db, payload)
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/a").one().status == "released"
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/absent").one().superseded is False


def test_superseded_keeps_historical_events_and_release_kpi(db):
    ingest(db, run(item(status="released")))
    empty = run()
    empty.snapshot = True
    ingest(db, empty)
    data = summary(db, start=date(2026, 11, 23), end=date(2026, 11, 23))
    assert data["kpis"]["features"] == 1
    assert len(data["timeline"][0]["entries"]) == 1


def test_pending_kpi_excludes_stale_like_pending_list(db):
    from app.devlog.query_service import pending_list
    ingest(db, run(item(status="pending_release", stale=True),
                   item(key="branch:codex/active", status="pending_release")))
    data = summary(db, start=date(2026, 11, 23), end=date(2026, 11, 23))
    assert data["kpis"]["pending_release"] == 1
    assert data["kpis"]["stale"] == 1
    assert len(pending_list(db)) == 1



def test_stale_columns_are_complete_and_not_duplicated(db):
    ingest(db, run(item(status="pending_release", stale=True),
                   item(key="branch:codex/stale-dev", status="dev", stale=True)))
    data = summary(db, start=date(2026, 11, 23), end=date(2026, 11, 23))
    assert data["columns"]["dev"] == []
    assert data["columns"]["committed"] == []
    assert len(data["stale_columns"]["dev"]) == 1
    assert len(data["stale_columns"]["committed"]) == 1
    assert len(data["timeline"][0]["entries"]) == 2


def test_hotfix_and_preconditions_update_even_if_fingerprint_reused(db):
    ingest(db, run(item()))
    result = ingest(db, run(item(unmerged_hotfix=True, preconditions={"config_keys": ["NEW_CONFIG"]})))
    assert result["updated"] == 1
    assert db.query(DevlogItem).one().unmerged_hotfix is True
    assert db.query(DevlogItem).one().preconditions["config_keys"] == ["NEW_CONFIG"]



def test_mysql_ingest_lock_is_held_across_commit_and_released_on_failure(monkeypatch):
    from unittest.mock import MagicMock
    import app.devlog.ingest_service as svc
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "mysql"
    connection = db.get_bind.return_value.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = 1
    monkeypatch.setattr(svc, "_ingest", lambda *_: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError):
        ingest(db, run())
    calls = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert calls == ["SELECT GET_LOCK(:name, 5)", "SELECT RELEASE_LOCK(:name)"]


def test_mysql_lock_timeout_never_starts_ingestion(monkeypatch):
    from unittest.mock import MagicMock
    import app.devlog.ingest_service as svc
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "mysql"
    connection = db.get_bind.return_value.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = 0
    worker = MagicMock()
    monkeypatch.setattr(svc, "_ingest", worker)
    with pytest.raises(HTTPException) as err:
        ingest(db, run())
    assert err.value.status_code == 409
    worker.assert_not_called()


def test_commit_failure_rolls_back_all_ingested_items(db, monkeypatch):
    def fail():
        raise RuntimeError("commit failed")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        ingest(db, run(item()))
    assert db.query(DevlogItem).count() == 0
    assert db.query(DevlogItemEvent).count() == 0


def test_invalid_ledger_input_fails_without_opening_session(monkeypatch, capsys):
    import io
    from unittest.mock import MagicMock
    from app.devlog import ledger_cli
    factory = MagicMock()
    monkeypatch.setattr(ledger_cli, "SessionLocal", factory)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"secret": "not-allowed"}'))
    assert ledger_cli.main() == 1
    factory.assert_not_called()
    assert "not-allowed" not in capsys.readouterr().out



def _complete_run(db, hour, *, snapshot=True, source_ok=True):
    payload = run()
    payload.started_at = datetime(2026, 11, 23, hour)
    payload.finished_at = datetime(2026, 11, 23, hour, 1)
    payload.snapshot = snapshot
    next(state for state in payload.sources if state.name == "fetch").ok = source_ok
    ingest(db, payload)


def _ledger_at(db, identity, *, created_at, released_at=None, scope="office-and-cloud"):
    db.add(DevlogRelease(revision="a" * 40, release_id=identity, scope=scope,
                        released_at=released_at or created_at, source="backfill", created_at=created_at))
    db.commit()


def test_ledger_pending_uses_insert_time_for_historical_backfill(db):
    _complete_run(db, 10)
    _ledger_at(db, "historical", created_at=datetime(2026, 11, 23, 11),
               released_at=datetime(2026, 10, 1))
    assert health(db)["ledger_pending_check"] is True
    _complete_run(db, 12)
    assert health(db)["ledger_pending_check"] is False


def test_ledger_insert_during_collection_stays_pending_until_next_complete_run(db):
    _complete_run(db, 10)
    _ledger_at(db, "during", created_at=datetime(2026, 11, 23, 10, 0, 30))
    assert health(db)["ledger_pending_check"] is True
    _complete_run(db, 11)
    assert health(db)["ledger_pending_check"] is False


@pytest.mark.parametrize("kwargs", [{"snapshot": False}, {"source_ok": False}])
def test_incomplete_collection_does_not_clear_ledger_pending(db, kwargs):
    _complete_run(db, 10)
    _ledger_at(db, "new", created_at=datetime(2026, 11, 23, 11))
    _complete_run(db, 12, **kwargs)
    assert health(db)["ledger_pending_check"] is True
    _complete_run(db, 13)
    assert health(db)["ledger_pending_check"] is False


def test_never_synced_and_cloud_only_do_not_show_ledger_pending(db):
    _ledger_at(db, "global", created_at=datetime(2026, 11, 23, 9))
    assert health(db)["ledger_pending_check"] is False
    _complete_run(db, 10)
    _ledger_at(db, "cloud", created_at=datetime(2026, 11, 23, 11), scope="cloud-only")
    assert health(db)["ledger_pending_check"] is False


def test_item_failure_does_not_acknowledge_new_ledger(db, monkeypatch):
    import app.devlog.ingest_service as svc
    _complete_run(db, 10)
    _ledger_at(db, "new", created_at=datetime(2026, 11, 23, 11))
    payload = run(item())
    payload.snapshot = True
    def fail(*_):
        raise RuntimeError("injected")
    monkeypatch.setattr(svc, "_upsert", fail)
    ingest(db, payload)
    assert health(db)["ledger_pending_check"] is True
    assert db.query(DevlogSyncRun).order_by(DevlogSyncRun.id.desc()).first().snapshot_complete is False


def test_backfilled_release_date_moves_event_and_weekly_kpi_idempotently(db):
    ingest(db, run(item(status="released", status_at="2026-11-23T09:00:00", released_revision="b" * 40)))
    recorded_at = db.query(DevlogItemEvent).one().recorded_at
    corrected = run(item(status="released", status_at="2026-11-10T09:00:00", released_revision="a" * 40))
    result = ingest(db, corrected)
    assert result["updated"] == 1 and result["transitions"] == 0
    assert ingest(db, corrected)["unchanged"] == 1
    event = db.query(DevlogItemEvent).one()
    assert event.occurred_at == datetime(2026, 11, 10, 9)
    assert event.recorded_at == recorded_at
    assert db.query(DevlogItem).one().status_at == event.occurred_at
    old_week = summary(db, start=date(2026, 11, 9), end=date(2026, 11, 15))
    new_week = summary(db, start=date(2026, 11, 23), end=date(2026, 11, 29))
    assert old_week["kpis"]["features"] == 1
    assert old_week["timeline"][0]["date"] == "2026-11-10"
    assert new_week["kpis"]["features"] == 0
    assert new_week["timeline"] == []


@pytest.mark.parametrize("included", [("git",), ("git", "fetch"), ("git", "releases"), ("fetch", "releases"), ()])
def test_omitted_sources_are_partial_without_destructive_snapshot_effects(db, monkeypatch, included):
    import app.devlog.query_service as qs
    _complete_run(db, 10)
    _ledger_at(db, "new", created_at=datetime(2026, 11, 23, 11))
    ingest(db, run(item(status="released"), item(key="branch:codex/retained")))
    payload = run(item(status="dev", fingerprint="b" * 64), item(key="branch:codex/new"))
    payload.sources = [state for state in payload.sources if state.name in included]
    payload.snapshot = True
    result = ingest(db, payload)
    assert result["failed"] == []
    assert result["created"] == 1  # Safe partial writes still proceed.
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/a").one().status == "released"
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/retained").one().superseded is False
    assert db.query(DevlogSyncRun).order_by(DevlogSyncRun.id.desc()).first().snapshot_complete is False
    monkeypatch.setattr(qs, "beijing_now", lambda: datetime(2026, 11, 23, 15, 2))
    state = health(db)
    assert state["is_stale"] is True
    assert state["ledger_pending_check"] is True
