"""开发动态查询口径：看板、KPI、时间线、待发布清单、同步健康。"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogSyncRun, DevlogRelease, GLOBAL_SCOPE
from app.devlog.release_service import latest_global
from app.devlog.source_status import sources_complete

COLUMN = {"dev": "dev", "pending_merge": "committed", "pending_push": "committed",
          "pending_release": "committed", "released": "released"}
STALE_SYNC_HOURS = 6


def _item(row: DevlogItem) -> dict:
    return {"id": row.id, "key": row.item_key, "title": row.title, "type": row.item_type, "module": row.module,
            "agent": row.agent, "status": row.status, "status_at": row.status_at.isoformat(timespec="minutes"),
            "last_activity_at": row.last_activity_at.isoformat(timespec="minutes"), "stale": row.stale,
            "unmerged_hotfix": row.unmerged_hotfix, "released_revision": row.released_revision,
            "preconditions": row.preconditions or {}}


def _filtered(db: Session, item_type: str | None, module: str | None, agent: str | None):
    query = db.query(DevlogItem)
    if item_type:
        query = query.filter(DevlogItem.item_type == item_type)
    if module:
        query = query.filter(DevlogItem.module == module)
    if agent:
        query = query.filter(DevlogItem.agent == agent)
    return query.all()


def summary(db: Session, *, start: date, end: date, item_type: str | None = None,
            module: str | None = None, agent: str | None = None) -> dict:
    if end == date.max or end < start or (end - start).days > 400:
        raise HTTPException(status_code=422, detail="日期范围无效")
    items = {row.id: row for row in _filtered(db, item_type, module, agent)}
    window = (datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min))
    events = (db.query(DevlogItemEvent)
              .filter(DevlogItemEvent.occurred_at >= window[0], DevlogItemEvent.occurred_at < window[1],
                      DevlogItemEvent.item_id.in_(list(items) or [0]))
              .order_by(DevlogItemEvent.occurred_at.desc()).all())
    released_ids = {event.item_id for event in events if event.to_status == "released"}
    columns = {"dev": [], "committed": [], "released": []}
    stale_columns = {"dev": [], "committed": [], "released": []}
    for row in sorted(items.values(), key=lambda r: r.status_at, reverse=True):
        if row.status == "released":
            if row.id in released_ids:
                columns["released"].append(_item(row))
        elif not row.superseded:
            target = stale_columns if row.stale else columns
            target[COLUMN[row.status]].append(_item(row))
    released = [items[i] for i in released_ids]
    open_rows = [r for r in items.values() if r.status != "released" and not r.superseded]
    kpis = {
        "features": sum(r.item_type in ("feature", "improve") for r in released),
        "bugs": sum(r.item_type == "bug" for r in released),
        "data": sum(r.item_type == "data" for r in released),
        "dev": sum(r.status == "dev" and not r.stale for r in open_rows),
        "pending_release": sum(r.status == "pending_release" and not r.stale for r in open_rows),
        "stale": sum(r.stale for r in open_rows),
    }
    days = defaultdict(list)
    for event in events:
        days[event.occurred_at.date().isoformat()].append(
            {**_item(items[event.item_id]), "to_status": event.to_status,
             "occurred_at": event.occurred_at.isoformat(timespec="minutes")})
    timeline = [{"date": day, "entries": entries} for day, entries in sorted(days.items(), reverse=True)]
    return {"kpis": kpis, "columns": columns, "stale_columns": stale_columns, "timeline": timeline}


def item_detail(db: Session, item_id: int) -> dict:
    row = db.get(DevlogItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="事项不存在")
    evidences = (db.query(DevlogEvidence).filter(DevlogEvidence.item_id == item_id)
                 .order_by(DevlogEvidence.occurred_at).all())
    events = (db.query(DevlogItemEvent).filter(DevlogItemEvent.item_id == item_id)
              .order_by(DevlogItemEvent.occurred_at, DevlogItemEvent.id).all())
    return {**_item(row),
            "evidences": [{"kind": e.kind, "ref": e.ref, "at": e.occurred_at.isoformat(timespec="minutes")} for e in evidences],
            "events": [{"from_status": e.from_status, "to_status": e.to_status,
                        "at": e.occurred_at.isoformat(timespec="minutes")} for e in events]}


def pending_list(db: Session) -> list[dict]:
    order = {"pending_release": 0, "pending_push": 1, "pending_merge": 2}
    # 停滞与已被取代的事项不进上线准备清单（停滞项在看板折叠行里查看）
    rows = (db.query(DevlogItem).filter(DevlogItem.status.in_(list(order)), DevlogItem.stale.is_(False),
                                        DevlogItem.superseded.is_(False)).all())
    rows.sort(key=lambda r: r.status_at, reverse=True)
    rows.sort(key=lambda r: order[r.status])
    result = []
    for row in rows:
        pre = row.preconditions or {}
        ready = row.status == "pending_release" and not pre.get("config_keys") and not pre.get("permissions")
        result.append({**_item(row), "ready": ready})
    return result


def health(db: Session) -> dict:
    last = db.query(DevlogSyncRun).order_by(DevlogSyncRun.finished_at.desc(), DevlogSyncRun.id.desc()).first()
    complete = (db.query(DevlogSyncRun).filter(DevlogSyncRun.snapshot_complete.is_(True))
                .order_by(DevlogSyncRun.started_at.desc(), DevlogSyncRun.id.desc()).first())
    pending_releases = db.query(DevlogRelease.id).filter(DevlogRelease.scope == GLOBAL_SCOPE)
    if complete is not None:
        pending_releases = pending_releases.filter(DevlogRelease.created_at > complete.started_at)
    # The never-synced UI already has its own state. Use creation time, not the
    # historical release time: a backfill invalidates previously computed coverage.
    ledger_pending_check = last is not None and pending_releases.first() is not None
    now = beijing_now()
    elapsed = None if last is None else max(0, (now - last.finished_at).total_seconds() / 3600)
    hours = None if elapsed is None else round(elapsed, 1)
    failed = bool(last and (last.failed_keys or not sources_complete(last.sources)))
    return {"last_sync_at": last.finished_at.isoformat(timespec="minutes") if last else None,
            "sources": last.sources if last else [], "hours_since_sync": hours,
            "is_stale": last is None or elapsed > STALE_SYNC_HOURS or failed,
            "failed_keys": last.failed_keys if last else [],
            "ledger_latest": latest_global(db), "ledger_pending_check": ledger_pending_check}
