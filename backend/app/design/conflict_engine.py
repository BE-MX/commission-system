"""设计预约 — 冲突检测引擎（半天槽位粒度）"""

from datetime import date, timedelta
from typing import Optional, Generator

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from app.design.models import (
    DesignScheduleTask,
    DesignUnavailableDate,
    DesignCapacityConfig,
)
from app.core.config import get_settings


_PERIOD_VAL = {"am": 0, "pm": 1}


def _pval(p: Optional[str]) -> int:
    return _PERIOD_VAL.get(p or "am", 0)


def iter_slots(
    start_date: date, start_period: str,
    end_date: date, end_period: str,
) -> Generator[tuple[date, str], None, None]:
    cur_date = start_date
    cur_p = start_period or "am"
    end_p = end_period or "pm"
    while True:
        yield (cur_date, cur_p)
        if cur_date == end_date and cur_p == end_p:
            break
        if cur_p == "am":
            cur_p = "pm"
        else:
            cur_p = "am"
            cur_date += timedelta(days=1)


def task_covers_slot(task, slot_date: date, slot_period: str) -> bool:
    if not task.plan_start_date or not task.plan_end_date:
        return False
    sp = _pval(slot_period)
    ts = _pval(task.plan_start_period)
    te = _pval(task.plan_end_period)
    starts_before = (task.plan_start_date < slot_date or
                     (task.plan_start_date == slot_date and ts <= sp))
    ends_after = (task.plan_end_date > slot_date or
                  (task.plan_end_date == slot_date and te >= sp))
    return starts_before and ends_after


def get_scheduling_mode(db: Session) -> str:
    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date.is_(None),
        DesignCapacityConfig.designer_id.is_(None),
    ).first()
    if row:
        return row.scheduling_mode
    return "pool"


def get_capacity_for_slot(
    db: Session,
    d: date,
    period: str = "am",
    designer_id: Optional[int] = None,
) -> int:
    settings = get_settings()

    # 1. date + designer + period
    if designer_id is not None:
        row = db.query(DesignCapacityConfig).filter(
            DesignCapacityConfig.config_date == d,
            DesignCapacityConfig.designer_id == designer_id,
            DesignCapacityConfig.period == period,
        ).first()
        if row:
            return row.max_parallel_tasks

    # 2. date + designer + NULL period (full day)
    if designer_id is not None:
        row = db.query(DesignCapacityConfig).filter(
            DesignCapacityConfig.config_date == d,
            DesignCapacityConfig.designer_id == designer_id,
            DesignCapacityConfig.period.is_(None),
        ).first()
        if row:
            return row.max_parallel_tasks

    # 3. date + NULL designer + period
    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date == d,
        DesignCapacityConfig.designer_id.is_(None),
        DesignCapacityConfig.period == period,
    ).first()
    if row:
        return row.max_parallel_tasks

    # 4. date + NULL designer + NULL period
    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date == d,
        DesignCapacityConfig.designer_id.is_(None),
        DesignCapacityConfig.period.is_(None),
    ).first()
    if row:
        return row.max_parallel_tasks

    # 5. global (NULL date + NULL designer + NULL period)
    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date.is_(None),
        DesignCapacityConfig.designer_id.is_(None),
    ).first()
    if row:
        return row.max_parallel_tasks

    return settings.DESIGN_DEFAULT_DAILY_CAPACITY


def check_conflict(
    db: Session,
    start_date: date,
    end_date: date,
    start_period: str = "am",
    end_period: str = "pm",
    designer_id: Optional[int] = None,
    exclude_task_id: Optional[int] = None,
) -> dict:
    start_period = start_period or "am"
    end_period = end_period or "pm"

    # 1. Unavailable dates/slots
    unavailable_rows = db.query(DesignUnavailableDate).filter(
        DesignUnavailableDate.date >= start_date,
        DesignUnavailableDate.date <= end_date,
    ).all()
    unavailable_slots = []
    for row in unavailable_rows:
        unavailable_slots.append({
            "date": row.date.isoformat(),
            "period": row.period,
        })

    # 2. Pre-fetch active tasks that could overlap the date range
    query = db.query(DesignScheduleTask).filter(
        DesignScheduleTask.plan_start_date <= end_date,
        DesignScheduleTask.plan_end_date >= start_date,
        DesignScheduleTask.status.in_(["pending_design", "scheduled", "in_progress"]),
    )
    if designer_id is not None:
        query = query.filter(DesignScheduleTask.designer_id == designer_id)
    if exclude_task_id is not None:
        query = query.filter(DesignScheduleTask.id != exclude_task_id)
    active_tasks = query.all()

    # 3. Check each slot
    overloaded_slots = []
    for slot_date, slot_period in iter_slots(start_date, start_period, end_date, end_period):
        task_count = sum(1 for t in active_tasks if task_covers_slot(t, slot_date, slot_period))
        capacity = get_capacity_for_slot(db, slot_date, slot_period, designer_id)

        if task_count >= capacity:
            overloaded_slots.append({
                "date": slot_date.isoformat(),
                "period": slot_period,
                "current_tasks": task_count,
                "capacity": capacity,
            })

    has_conflict = len(overloaded_slots) > 0
    route = "pending_audit" if has_conflict else None

    return {
        "has_conflict": has_conflict,
        "unavailable_dates": unavailable_slots,
        "overloaded_dates": overloaded_slots,
        "route": route,
    }
