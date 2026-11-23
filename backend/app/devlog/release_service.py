"""发布账本：部署器验收通过后写入，回填走同一入口；按 release_id 幂等。"""
import logging
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.core.config import get_settings
from app.core.time import to_beijing_naive
from app.devlog.schemas import ReleaseIn

from sqlalchemy.orm import Session

from app.devlog.models import GLOBAL_SCOPE, DevlogRelease


logger = logging.getLogger(__name__)


def record_release(db: Session, *, revision: str, release_id: str, scope: str, released_at: datetime, source: str) -> bool:
    # sqlite3 legacy transaction mode does not BEGIN for SELECT/SAVEPOINT.
    # Establish the outer transaction so savepoint release cannot commit a partial batch.
    if db.get_bind().dialect.name == "sqlite":
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    release = ReleaseIn(revision=revision, release_id=release_id, scope=scope, released_at=released_at)
    if source not in ("deployer", "backfill"):
        raise ValueError("Invalid release source")

    def existing(*, lock=False):
        query = db.query(DevlogRelease).filter_by(release_id=release.release_id).populate_existing()
        return (query.with_for_update() if lock else query).one_or_none()

    def check(row):
        # A retry receives a new CLI clock reading; preserve the original acceptance time.
        if row.revision != release.revision or row.scope != release.scope:
            raise HTTPException(status_code=409, detail="发布标识已被其他版本或范围使用")
        return False

    row = existing()
    if row is not None:
        return check(row)
    try:
        with db.begin_nested():
            db.add(DevlogRelease(revision=release.revision, release_id=release.release_id,
                                scope=release.scope, released_at=to_beijing_naive(release.released_at), source=source))
            db.flush()
    except IntegrityError:
        # The unique release_id arbitrates concurrent deployer/backfill retries.
        logger.warning("devlog release identity raced")
        print("[devlog] release identity raced", flush=True)
        row = existing(lock=True)
        if row is None:
            raise
        return check(row)
    return True


def _row(release: DevlogRelease) -> dict:
    return {"revision": release.revision, "release_id": release.release_id, "scope": release.scope,
            "released_at": release.released_at.isoformat(timespec="seconds"), "source": release.source}


def list_releases(db: Session) -> list[dict]:
    return [_row(r) for r in db.query(DevlogRelease).order_by(DevlogRelease.released_at, DevlogRelease.id).all()]


def latest_global(db: Session) -> dict | None:
    release = (db.query(DevlogRelease).filter(DevlogRelease.scope == GLOBAL_SCOPE)
               .order_by(DevlogRelease.released_at.desc(), DevlogRelease.id.desc()).first())
    return _row(release) if release else None

def backfill(db: Session, items) -> int:
    """人工核对后的一次性回填；开关默认关闭，防止常驻采集器 token 伪造「已发布」。"""
    if not get_settings().DEVLOG_BACKFILL_ENABLED:
        raise HTTPException(status_code=403, detail="发布账本回填未开启")
    recorded = 0
    try:
        for item in items:
            recorded += record_release(db, revision=item.revision, release_id=item.release_id, scope=item.scope,
                                       released_at=item.released_at, source="backfill")
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("devlog backfill failed: %s", type(exc).__name__)
        print(f"[devlog] backfill failed: {type(exc).__name__}", flush=True)
        raise
    return recorded
