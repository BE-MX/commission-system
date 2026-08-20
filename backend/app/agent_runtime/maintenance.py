"""Retention jobs for Agent runtime sensitive payloads."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.agent_runtime.models import AgentEvent
from app.core.config import get_settings
from app.core.database import SessionLocal


def redact_expired_raw_events(
    db: Session,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
) -> int:
    """Remove only encrypted raw payloads; keep normalized audit events intact."""
    days = retention_days or get_settings().AGENT_RUNTIME_RAW_EVENT_RETENTION_DAYS
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    count = db.query(AgentEvent).filter(
        AgentEvent.created_at < cutoff,
        AgentEvent.raw_payload_cipher.isnot(None),
    ).update({AgentEvent.raw_payload_cipher: None}, synchronize_session=False)
    db.commit()
    return int(count or 0)


def redact_expired_raw_events_job() -> int:
    with SessionLocal() as db:
        return redact_expired_raw_events(db)
