"""设计预约 — 冲突检测引擎"""

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from app.design.models import (
    DesignScheduleTask,
    DesignUnavailableDate,
    DesignCapacityConfig,
)
from app.core.config import get_settings


def get_scheduling_mode(db: Session) -> str:
    """读取全局排期模式（config_date IS NULL AND designer_id IS NULL）"""
    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date.is_(None),
        DesignCapacityConfig.designer_id.is_(None),
    ).first()
    if row:
        return row.scheduling_mode
    return "pool"


def get_capacity_for_date(
    db: Session,
    d: date,
    designer_id: Optional[int] = None,
) -> int:
    """
    级联查找容量上限：
    1. 指定日期 + 指定设计师
    2. 指定日期 + 全局（designer_id IS NULL）
    3. 全局行（config_date IS NULL AND designer_id IS NULL）
    4. 兜底：settings.DESIGN_DEFAULT_DAILY_CAPACITY
    """
    settings = get_settings()

    if designer_id is not None:
        row = db.query(DesignCapacityConfig).filter(
            DesignCapacityConfig.config_date == d,
            DesignCapacityConfig.designer_id == designer_id,
        ).first()
        if row:
            return row.max_parallel_tasks

    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date == d,
        DesignCapacityConfig.designer_id.is_(None),
    ).first()
    if row:
        return row.max_parallel_tasks

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
    designer_id: Optional[int] = None,
    exclude_task_id: Optional[int] = None,
) -> dict:
    """
    检测日期范围内的冲突。

    返回:
        {
            "has_conflict": bool,          # 仅 overloaded_dates 触发
            "unavailable_dates": [...],    # 不可用日期（仅提示，不触发冲突）
            "overloaded_dates": [...],     # 超容量日期
            "route": str | None            # "pending_audit" 表示需要走审批
        }
    """
    # 1. 收集不可用日期
    unavailable_rows = db.query(DesignUnavailableDate).filter(
        DesignUnavailableDate.date >= start_date,
        DesignUnavailableDate.date <= end_date,
    ).all()
    unavailable_dates = [row.date.isoformat() for row in unavailable_rows]

    # 2. 检测每天的任务负载是否超容量
    overloaded_dates = []
    current = start_date
    while current <= end_date:
        # 查询该日已有的活跃任务数（排除已取消/已完成的）
        query = db.query(func.count(DesignScheduleTask.id)).filter(
            DesignScheduleTask.plan_start_date <= current,
            DesignScheduleTask.plan_end_date >= current,
            DesignScheduleTask.status.in_(["pending_design", "scheduled", "in_progress"]),
        )
        if designer_id is not None:
            query = query.filter(DesignScheduleTask.designer_id == designer_id)
        if exclude_task_id is not None:
            query = query.filter(DesignScheduleTask.id != exclude_task_id)

        task_count = query.scalar() or 0
        capacity = get_capacity_for_date(db, current, designer_id)

        if task_count >= capacity:
            overloaded_dates.append({
                "date": current.isoformat(),
                "current_tasks": task_count,
                "capacity": capacity,
            })

        current += timedelta(days=1)

    has_conflict = len(overloaded_dates) > 0
    route = "pending_audit" if has_conflict else None

    return {
        "has_conflict": has_conflict,
        "unavailable_dates": unavailable_dates,
        "overloaded_dates": overloaded_dates,
        "route": route,
    }
