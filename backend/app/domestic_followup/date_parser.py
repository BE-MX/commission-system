"""相对日期确定性解析（规格 4.2）。

模型同时给原话 date_expression 和日期；这里按原话重算，两者不一致时以
这里为准，界面标黄让业务员确认。today 由调用方传 beijing_today()，本模块
不读时钟，便于测「服务器非东八区」和「00:00 跨日」。
"""
import calendar
import re
from datetime import date, timedelta

from app.domestic_followup.constants import WEEKDAY_LABELS

_WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_N = r"(\d{1,2}|[一二两三四五六七八九十]{1,3})"


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if "十" not in token:
        return _CN_NUM.get(token) if len(token) == 1 else None
    tens, _, ones = token.partition("十")
    tens_value = _CN_NUM.get(tens) if tens else 1
    ones_value = _CN_NUM.get(ones) if ones else 0
    if tens_value is None or ones_value is None:
        return None
    return tens_value * 10 + ones_value


def _safe_date(year: int, month: int, day: int | None) -> date | None:
    if not day:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _monday(today: date) -> date:
    return today - timedelta(days=today.weekday())


_PAST_WEEKDAY = r"上个?(?:周|星期|礼拜)[一二三四五六日天]"
_PAST_MONTH_END = r"上个?月[底末]?"


def resolve_relative_date(expression: str | None, today: date) -> date | None:
    text = re.sub(r"\s+", "", expression or "")
    if not text:
        return None
    # 「上周三」「上个月底」指向过去，不是下次跟进时间；挖掉再走剩余规则，
    # 否则通用星期/月底正则会把它们当成目标日期（规格 4.2 的既知缺陷）
    text = re.sub(_PAST_WEEKDAY, "", text)
    text = re.sub(_PAST_MONTH_END, "", text)
    if not text:
        return None
    if m := re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"(?<!\d)(\d{2})\.(\d{1,2})\.(\d{1,2})(?!\d)", text):
        return _safe_date(2000 + int(m[1]), int(m[2]), int(m[3]))
    if "大后天" in text:
        return today + timedelta(days=3)
    if "后天" in text:
        return today + timedelta(days=2)
    if re.search(r"明[天日]", text):
        return today + timedelta(days=1)
    if re.search(r"今[天日]", text):
        return today
    if m := re.search(r"(?<!\d)" + _N + r"[天日](?:后|以后|之后)", text):
        days = _to_int(m[1])
        return today + timedelta(days=days) if days is not None else None
    if m := re.search(r"(?<!\d)" + _N + r"个?(?:周|星期|礼拜)(?:后|以后|之后)", text):
        weeks = _to_int(m[1])
        return today + timedelta(weeks=weeks) if weeks is not None else None
    if m := re.search(r"下下个?(?:周|星期|礼拜)([一二三四五六日天])", text):
        return _monday(today) + timedelta(days=14 + _WEEKDAY_INDEX[m[1]])
    if m := re.search(r"下个?(?:周|星期|礼拜)([一二三四五六日天])", text):
        return _monday(today) + timedelta(days=7 + _WEEKDAY_INDEX[m[1]])
    if re.search(r"下个?月[底末]", text):
        return _month_end(*_add_months(today.year, today.month, 1))
    if re.search(r"月[底末]", text):
        return _month_end(today.year, today.month)
    if m := re.search(r"下个?月" + _N + r"[号日]", text):
        year, month = _add_months(today.year, today.month, 1)
        return _safe_date(year, month, _to_int(m[1]))
    if m := re.search(r"(?<![\d一二两三四五六七八九十])" + _N + r"月" + _N + r"[号日]?", text):
        month, day = _to_int(m[1]), _to_int(m[2])
        if not month or month > 12:
            return None
        candidate = _safe_date(today.year, month, day)
        if candidate and candidate < today - timedelta(days=30):
            candidate = _safe_date(today.year + 1, month, day)
        return candidate
    # 前面紧跟数字的不算星期：「一周一次」「3周」
    if m := re.search(r"(?<![\d一二两三四五六七八九十])(?:周|星期|礼拜)([一二三四五六日天])", text):
        candidate = _monday(today) + timedelta(days=_WEEKDAY_INDEX[m[1]])
        # 等于今天也顺延一周：裸星期几指的是「再」问的下一次，不是正在记录的今天
        # （今天本身已经有专门的「今天」规则覆盖）
        return candidate if candidate > today else candidate + timedelta(days=7)
    if m := re.search(r"(?<![\d月])" + _N + r"[号日]", text):
        day = _to_int(m[1])
        candidate = _safe_date(today.year, today.month, day)
        if candidate is None or candidate < today:
            year, month = _add_months(today.year, today.month, 1)
            candidate = _safe_date(year, month, day)
        return candidate
    return None


def weekday_label(value: date) -> str:
    return WEEKDAY_LABELS[value.weekday()]


def reconcile_next_date(expression: str | None, model_date: date | None, today: date) -> tuple[date | None, str]:
    """返回 (采用的日期, 依据)。依据：parsed / mismatch / unverified / none。"""
    parsed = resolve_relative_date(expression, today)
    if parsed:
        return parsed, ("mismatch" if model_date and model_date != parsed else "parsed")
    if model_date:
        return model_date, "unverified"
    return None, "none"
