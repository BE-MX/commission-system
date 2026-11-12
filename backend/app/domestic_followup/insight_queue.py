"""Short transactional queue admission and leases shared by HTTP and the scheduler."""
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.core.time import beijing_now
from app.domestic_followup.insight_models import DomesticFollowupInsightSnapshot as Snapshot
from app.domestic_followup.models import DomesticFollowupConfig

logger = logging.getLogger("commission")
ACTIVE = ("queued", "running")
LOCK_KEY = "_insight_queue_lock"


def lock_admission(db):
    # A single config row serializes only queue admission, never an AI request.
    if db.get(DomesticFollowupConfig, LOCK_KEY) is None:
        try:
            with db.begin_nested():
                db.add(DomesticFollowupConfig(key=LOCK_KEY, value={}))
                db.flush()
        except IntegrityError:
            logger.warning("followup insight queue lock initialized concurrently")
            print("[domestic_followup] insight queue lock initialized concurrently", flush=True)
    db.query(DomesticFollowupConfig).filter_by(key=LOCK_KEY).populate_existing().with_for_update().one()


def recover_stale(db):
    now = beijing_now()
    # Queued work has not consumed its execution window yet.
    condition = or_((Snapshot.status == "running") & (Snapshot.updated_at < now - timedelta(minutes=15)),
                    (Snapshot.status == "queued") & (Snapshot.created_at < now - timedelta(hours=24)))
    return db.execute(update(Snapshot).where(condition).values(
        status="failed", error="进程重启或生成超时", run_token=None, updated_at=now,
    ).execution_options(synchronize_session=False)).rowcount


def active(db, scope, user_id):
    return db.query(Snapshot).filter(Snapshot.scope == scope, Snapshot.user_id == user_id,
                                     Snapshot.status.in_(ACTIVE)).order_by(Snapshot.id.desc()).populate_existing().with_for_update().first()


def claim(db, snapshot_id):
    token = str(uuid4())
    claimed = db.execute(update(Snapshot).where(
        Snapshot.id == snapshot_id, Snapshot.status.in_(ACTIVE), Snapshot.run_token.is_(None),
    ).values(status="running", run_token=token, updated_at=beijing_now()).execution_options(synchronize_session=False))
    db.commit()
    return token if claimed.rowcount else None
