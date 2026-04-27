"""设计预约 — 业务逻辑层"""

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.design.models import (
    DesignScheduleRequest,
    DesignScheduleTask,
    DesignDesigner,
    DesignUnavailableDate,
    DesignCapacityConfig,
    DesignAuditLog,
)
from app.design.state_machine import RequestStatus, OperatorRole, transition
from app.design.conflict_engine import check_conflict, get_scheduling_mode as _get_mode
from app.design.utils import generate_request_no, generate_task_no
from app.design.schemas import (
    DesignRequestCreate,
    DesignRequestAudit,
    DesignRequestAction,
    TaskReschedule,
    UnavailableDateCreate,
    CapacityUpdate,
    ModeUpdate,
)

logger = logging.getLogger("design")


# ── 辅助 ──────────────────────────────────────────────────


def _write_audit_log(
    db: Session,
    *,
    request_id: int,
    task_id: Optional[int] = None,
    operator_id: int,
    operator_name: str,
    operator_role: str,
    action: str,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    comment: Optional[str] = None,
    snapshot: Optional[dict] = None,
):
    log = DesignAuditLog(
        request_id=request_id,
        task_id=task_id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role=operator_role,
        action=action,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        snapshot=snapshot,
    )
    db.add(log)


# ── 申请单 ────────────────────────────────────────────────


def create_request(
    db: Session,
    data: DesignRequestCreate,
    operator_id: int,
    operator_name: str,
    operator_role: str,
) -> dict:
    """创建设计预约申请"""
    # 冲突检测
    conflict = check_conflict(db, data.expect_start_date, data.expect_end_date)

    request_no = generate_request_no(db)

    req = DesignScheduleRequest(
        request_no=request_no,
        customer_name=data.customer_name,
        salesperson_id=data.salesperson_id,
        salesperson_name=data.salesperson_name,
        shoot_type=data.shoot_type,
        shoot_type_remark=data.shoot_type_remark,
        expect_start_date=data.expect_start_date,
        expect_end_date=data.expect_end_date,
        priority=data.priority,
        remark=data.remark,
        status="pending_audit",
        conflict_detail=conflict if conflict["has_conflict"] else None,
    )
    db.add(req)
    db.flush()

    _write_audit_log(
        db,
        request_id=req.id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role=operator_role,
        action="submit",
        to_status="pending_audit",
        comment=data.remark,
    )
    db.commit()
    db.refresh(req)

    return {
        "code": 200,
        "message": "申请已提交",
        "data": {
            "id": req.id,
            "request_no": req.request_no,
            "status": req.status,
            "conflict": conflict,
        },
    }


def audit_request(
    db: Session,
    request_id: int,
    data: DesignRequestAudit,
    operator_id: int,
    operator_name: str,
) -> dict:
    """主管审批（approve / reject）"""
    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ).first()
    if not req:
        raise ValueError("申请单不存在")

    from_status = req.status
    new_status = transition(
        RequestStatus(from_status),
        data.action,
        OperatorRole.supervisor,
    )
    req.status = new_status.value
    req.updated_at = datetime.now()

    _write_audit_log(
        db,
        request_id=req.id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role="supervisor",
        action=data.action,
        from_status=from_status,
        to_status=new_status.value,
        comment=data.comment,
    )
    db.commit()
    db.refresh(req)

    return {
        "code": 200,
        "message": f"审批操作 {data.action} 完成",
        "data": {"id": req.id, "status": req.status},
    }


def action_request(
    db: Session,
    request_id: int,
    data: DesignRequestAction,
    operator_id: int,
    operator_name: str,
    operator_role: str,
) -> dict:
    """执行申请单动作：confirm / start / complete / cancel"""
    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ).first()
    if not req:
        raise ValueError("申请单不存在")

    from_status = req.status
    new_status = transition(
        RequestStatus(from_status),
        data.action,
        OperatorRole(operator_role),
    )
    req.status = new_status.value
    req.updated_at = datetime.now()

    task_id = None

    if data.action == "confirm":
        # 确认排期 → 创建任务
        if not data.designer_id:
            raise ValueError("确认排期需要指定设计师")
        task_no = generate_task_no(db)
        task = DesignScheduleTask(
            request_id=req.id,
            task_no=task_no,
            designer_id=data.designer_id,
            task_name=f"{req.customer_name} - {req.shoot_type}",
            customer_name=req.customer_name,
            salesperson_name=req.salesperson_name,
            shoot_type=req.shoot_type,
            priority=req.priority,
            plan_start_date=data.plan_start_date or req.expect_start_date,
            plan_end_date=data.plan_end_date or req.expect_end_date,
            status="scheduled",
        )
        db.add(task)
        db.flush()
        task_id = task.id
        req.assigned_designer_id = data.designer_id

    elif data.action == "start":
        req.actual_start_date = date.today()
        # 同步更新相关任务
        for t in req.tasks:
            if t.status == "scheduled":
                t.status = "in_progress"
                t.actual_start_date = date.today()
                t.updated_at = datetime.now()

    elif data.action == "complete":
        req.actual_end_date = date.today()
        for t in req.tasks:
            if t.status == "in_progress":
                t.status = "completed"
                t.actual_end_date = date.today()
                t.updated_at = datetime.now()

    elif data.action == "cancel":
        for t in req.tasks:
            if t.status not in ("completed", "cancelled"):
                t.status = "cancelled"
                t.updated_at = datetime.now()

    _write_audit_log(
        db,
        request_id=req.id,
        task_id=task_id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role=operator_role,
        action=data.action,
        from_status=from_status,
        to_status=new_status.value,
        comment=data.comment,
    )
    db.commit()
    db.refresh(req)

    return {
        "code": 200,
        "message": f"操作 {data.action} 完成",
        "data": {"id": req.id, "status": req.status},
    }


# ── 甘特图 ────────────────────────────────────────────────


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
                    "plan_end_date": t.plan_end_date.isoformat() if t.plan_end_date else None,
                    "actual_start_date": t.actual_start_date.isoformat() if t.actual_start_date else None,
                    "actual_end_date": t.actual_end_date.isoformat() if t.actual_end_date else None,
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
    unavailable_dates = [row.date.isoformat() for row in unavailable]

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "designers": result,
            "unavailable_dates": unavailable_dates,
        },
    }


# ── 任务改期 ──────────────────────────────────────────────


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
    old_end = task.plan_end_date
    old_designer = task.designer_id

    task.plan_start_date = data.plan_start_date
    task.plan_end_date = data.plan_end_date
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
        comment=data.comment,
        snapshot={
            "old_start": old_start.isoformat() if old_start else None,
            "old_end": old_end.isoformat() if old_end else None,
            "old_designer_id": old_designer,
            "new_start": data.plan_start_date.isoformat(),
            "new_end": data.plan_end_date.isoformat(),
            "new_designer_id": data.designer_id,
        },
    )
    db.commit()
    db.refresh(task)

    return {
        "code": 200,
        "message": "改期成功",
        "data": {"task_id": task.id, "task_no": task.task_no},
    }


# ── 不可用日期 ────────────────────────────────────────────


def create_unavailable_dates(
    db: Session,
    data: UnavailableDateCreate,
    operator_id: int,
    operator_name: str,
) -> dict:
    """批量设置不可用日期"""
    created = []
    for d in data.dates:
        existing = db.query(DesignUnavailableDate).filter(
            DesignUnavailableDate.date == d,
        ).first()
        if existing:
            continue
        row = DesignUnavailableDate(
            date=d,
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
) -> dict:
    """删除不可用日期"""
    from datetime import date as date_type
    try:
        target = date_type.fromisoformat(date_str)
    except ValueError:
        raise ValueError("日期格式错误，应为 YYYY-MM-DD")

    row = db.query(DesignUnavailableDate).filter(
        DesignUnavailableDate.date == target,
    ).first()
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


# ── 容量配置 ──────────────────────────────────────────────


def get_capacity(db: Session) -> list:
    """获取所有容量配置"""
    rows = db.query(DesignCapacityConfig).all()
    return [
        {
            "id": r.id,
            "config_date": r.config_date.isoformat() if r.config_date else None,
            "designer_id": r.designer_id,
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
        existing = db.query(DesignCapacityConfig).filter(
            DesignCapacityConfig.config_date == entry.config_date if entry.config_date else DesignCapacityConfig.config_date.is_(None),
            DesignCapacityConfig.designer_id == entry.designer_id if entry.designer_id else DesignCapacityConfig.designer_id.is_(None),
        ).first()
        if existing:
            existing.max_parallel_tasks = entry.max_parallel_tasks
            existing.updated_by = operator_id
            existing.updated_at = datetime.now()
        else:
            row = DesignCapacityConfig(
                config_date=entry.config_date,
                designer_id=entry.designer_id,
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


# ── 排期模式 ──────────────────────────────────────────────


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
