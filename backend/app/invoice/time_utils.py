"""订单域时间输出口径：数据库 UTC，API 北京时间。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def to_beijing_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return utc_value.astimezone(BEIJING_TIMEZONE)
