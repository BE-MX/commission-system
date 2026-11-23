from datetime import date, datetime

from app.devlog.ingest_service import ingest
from app.devlog.query_service import health, item_detail, pending_list, summary
from app.devlog.release_service import record_release
from app.devlog.schemas import IngestIn


def push(db, items, finished="2026-11-23T15:01:00"):
    ingest(db, IngestIn.model_validate({"started_at": finished, "finished_at": finished,
                                        "sources": [{"name": name, "ok": True} for name in ("git", "fetch", "releases")], "items": items}))


def it(key, status, at, type_="feature", stale=False, fp="a", pre=None):
    return {"key": key, "title": key.split("/")[-1], "type": type_, "module": "invoice", "agent": "codex",
            "status": status, "status_at": at, "last_activity_at": at, "stale": stale,
            "fingerprint": fp * 64, "preconditions": pre or {}, "evidences": []}


def seed(db):
    push(db, [
        it("branch:codex/old-release", "released", "2026-11-10T10:00:00"),
        it("branch:codex/fix", "released", "2026-11-23T14:02:00", type_="bug"),
        it("branch:codex/wip", "dev", "2026-11-23T10:00:00"),
        it("branch:codex/ready", "pending_release", "2026-11-22T10:00:00"),
        it("branch:codex/needs-config", "pending_release", "2026-11-21T10:00:00",
           pre={"migrations": ["276_invoice_alibaba_order"], "config_keys": ["CROSS_BORDER_DXP_ID"], "permissions": []}),
        it("branch:codex/forgotten", "pending_merge", "2026-10-01T10:00:00", stale=True),
    ])


def test_week_summary_buckets_by_event_time(db):
    seed(db)
    data = summary(db, start=date(2026, 11, 17), end=date(2026, 11, 23))
    assert data["kpis"] == {"features": 0, "bugs": 1, "data": 0, "dev": 1, "pending_release": 2, "stale": 1}
    titles = {c: [i["title"] for i in data["columns"][c]] for c in data["columns"]}
    assert titles["released"] == ["fix"]
    assert "old-release" not in sum(titles.values(), [])
    assert "forgotten" not in sum(titles.values(), [])
    assert data["timeline"][0]["date"] == "2026-11-23"


def test_type_filter(db):
    seed(db)
    data = summary(db, start=date(2026, 11, 17), end=date(2026, 11, 23), item_type="bug")
    assert data["kpis"]["pending_release"] == 0 and data["kpis"]["bugs"] == 1


def test_pending_list_ready_flags(db):
    seed(db)
    rows = {r["title"]: r for r in pending_list(db)}
    assert rows["ready"]["ready"] is True
    assert rows["needs-config"]["ready"] is False
    assert "forgotten" not in rows   # 停滞项不进清单


def test_health_marks_stale_after_six_hours(db, monkeypatch):
    import app.devlog.query_service as qs
    record_release(db, revision="d" * 40, release_id="g", scope="office-and-cloud", released_at=datetime(2026, 11, 23, 14, 2), source="deployer")
    push(db, [], finished="2026-11-23T07:12:00")
    monkeypatch.setattr(qs, "beijing_now", lambda: datetime(2026, 11, 23, 15, 20))
    data = health(db)
    assert data["is_stale"] is True and data["ledger_latest"]["revision"] == "d" * 40


def test_detail_contains_events(db):
    seed(db)
    first = summary(db, start=date(2026, 11, 17), end=date(2026, 11, 23))["columns"]["released"][0]
    detail = item_detail(db, first["id"])
    assert detail["events"][-1]["to_status"] == "released"
