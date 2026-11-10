"""Local feed normalization on the singleton scheduler; no CRM or AI calls."""
from app.core.config import get_settings
from app.core.database import SessionLocal


def worker_job():
    settings = get_settings()
    from app.alibaba_feed.worker import drain_queue
    drain_queue(SessionLocal, limit=10, lease_seconds=settings.ALIBABA_FEED_LEASE_SECONDS)
