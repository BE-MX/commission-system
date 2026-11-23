"""采集器上报落库：按 item_key upsert，状态变化写事件，上报里缺席的事项保持原样（缺源不等于消失）。"""
import logging
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogSyncRun
from app.devlog.schemas import IngestIn, ItemIn
from app.devlog.source_status import sources_complete

logger = logging.getLogger(__name__)
STATUS_RANK = {"dev": 0, "pending_merge": 1, "pending_push": 2, "pending_release": 3, "released": 4}


def _bj(value: datetime) -> datetime:
    return to_beijing_naive(value, naive_is_beijing=True)


def _upsert(db: Session, item: ItemIn, now: datetime) -> str:
    row = db.query(DevlogItem).filter(DevlogItem.item_key == item.key).one_or_none()
    if (row is not None and row.fingerprint == item.fingerprint and row.status == item.status
            and row.stale == item.stale and not row.superseded
            and row.title == item.title and row.item_type == item.type
            and row.module == item.module and row.agent == item.agent
            and row.status_at == _bj(item.status_at) and row.last_activity_at == _bj(item.last_activity_at)
            and row.unmerged_hotfix == item.unmerged_hotfix and row.released_revision == item.released_revision
            and row.preconditions == item.preconditions.model_dump()):
        return "unchanged"
    outcome = "updated" if row is not None else "created"
    previous = row.status if row is not None else None
    previous_at = row.status_at if row is not None else None
    if row is None:
        row = DevlogItem(item_key=item.key, created_at=now)
        db.add(row)
    row.title = item.title
    row.item_type = item.type
    row.module = item.module
    row.agent = item.agent
    row.status = item.status
    row.status_at = _bj(item.status_at)
    row.last_activity_at = _bj(item.last_activity_at)
    row.stale = item.stale
    row.superseded = False
    row.unmerged_hotfix = item.unmerged_hotfix
    row.released_revision = item.released_revision
    row.preconditions = item.preconditions.model_dump()
    row.fingerprint = item.fingerprint
    row.updated_at = now
    db.flush()
    if previous != item.status:
        db.add(DevlogItemEvent(item_id=row.id, from_status=previous, to_status=item.status,
                               occurred_at=_bj(item.status_at), recorded_at=now))
    elif item.status == "released" and previous_at != row.status_at:
        # Backfilled authoritative ledger history can correct first coverage without
        # creating a second release transition. Keep the original audit recording time.
        event = (db.query(DevlogItemEvent)
                 .filter_by(item_id=row.id, to_status="released", occurred_at=previous_at)
                 .order_by(DevlogItemEvent.id.desc()).first())
        if event is not None:
            event.occurred_at = row.status_at
    db.query(DevlogEvidence).filter(DevlogEvidence.item_id == row.id).delete(synchronize_session=False)
    seen = set()
    for evidence in item.evidences:
        if (evidence.kind, evidence.ref) in seen:
            continue
        seen.add((evidence.kind, evidence.ref))
        db.add(DevlogEvidence(item_id=row.id, kind=evidence.kind, ref=evidence.ref, occurred_at=_bj(evidence.at)))
    db.flush()
    return outcome + ("+transition" if previous != item.status else "")


def ingest(db: Session, payload: IngestIn) -> dict:
    """Serialize full snapshots across backend instances on the owning MySQL server."""
    if db.get_bind().dialect.name != "mysql":
        return _ingest(db, payload)
    # Hold a dedicated connection until RELEASE_LOCK, including across the data commit.
    # Returning a connection with an advisory lock to the pool would leak that lock.
    with db.get_bind().connect() as lock_connection:
        lock_name = "ark_devlog_ingest"
        acquired = lock_connection.execute(text("SELECT GET_LOCK(:name, 5)"), {"name": lock_name}).scalar()
        if acquired != 1:
            raise HTTPException(status_code=409, detail="另一次同步正在进行，请稍后重试")
        try:
            return _ingest(db, payload)
        finally:
            try:
                lock_connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
            except Exception as exc:
                logger.warning("devlog lock release failed: %s", type(exc).__name__)
                print(f"[devlog] lock release failed: {type(exc).__name__}", flush=True)
                lock_connection.invalidate()
                raise


def _ingest(db: Session, payload: IngestIn) -> dict:
    if db.get_bind().dialect.name == "sqlite":
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    # A delayed older snapshot must not resurrect branches or overwrite newer states.
    latest = db.query(DevlogSyncRun).order_by(DevlogSyncRun.finished_at.desc()).first()
    if latest is not None and _bj(payload.finished_at) < latest.finished_at:
        raise HTTPException(status_code=409, detail="采集结果早于最近同步，请重新采集")
    now = beijing_now()
    counts = {"created": 0, "updated": 0, "unchanged": 0, "transitions": 0, "failed": []}
    sources = [source.model_dump() for source in payload.sources]
    sources_ok = sources_complete(sources)
    for item in payload.items:
        try:
            # An incomplete source set cannot prove a regression from a known state.
            if not sources_ok:
                previous = db.query(DevlogItem).filter_by(item_key=item.key).one_or_none()
                if previous is not None and STATUS_RANK[item.status] < STATUS_RANK[previous.status]:
                    counts["unchanged"] += 1
                    continue
            with db.begin_nested():
                outcome = _upsert(db, item, now)
        except Exception as exc:  # 单条失败隔离在 savepoint 内，继续处理其余事项
            logger.warning("devlog ingest item failed key=%s error=%s", item.key, type(exc).__name__)
            print(f"[devlog] ingest item failed key={item.key} error={type(exc).__name__}", flush=True)
            counts["failed"].append(item.key)
            continue
        base, _, transition = outcome.partition("+")
        counts[base] += 1
        if transition:
            counts["transitions"] += 1
    if payload.snapshot and sources_ok and not counts["failed"]:
        present = [item.key for item in payload.items]
        (db.query(DevlogItem)
         .filter(DevlogItem.superseded.is_(False), DevlogItem.item_key.notin_(present or [""]))
         .update({DevlogItem.superseded: True, DevlogItem.updated_at: now}, synchronize_session=False))
    db.add(DevlogSyncRun(started_at=_bj(payload.started_at), finished_at=_bj(payload.finished_at),
                         sources=sources,
                         item_count=len(payload.items), failed_keys=counts["failed"], created_at=now,
                         snapshot_complete=payload.snapshot and sources_ok and not counts["failed"]))
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("devlog ingest commit failed: %s", type(exc).__name__)
        print(f"[devlog] ingest commit failed: {type(exc).__name__}", flush=True)
        raise
    return counts
