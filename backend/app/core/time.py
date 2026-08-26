"""方舟平台时间口径。

业务库使用 MySQL DATETIME 存储无时区的北京时间；只有 JWT、
外部协议和跨机器租约等明确的技术场景可使用 UTC。
"""

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
    """返回北京时间的业务日期，不受服务器本地时区影响。"""
    return beijing_now_aware().date()


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间，仅用于协议/签名等明确 UTC 场景。"""
    return datetime.now(UTC_TIMEZONE)


def utc_now_naive() -> datetime:
    """返回无时区 UTC，仅用于既有跨机器租约存储契约。"""
    return utc_now().replace(tzinfo=None)


def to_beijing_time(value: datetime | None, *, naive_is_beijing: bool = True) -> datetime | None:
    """将时间转换为带时区的北京时间。

    业务库中的 naive DATETIME 默认已是北京钟面时间，不做二次
    加 8 小时。只有读取明确的历史 UTC 值时才传 naive_is_beijing=False。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        source_timezone = BEIJING_TIMEZONE if naive_is_beijing else UTC_TIMEZONE
        value = value.replace(tzinfo=source_timezone)
    return value.astimezone(BEIJING_TIMEZONE)


def to_beijing_naive(value: datetime | None, *, naive_is_beijing: bool = True) -> datetime | None:
    """将外部时间转为适合写入业务 DATETIME 的北京钟面时间。

    带 offset/Z 的值会先转到 Asia/Shanghai，再去掉 tzinfo；无 offset
    的值按业务时间处理。只有明确声明“naive 就是 UTC”的协议
    才允许传 naive_is_beijing=False。
    """
    aware = to_beijing_time(value, naive_is_beijing=naive_is_beijing)
    return aware.replace(tzinfo=None) if aware is not None else None
