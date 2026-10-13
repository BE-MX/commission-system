"""Connector timestamp parsing in Beijing business time."""
from datetime import datetime
from typing import Any
from app.core.time import to_beijing_naive


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return to_beijing_naive(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Connector 带 Z/offset 时先换算为北京时间，绝不只丢
            # tzinfo；无 offset 按双方约定的北京业务钟面处理。
            return to_beijing_naive(parsed)
        except ValueError:
            return None
    return None
