"""Business calendar, State Council notices 国办发明电〔2024〕12号 /〔2025〕7号."""

from datetime import date, datetime, timedelta

DAY = timedelta(days=1)
PERIODS = {
    2025: (
        "0101-0101 0128-0204 0404-0406 0501-0505 0531-0602 1001-1008",
        "0126 0208 0427 0928 1011",
    ),
    2026: (
        "0101-0103 0215-0223 0404-0406 0501-0505 0619-0621 0925-0927 1001-1007",
        "0104 0214 0228 0509 0920 1010",
    ),
}


def _official():
    years = {}
    for year, (periods, makeup) in PERIODS.items():

        def day(mmdd):
            return date(year, int(mmdd[:2]), int(mmdd[2:]))

        holidays = set()
        for period in periods.split():
            start, end = map(day, period.split("-"))
            while start <= end:
                holidays.add(start.isoformat())
                start += DAY
        years[str(year)] = {
            "holidays": holidays,
            "workdays": {day(x).isoformat() for x in makeup.split()},
        }
    return years


OFFICIAL = _official()


def is_workday(day, calendar=None):
    year = str(day.year)
    cfg = (calendar or {}).get(year, OFFICIAL.get(year))
    if not isinstance(cfg, dict) or not {"holidays", "workdays"} <= cfg.keys():
        raise ValueError(f"calendar_year_missing:{year}")
    key = day.isoformat()
    return key in cfg["workdays"] or (key not in cfg["holidays"] and day.weekday() < 5)


def offset_workdays(day, count, calendar=None):
    direction = 1 if count >= 0 else -1
    remaining = abs(count)
    while remaining:
        day += direction * DAY
        remaining -= is_workday(day, calendar)
    return day


def complete_days(start, end, calendar=None, cap=40):
    """Count full intervening Beijing business dates; cap permits bounded historical reads."""
    day = end - DAY
    count = 0
    while day > start and count < cap:
        count += is_workday(day, calendar)
        day -= DAY
    return count
