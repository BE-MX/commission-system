"""Scheduler-owned database factory for portal notification delivery."""
from app.core.database import SessionLocal
from app.portal.notification_worker import run_once


def deliver_portal_notifications():
    return run_once(SessionLocal)
