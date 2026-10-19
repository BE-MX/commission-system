"""Scheduler-owned database factory for portal notification delivery."""
from app.core.database import SessionLocal
from app.portal.notification_worker import run_once


def deliver_portal_notifications():
    return run_once(SessionLocal)


def deliver_portal_dingtalk_notices():
    # Sync job: AsyncIOScheduler runs it in a worker thread, so asyncio.run is safe here.
    from app.portal.dingtalk_notice import run_once as run_dingtalk
    return run_dingtalk(SessionLocal)
