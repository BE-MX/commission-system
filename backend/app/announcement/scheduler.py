"""Single-active scheduler entrypoints. Own sessions only in scheduler scope."""
import logging
from app.core.database import SessionLocal
from app.announcement import delivery, weekly

logger = logging.getLogger(__name__)


def dispatch_announcements():
    with SessionLocal() as db:
        try:
            delivery.recover(db)
            claimed = delivery.claim(db)
            if claimed:
                delivery.execute(db, *claimed)
        except Exception as exc:
            db.rollback()
            logger.warning('announcement dispatcher: %s', type(exc).__name__)
            print(f'announcement dispatcher: {type(exc).__name__}', flush=True)
            raise


def generate_announcement_weekly():
    with SessionLocal() as db:
        try:
            weekly.schedule_due(db)
            weekly.execute_next(db)
        except Exception as exc:
            db.rollback()
            logger.warning('announcement weekly scheduler: %s', type(exc).__name__)
            print(f'announcement weekly scheduler: {type(exc).__name__}', flush=True)
            raise
