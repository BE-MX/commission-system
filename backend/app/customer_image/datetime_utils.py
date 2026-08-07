"""UTC-naive datetime convention for customer image persistence."""

from datetime import UTC, datetime


def as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
