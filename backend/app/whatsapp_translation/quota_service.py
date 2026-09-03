"""Bounded rate limiting and atomic Beijing-day quota accounting."""

import math
import threading
import time
from collections import OrderedDict, deque
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today
from app.whatsapp_translation.constants import ERROR_DAILY_QUOTA
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import TranslationUsageDaily


class BoundedSlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.windows: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            window = self.windows.get(key)
            if window is None:
                window = deque()
                self.windows[key] = window
                if len(self.windows) > self.max_keys:
                    self.windows.popitem(last=False)
            while window and window[0] <= now - self.window_seconds:
                window.popleft()
            if len(window) < self.limit:
                window.append(now)
                if len(self.windows) > self.max_keys:
                    self.windows.popitem(last=False)
                return True, 0
            retry_after = math.ceil(self.window_seconds - (now - window[0]))
            return False, max(1, retry_after)

    def clear(self) -> None:
        with self.lock:
            self.windows.clear()


def client_ip(request) -> str:
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


LATENCY_BUCKETS = (
    ("lt_500", 500),
    ("lt_1000", 1000),
    ("lt_2000", 2000),
    ("lt_5000", 5000),
    ("lt_10000", 10000),
    ("gte_10000", None),
)


def _latency_bucket(duration_ms: int) -> str:
    for name, upper_bound in LATENCY_BUCKETS:
        if upper_bound is None or duration_ms < upper_bound:
            return name
    return "gte_10000"


def _lock_user(db: Session, user_id: int) -> None:
    db.execute(select(ArkUser).where(ArkUser.id == user_id).with_for_update())


def _get_or_create_usage_row(
    db: Session,
    usage_date: date,
    user_id: int,
    device_id: int,
    input_chars: int,
) -> TranslationUsageDaily:
    query = db.query(TranslationUsageDaily).filter(
        TranslationUsageDaily.usage_date == usage_date,
        TranslationUsageDaily.user_id == user_id,
        TranslationUsageDaily.device_id == device_id,
    )
    row = query.one_or_none()
    if row is not None:
        row.input_chars += input_chars
        db.commit()
        return row

    try:
        with db.begin_nested():
            row = TranslationUsageDaily(
                usage_date=usage_date,
                user_id=user_id,
                device_id=device_id,
                input_chars=input_chars,
                duration_buckets={},
                direction_counts={},
                language_pair_counts={},
                error_counts={},
            )
            db.add(row)
            db.flush()
    except IntegrityError:
        row = query.one_or_none()
        if row is None:
            raise
        row.input_chars += input_chars
    db.commit()
    return row


def reserve_daily_input(db: Session, identity, input_chars: int) -> TranslationUsageDaily:
    settings = get_settings()
    usage_date = beijing_today()
    _lock_user(db, identity.user_id)
    total = db.query(TranslationUsageDaily).filter(
        TranslationUsageDaily.usage_date == usage_date,
        TranslationUsageDaily.user_id == identity.user_id,
    ).with_entities(TranslationUsageDaily.input_chars).all()
    used = sum(value[0] for value in total)
    if used + input_chars > settings.WHATSAPP_TRANSLATION_DAILY_INPUT_CHARS:
        db.commit()
        midnight = beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = max(1, int((midnight + __import__("datetime").timedelta(days=1) - beijing_now()).total_seconds()))
        raise WhatsAppTranslationError(
            429,
            ERROR_DAILY_QUOTA,
            "Daily translation quota exceeded",
            retry_after,
        )
    return _get_or_create_usage_row(db, usage_date, identity.user_id, identity.device_id, input_chars)


def _lock_usage_row(db: Session, row_id: int) -> TranslationUsageDaily:
    return db.execute(
        select(TranslationUsageDaily).where(TranslationUsageDaily.id == row_id).with_for_update()
    ).scalar_one()


def record_success(
    db: Session,
    row: TranslationUsageDaily,
    *,
    direction: str,
    source_language: str,
    target_language: str,
    duration_ms: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    row = _lock_usage_row(db, row.id)
    row.request_count += 1
    row.success_count += 1
    row.input_tokens += input_tokens
    row.output_tokens += output_tokens
    row.duration_ms_total += duration_ms
    row.duration_buckets = dict(row.duration_buckets or {})
    row.duration_buckets[_latency_bucket(duration_ms)] = row.duration_buckets.get(_latency_bucket(duration_ms), 0) + 1
    row.direction_counts = dict(row.direction_counts or {})
    row.direction_counts[direction] = row.direction_counts.get(direction, 0) + 1
    language_pair = source_language + "\u2192" + target_language
    row.language_pair_counts = dict(row.language_pair_counts or {})
    row.language_pair_counts[language_pair] = row.language_pair_counts.get(language_pair, 0) + 1
    db.commit()


def record_failure(
    db: Session,
    row: TranslationUsageDaily,
    *,
    direction: str,
    error_code: str,
) -> None:
    row = _lock_usage_row(db, row.id)
    row.request_count += 1
    row.failure_count += 1
    row.direction_counts = dict(row.direction_counts or {})
    row.direction_counts[direction] = row.direction_counts.get(direction, 0) + 1
    row.error_counts = dict(row.error_counts or {})
    row.error_counts[error_code] = row.error_counts.get(error_code, 0) + 1
    db.commit()


def estimate_p95(duration_buckets: dict) -> int:
    counts = {name: int(duration_buckets.get(name, 0)) for name, _ in LATENCY_BUCKETS}
    total = sum(counts.values())
    if total == 0:
        return 0
    cumulative = 0
    target = total * 95 / 100
    for name, upper_bound in LATENCY_BUCKETS:
        cumulative += counts[name]
        if cumulative >= target:
            return upper_bound
    return 10000

