"""Explicit business calendar; never infer holidays from the host timezone."""
from datetime import date, time
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from app.core.time import to_beijing_naive

SEPTEMBER_WORK_DATES = ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-28", "2026-09-29", "2026-09-30"]


def work_dates(report):
    configured = getattr(report, "work_dates", None)
    if configured is not None:
        return sorted(configured)
    # The calendar explicitly confirmed for this campaign; no inferred holidays elsewhere.
    if report.start_date == date(2026, 9, 22) and report.end_date == date(2026, 9, 30):
        return list(SEPTEMBER_WORK_DATES)
    return []


def calendar_progress(report, now):
    dates = work_dates(report)
    if not dates or any(not report.start_date <= date.fromisoformat(d) <= report.end_date for d in dates):
        return None
    local = to_beijing_naive(now)
    completed = sum(d < local.date().isoformat() or (d == local.date().isoformat() and local.time() >= time(16)) for d in dates)
    step = (Decimal(100) / len(dates)).quantize(Decimal(".01"), rounding=ROUND_DOWN)
    percent = Decimal(100) if completed == len(dates) else step * completed
    return {"percent": float(percent), "completed": completed, "total": len(dates),
            "step": float(step), "work_dates": dates, "cutoff": "16:00", "timezone": "Asia/Shanghai"}


def pace_metrics(metrics, progress):
    if progress is None or metrics["progress_percent"] is None:
        return {"ahead_of_time": None, "pace_delta": None}
    target = Decimal(metrics["target"])
    percent = Decimal(str(progress["percent"]))
    actual = Decimal(metrics["gmv"]) * 100 / target
    # Compare before rounding. Equality, including zero/zero completion, is not ahead.
    return {"ahead_of_time": Decimal(metrics["gmv"]) * 100 > target * percent,
            "pace_delta": format((actual - percent).quantize(Decimal(".01"), rounding=ROUND_HALF_UP), ".2f")}
