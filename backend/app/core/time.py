"""方舟平台统一业务时间口径。"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
UTC_TIMEZONE = timezone.utc


def beijing_now() -> datetime:
    """返回适合写入 MySQL DATETIME 的无时区北京时间。"""
    return datetime.now(BEIJING_TIMEZONE).replace(tzinfo=None)


def beijing_now_aware() -> datetime:
    """返回带 Asia/Shanghai 时区的当前时间。"""
    return datetime.now(BEIJING_TIMEZONE)


def beijing_today() -> date:
    """返回北京时间业务日期，不受服务器本地时区影响。"""
    return beijing_now_aware().date()


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间，仅用于明确的技术协议场景。"""
    return datetime.now(UTC_TIMEZONE)


def utc_now_naive() -> datetime:
    """返回无时区 UTC，仅用于既有跨机器存储契约。"""
    return utc_now().replace(tzinfo=None)


def to_beijing_time(value: datetime | None, *, naive_is_beijing: bool = True) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=BEIJING_TIMEZONE if naive_is_beijing else UTC_TIMEZONE)
    return value.astimezone(BEIJING_TIMEZONE)


def to_beijing_naive(value: datetime | None, *, naive_is_beijing: bool = True) -> datetime | None:
    aware = to_beijing_time(value, naive_is_beijing=naive_is_beijing)
    return aware.replace(tzinfo=None) if aware is not None else None
