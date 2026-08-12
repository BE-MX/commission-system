"""订单域时间口径：数据库与 API 均使用北京时间。"""

from datetime import datetime
from zoneinfo import ZoneInfo


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def to_beijing_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TIMEZONE)
    return value.astimezone(BEIJING_TIMEZONE)


def beijing_now() -> datetime:
    """返回适合 MySQL DATETIME 的无时区北京时间。"""
    return datetime.now(BEIJING_TIMEZONE).replace(tzinfo=None)
