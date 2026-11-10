"""Opt-in private-sea jobs on the office singleton scheduler."""
import logging

from app.core.config import get_settings
from app.core.database import SessionLocal

logger = logging.getLogger("commission.client_desk")


def _users(db):
    from app.client_desk.access import enrolled_user_ids
    from app.invoice.xiaoman_service import resolve_okki_user_id

    settings = get_settings()
    if not settings.CLIENT_DESK_ENABLED:
        return []
    return [
        uid for uid in db.scalars(enrolled_user_ids(settings))
        if resolve_okki_user_id(db, uid) is not None
    ]


def candidates_job():
    from app.client_desk.queue import scan_pilots

    with SessionLocal() as db:
        try:
            scan_pilots(db, _users(db))
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Candidate scan failed: %s", type(exc).__name__)
            print(f"[CLIENT_DESK] Candidate scan failed: {type(exc).__name__}", flush=True)


def worker_job():
    if not get_settings().CLIENT_DESK_ENABLED:
        return
    from app.client_desk.runner import drain_queue

    drain_queue(SessionLocal, limit=40)


async def report_job():
    if not get_settings().CLIENT_DESK_REPORT_ENABLED:
        return
    from app.client_desk.reports import send_report

    with SessionLocal() as db:
        for user in _users(db):
            try:
                await send_report(db, user)
            except Exception as exc:
                db.rollback()
                logger.warning("Morning report failed for user %s: %s", user, type(exc).__name__)
                print(f"[CLIENT_DESK] Morning report failed for user {user}: {type(exc).__name__}", flush=True)
