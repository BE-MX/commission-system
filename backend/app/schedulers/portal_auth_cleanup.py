"""Scheduler-owned invitation/activation mail delivery and expired auth secret cleanup."""
from app.core.database import SessionLocal
from app.portal.mail_worker import cleanup_expired, run_once


def cleanup_portal_auth_secrets():
    with SessionLocal() as db:
        count = cleanup_expired(db)
        db.commit()
        return count


def deliver_portal_auth_mail():
    # run_once owns its sessions and keeps SMTP outside any DB transaction.
    return run_once(SessionLocal)
