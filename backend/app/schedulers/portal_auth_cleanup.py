"""Retired invitation/OTP secret retention; never delivers authentication mail."""
from app.core.database import SessionLocal
from app.portal.mail_worker import cleanup_expired


def cleanup_portal_auth_secrets():
    with SessionLocal() as db:
        count = cleanup_expired(db)
        db.commit()
        return count
