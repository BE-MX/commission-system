from datetime import date

import pytest

from app.domestic_followup.date_parser import reconcile_next_date, resolve_relative_date, weekday_label

FRI = date(2026, 10, 30)  # 周五


@pytest.mark.parametrize("expr, expected", [
    ("今天", date(2026, 10, 30)),
    ("明天下午", date(2026, 10, 31)),
    ("后天", date(2026, 11, 1)),
    ("大后天", date(2026, 11, 2)),
    ("3天后", date(2026, 11, 2)),
    ("三天以后", date(2026, 11, 2)),
    ("下周一", date(2026, 11, 2)),
    ("下星期三", date(2026, 11, 4)),
    ("下礼拜天", date(2026, 11, 8)),
    ("周三再问", date(2026, 11, 4)),
    ("周六", date(2026, 10, 31)),
    ("5号", date(2026, 11, 5)),
    ("30号", date(2026, 10, 30)),
    ("十五号", date(2026, 11, 15)),
    ("月底", date(2026, 10, 31)),
    ("下个月底", date(2026, 11, 30)),
    ("下月3号", date(2026, 11, 3)),
    ("11月4日", date(2026, 11, 4)),
    ("1月5日", date(2027, 1, 5)),
    ("下下周一", date(2026, 11, 9)),
    ("两周后", date(2026, 11, 13)),
    ("十二月五日", date(2026, 12, 5)),
    ("2026-11-04", date(2026, 11, 4)),
    ("2026/11/4", date(2026, 11, 4)),
    ("26.10.30", date(2026, 10, 30)),
    ("上周三说的，周五再问", date(2026, 11, 6)),
])
def test_resolve_relative_date(expr, expected):
    assert resolve_relative_date(expr, FRI) == expected


@pytest.mark.parametrize("expr", [
    None, "", "过几天", "2月30日", "等客户回复", "100天后", "一周一次回访", "上周三", "上个月底",
])
def test_unparseable_returns_none(expr):
    assert resolve_relative_date(expr, FRI) is None


def test_day_of_month_rolls_to_next_valid_month():
    assert resolve_relative_date("31号", date(2026, 11, 5)) == date(2026, 12, 31)


def test_weekday_label():
    assert weekday_label(date(2026, 11, 2)) == "周一"
    assert weekday_label(date(2026, 11, 8)) == "周日"


def test_reconcile_prefers_backend_and_flags_mismatch():
    assert reconcile_next_date("下周一", date(2026, 11, 3), FRI) == (date(2026, 11, 2), "mismatch")
    assert reconcile_next_date("下周一", date(2026, 11, 2), FRI) == (date(2026, 11, 2), "parsed")
    assert reconcile_next_date("过几天", date(2026, 11, 3), FRI) == (date(2026, 11, 3), "unverified")
    assert reconcile_next_date(None, None, FRI) == (None, "none")
