"""设计预约 — 排期 / 容量 / 不可日 / 调度模式 / 甘特图"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.design.models import (
    DesignScheduleTask,
    DesignDesigner,
    DesignUnavailableDate,
    DesignCapacityConfig,
)
from app.design.conflict_engine import get_scheduling_mode as _get_mode
from app.design.schemas import (
    TaskReschedule,
    UnavailableDateCreate,
    CapacityUpdate,
    ModeUpdate,
)
from app.design.audit_log import write_audit_log as _write_audit_log

logger = __import__("logging").getLogger("design")


def get_gantt_data(
    db: Session,
    start_date: date,
    end_date: date,
    designer_id: Optional[int] = None,
) -> dict:
    """获取甘特图数据"""
    designer_query = db.query(DesignDesigner).filter(DesignDesigner.is_active == True)
    if designer_id:
        designer_query = designer_query.filter(DesignDesigner.id == designer_id)
    designers = designer_query.all()

    result = []
    for d in designers:
        tasks = db.query(DesignScheduleTask).filter(
            DesignScheduleTask.designer_id == d.id,
            DesignScheduleTask.status.in_(["scheduled", "in_progress", "completed"]),
            DesignScheduleTask.plan_start_date <= end_date,
            DesignScheduleTask.plan_end_date >= start_date,
        ).all()
        result.append({
            "id": d.id,
            "name": d.name,
            "tasks": [
                {
                    "id": t.id,
                    "request_id": t.request_id,
                    "task_no": t.task_no,
                    "designer_id": t.designer_id,
                    "task_name": t.task_name,
                    "customer_name": t.customer_name,
                    "salesperson_name": t.salesperson_name,
                    "shoot_type": t.shoot_type,
                    "priority": t.priority,
                    "plan_start_date": t.plan_start_date.isoformat() if t.plan_start_date else None,
                    "plan_start_period": t.plan_start_period or "am",
                    "plan_end_date": t.plan_end_date.isoformat() if t.plan_end_date else None,
                    "plan_end_period": t.plan_end_period or "pm",
                    "actual_start_date": t.actual_start_date.isoformat() if t.actual_start_date else None,
                    "actual_start_period": t.actual_start_period,
                    "actual_end_date": t.actual_end_date.isoformat() if t.actual_end_date else None,
                    "actual_end_period": t.actual_end_period,
                    "status": t.status,
                    "remark": t.remark,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in tasks
            ],
        })

    # 获取不可用日期
    unavailable = db.query(DesignUnavailableDate).filter(
        DesignUnavailableDate.date >= start_date,
        DesignUnavailableDate.date <= end_date,
    ).all()
    unavailable_dates = [
        {"date": row.date.isoformat(), "period": row.period, "reason": row.reason}
        for row in unavailable
    ]

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "designers": result,
            "unavailable_dates": unavailable_dates,
        },
    }


def reschedule_task(
    db: Session,
    task_id: int,
    data: TaskReschedule,
    operator_id: int,
    operator_name: str,
) -> dict:
    """改期任务"""
    task = db.query(DesignScheduleTask).filter(
        DesignScheduleTask.id == task_id,
    ).first()
    if not task:
        raise ValueError("任务不存在")

    if task.status in ("completed", "cancelled"):
        raise ValueError(f"任务状态 {task.status} 不允许改期")

    old_start = task.plan_start_date
    old_start_period = task.plan_start_period
    old_end = task.plan_end_date
    old_end_period = task.plan_end_period
    old_designer = task.designer_id

    task.plan_start_date = data.plan_start_date
    task.plan_start_period = data.plan_start_period or "am"
    task.plan_end_date = data.plan_end_date
    task.plan_end_period = data.plan_end_period or "pm"
    if data.designer_id is not None:
        task.designer_id = data.designer_id
    task.updated_at = datetime.now()

    _write_audit_log(
        db,
        request_id=task.request_id,
        task_id=task.id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role="design_staff",
        action="reschedule",
        from_status=task.status,
        to_status=task.status,
        comment=data.comment,
        snapshot={
            "old_start": old_start.isoformat() if old_start else None,
            "old_start_period": old_start_period,
            "old_end": old_end.isoformat() if old_end else None,
            "old_end_period": old_end_period,
            "old_designer_id": old_designer,
            "new_start": data.plan_start_date.isoformat(),
            "new_start_period": data.plan_start_period or "am",
            "new_end": data.plan_end_date.isoformat(),
            "new_end_period": data.plan_end_period or "pm",
            "new_designer_id": data.designer_id,
        },
    )
    db.commit()
    db.refresh(task)

    return {
        "code": 200,
        "message": "改期成功",
        "data": {
            "task_id": task.id,
            "task_no": task.task_no,
            "request_id": task.request_id,
            "old_designer_id": old_designer,
            "new_designer_id": task.designer_id,
            "old_start": old_start.isoformat() if old_start else None,
            "old_start_period": old_start_period,
            "old_end": old_end.isoformat() if old_end else None,
            "old_end_period": old_end_period,
            "new_start": data.plan_start_date.isoformat(),
            "new_start_period": data.plan_start_period or "am",
            "new_end": data.plan_end_date.isoformat(),
            "new_end_period": data.plan_end_period or "pm",
        },
    }


def create_unavailable_dates(
    db: Session,
    data: UnavailableDateCreate,
    operator_id: int,
    operator_name: str,
) -> dict:
    """批量设置不可用日期"""
    created = []
    for d in data.dates:
        q = db.query(DesignUnavailableDate).filter(DesignUnavailableDate.date == d)
        if data.period:
            q = q.filter(DesignUnavailableDate.period == data.period)
        else:
            q = q.filter(DesignUnavailableDate.period.is_(None))
        if q.first():
            continue
        row = DesignUnavailableDate(
            date=d,
            period=data.period,
            reason=data.reason,
            created_by=operator_id,
        )
        db.add(row)
        created.append(d.isoformat())

    if created:
        _write_audit_log(
            db,
            request_id=0,
            operator_id=operator_id,
            operator_name=operator_name,
            operator_role="design_staff",
            action="set_unavailable",
            comment=f"设置不可用日期: {', '.join(created)}; 原因: {data.reason}",
        )
    db.commit()

    return {
        "code": 200,
        "message": f"已设置 {len(created)} 个不可用日期",
        "data": {"dates": created},
    }


def delete_unavailable_date(
    db: Session,
    date_str: str,
    operator_id: int,
    operator_name: str,
    period: Optional[str] = None,
) -> dict:
    """删除不可用日期"""
    from datetime import date as date_type
    try:
        target = date_type.fromisoformat(date_str)
    except ValueError:
        raise ValueError("日期格式错误，应为 YYYY-MM-DD")

    q = db.query(DesignUnavailableDate).filter(DesignUnavailableDate.date == target)
    if period:
        q = q.filter(DesignUnavailableDate.period == period)
    else:
        q = q.filter(DesignUnavailableDate.period.is_(None))
    row = q.first()
    if not row:
        raise ValueError("该日期未设置为不可用")

    db.delete(row)
    _write_audit_log(
        db,
        request_id=0,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role="design_staff",
        action="remove_unavailable",
        comment=f"移除不可用日期: {date_str}",
    )
    db.commit()

    return {"code": 200, "message": "已移除不可用日期", "data": {"date": date_str}}


def get_capacity(db: Session) -> list:
    """获取所有容量配置"""
    rows = db.query(DesignCapacityConfig).all()
    return [
        {
            "id": r.id,
            "config_date": r.config_date.isoformat() if r.config_date else None,
            "designer_id": r.designer_id,
            "period": r.period,
            "max_parallel_tasks": r.max_parallel_tasks,
            "scheduling_mode": r.scheduling_mode,
            "updated_by": r.updated_by,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def update_capacity(
    db: Session,
    data: CapacityUpdate,
    operator_id: int,
    operator_name: str,
) -> dict:
    """更新容量配置"""
    for entry in data.entries:
        q = db.query(DesignCapacityConfig)
        q = q.filter(DesignCapacityConfig.config_date == entry.config_date) if entry.config_date else q.filter(DesignCapacityConfig.config_date.is_(None))
        q = q.filter(DesignCapacityConfig.designer_id == entry.designer_id) if entry.designer_id else q.filter(DesignCapacityConfig.designer_id.is_(None))
        q = q.filter(DesignCapacityConfig.period == entry.period) if entry.period else q.filter(DesignCapacityConfig.period.is_(None))
        existing = q.first()
        if existing:
            existing.max_parallel_tasks = entry.max_parallel_tasks
            existing.updated_by = operator_id
            existing.updated_at = datetime.now()
        else:
            row = DesignCapacityConfig(
                config_date=entry.config_date,
                designer_id=entry.designer_id,
                period=entry.period,
                max_parallel_tasks=entry.max_parallel_tasks,
                updated_by=operator_id,
            )
            db.add(row)

    _write_audit_log(
        db,
        request_id=0,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role="design_staff",
        action="update_capacity",
        comment=f"更新容量配置 {len(data.entries)} 条",
    )
    db.commit()

    return {"code": 200, "message": "容量配置已更新", "data": None}


def get_scheduling_mode_info(db: Session) -> dict:
    """获取当前排期模式"""
    mode = _get_mode(db)
    return {"code": 200, "message": "ok", "data": {"scheduling_mode": mode}}


def update_scheduling_mode(
    db: Session,
    data: ModeUpdate,
    operator_id: int,
    operator_name: str,
) -> dict:
    """更新排期模式"""
    row = db.query(DesignCapacityConfig).filter(
        DesignCapacityConfig.config_date.is_(None),
        DesignCapacityConfig.designer_id.is_(None),
    ).first()
    if row:
        row.scheduling_mode = data.scheduling_mode
        row.updated_by = operator_id
        row.updated_at = datetime.now()
    else:
        row = DesignCapacityConfig(
            config_date=None,
            designer_id=None,
            max_parallel_tasks=3,
            scheduling_mode=data.scheduling_mode,
            updated_by=operator_id,
        )
        db.add(row)

    _write_audit_log(
        db,
        request_id=0,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role="design_staff",
        action="update_capacity",
        comment=f"切换排期模式为 {data.scheduling_mode}",
    )
    db.commit()

    return {"code": 200, "message": f"排期模式已切换为 {data.scheduling_mode}", "data": None}
