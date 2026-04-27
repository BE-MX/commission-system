"""设计预约 — API 路由"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.design import service
from app.design.schemas import (
    DesignRequestCreate,
    DesignRequestAudit,
    DesignRequestAction,
    TaskReschedule,
    UnavailableDateCreate,
    CapacityUpdate,
    ModeUpdate,
)
from app.design.models import (
    DesignScheduleRequest, DesignScheduleTask, DesignAuditLog,
    DesignUnavailableDate, DesignDesigner, DesignCapacityConfig,
)

router = APIRouter()


# ── 申请单 CRUD ───────────────────────────────────────────


@router.post("/requests")
def create_request(
    data: DesignRequestCreate,
    db: Session = Depends(get_db),
):
    """提交设计预约申请"""
    return service.create_request(
        db, data, data.operator_id, data.operator_name, data.operator_role
    )


@router.get("/requests")
def list_requests(
    status: Optional[str] = Query(None),
    salesperson_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """查询申请单列表"""
    query = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.deleted_at.is_(None),
    )
    if status:
        q_statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(q_statuses) == 1:
            query = query.filter(DesignScheduleRequest.status == q_statuses[0])
        elif q_statuses:
            query = query.filter(DesignScheduleRequest.status.in_(q_statuses))
    if salesperson_id:
        query = query.filter(DesignScheduleRequest.salesperson_id == salesperson_id)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (DesignScheduleRequest.customer_name.like(like))
            | (DesignScheduleRequest.request_no.like(like))
            | (DesignScheduleRequest.salesperson_name.like(like))
        )

    total = query.count()
    items = query.order_by(DesignScheduleRequest.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "total": total,
            "items": [
                {
                    "id": r.id,
                    "request_no": r.request_no,
                    "customer_name": r.customer_name,
                    "salesperson_id": r.salesperson_id,
                    "salesperson_name": r.salesperson_name,
                    "shoot_type": r.shoot_type,
                    "expect_start_date": r.expect_start_date.isoformat() if r.expect_start_date else None,
                    "expect_end_date": r.expect_end_date.isoformat() if r.expect_end_date else None,
                    "priority": r.priority,
                    "status": r.status,
                    "conflict_detail": r.conflict_detail,
                    "assigned_designer_id": r.assigned_designer_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in items
            ],
        },
    }


@router.get("/requests/{request_id}")
def get_request(request_id: int, db: Session = Depends(get_db)):
    """查询申请单详情"""
    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ).first()
    if not req:
        raise ValueError("申请单不存在")

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "id": req.id,
            "request_no": req.request_no,
            "customer_name": req.customer_name,
            "salesperson_id": req.salesperson_id,
            "salesperson_name": req.salesperson_name,
            "shoot_type": req.shoot_type,
            "shoot_type_remark": req.shoot_type_remark,
            "expect_start_date": req.expect_start_date.isoformat() if req.expect_start_date else None,
            "expect_end_date": req.expect_end_date.isoformat() if req.expect_end_date else None,
            "priority": req.priority,
            "remark": req.remark,
            "status": req.status,
            "conflict_detail": req.conflict_detail,
            "assigned_designer_id": req.assigned_designer_id,
            "actual_start_date": req.actual_start_date.isoformat() if req.actual_start_date else None,
            "actual_end_date": req.actual_end_date.isoformat() if req.actual_end_date else None,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "updated_at": req.updated_at.isoformat() if req.updated_at else None,
            "tasks": [
                {
                    "id": t.id,
                    "task_no": t.task_no,
                    "designer_id": t.designer_id,
                    "task_name": t.task_name,
                    "plan_start_date": t.plan_start_date.isoformat() if t.plan_start_date else None,
                    "plan_end_date": t.plan_end_date.isoformat() if t.plan_end_date else None,
                    "status": t.status,
                }
                for t in req.tasks
            ],
        },
    }


@router.post("/requests/{request_id}/audit")
def audit_request(
    request_id: int,
    data: DesignRequestAudit,
    db: Session = Depends(get_db),
):
    """主管审批申请单"""
    return service.audit_request(db, request_id, data, data.operator_id, data.operator_name)


@router.post("/requests/{request_id}/action")
def action_request(
    request_id: int,
    data: DesignRequestAction,
    db: Session = Depends(get_db),
):
    """执行申请单动作（confirm/start/complete/cancel）"""
    return service.action_request(
        db, request_id, data, data.operator_id, data.operator_name, data.operator_role
    )


# ── 甘特图 ────────────────────────────────────────────────


@router.get("/gantt")
def get_gantt(
    start_date: date = Query(...),
    end_date: date = Query(...),
    designer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """获取甘特图数据"""
    return service.get_gantt_data(db, start_date, end_date, designer_id)


# ── 任务管理 ──────────────────────────────────────────────


@router.get("/tasks")
def list_tasks(
    designer_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """查询任务列表"""
    query = db.query(DesignScheduleTask)
    if designer_id:
        query = query.filter(DesignScheduleTask.designer_id == designer_id)
    if status:
        query = query.filter(DesignScheduleTask.status == status)

    total = query.count()
    items = query.order_by(DesignScheduleTask.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "total": total,
            "items": [
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
                for t in items
            ],
        },
    }


@router.put("/tasks/{task_id}/reschedule")
def reschedule_task(
    task_id: int,
    data: TaskReschedule,
    db: Session = Depends(get_db),
):
    """任务改期"""
    return service.reschedule_task(db, task_id, data, data.operator_id, data.operator_name)


# ── 不可用日期 ────────────────────────────────────────────


@router.get("/unavailable-dates")
def list_unavailable_dates(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """查询不可用日期"""
    query = db.query(DesignUnavailableDate)
    if start_date:
        query = query.filter(DesignUnavailableDate.date >= start_date)
    if end_date:
        query = query.filter(DesignUnavailableDate.date <= end_date)

    rows = query.order_by(DesignUnavailableDate.date).all()
    return {
        "code": 200,
        "message": "ok",
        "data": [
            {
                "id": r.id,
                "date": r.date.isoformat(),
                "reason": r.reason,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/unavailable-dates")
def create_unavailable_dates(
    data: UnavailableDateCreate,
    db: Session = Depends(get_db),
):
    """批量设置不可用日期"""
    return service.create_unavailable_dates(db, data, data.operator_id, data.operator_name)


@router.delete("/unavailable-dates/{date_str}")
def delete_unavailable_date(
    date_str: str,
    operator_id: int = Query(1),
    operator_name: str = Query("管理员"),
    db: Session = Depends(get_db),
):
    """删除不可用日期"""
    return service.delete_unavailable_date(db, date_str, operator_id, operator_name)


# ── 容量配置 ──────────────────────────────────────────────


@router.get("/capacity")
def get_capacity(db: Session = Depends(get_db)):
    """获取容量配置"""
    return {"code": 200, "message": "ok", "data": service.get_capacity(db)}


@router.put("/capacity")
def update_capacity(
    data: CapacityUpdate,
    db: Session = Depends(get_db),
):
    """更新容量配置"""
    return service.update_capacity(db, data, data.operator_id, data.operator_name)


# ── 冲突检测 ──────────────────────────────────────────────


@router.get("/conflict-check")
def conflict_check(
    start_date: date = Query(...),
    end_date: date = Query(...),
    designer_id: Optional[int] = Query(None),
    exclude_task_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """前端实时冲突检查（不写库）"""
    from app.design.conflict_engine import check_conflict
    result = check_conflict(db, start_date, end_date, designer_id, exclude_task_id)
    return {"code": 200, "message": "ok", "data": result}


# ── 排期模式 ──────────────────────────────────────────────


@router.get("/scheduling-mode")
def get_scheduling_mode(db: Session = Depends(get_db)):
    """获取当前排期模式"""
    return service.get_scheduling_mode_info(db)


@router.put("/scheduling-mode")
def update_scheduling_mode(
    data: ModeUpdate,
    db: Session = Depends(get_db),
):
    """更新排期模式"""
    return service.update_scheduling_mode(db, data, data.operator_id, data.operator_name)


# ── 审计日志 ──────────────────────────────────────────────


@router.get("/audit-logs/{request_id}")
def get_audit_logs_by_request(request_id: int, db: Session = Depends(get_db)):
    """查询指定申请单的操作日志"""
    items = db.query(DesignAuditLog).filter(
        DesignAuditLog.request_id == request_id,
    ).order_by(DesignAuditLog.created_at.asc()).all()

    return {
        "code": 200,
        "message": "ok",
        "data": [
            {
                "id": log.id,
                "request_id": log.request_id,
                "task_id": log.task_id,
                "operator_id": log.operator_id,
                "operator_name": log.operator_name,
                "operator_role": log.operator_role,
                "action": log.action,
                "from_status": log.from_status,
                "to_status": log.to_status,
                "comment": log.comment,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in items
        ],
    }


# ── 设计师管理 ────────────────────────────────────────────


@router.get("/designers")
def list_designers(
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    """查询设计师列表"""
    query = db.query(DesignDesigner)
    if is_active is not None:
        query = query.filter(DesignDesigner.is_active == is_active)

    designers = query.all()
    return {
        "code": 200,
        "message": "ok",
        "data": [
            {
                "id": d.id,
                "name": d.name,
                "dingtalk_id": d.dingtalk_id,
                "email": d.email,
                "is_active": d.is_active,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in designers
        ],
    }


# ── 导出 Excel ────────────────────────────────────────────


@router.get("/export/tasks")
def export_tasks(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
):
    """导出设计任务为 Excel"""
    return service.export_tasks_excel(db, start_date, end_date)


# ── 统计报表 ──────────────────────────────────────────────


@router.get("/stats")
def get_stats(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
):
    """获取设计模块统计"""
    return service.get_design_stats(db, start_date, end_date)


# ── 批量导入 ──────────────────────────────────────────────


@router.post("/import/requests")
async def import_requests(
    file: UploadFile = File(...),
    operator_id: int = Query(1),
    operator_name: str = Query("管理员"),
    operator_role: str = Query("salesperson"),
    db: Session = Depends(get_db),
):
    """批量导入预约申请"""
    contents = await file.read()
    return service.batch_import_requests(
        db, contents, operator_id, operator_name, operator_role
    )
