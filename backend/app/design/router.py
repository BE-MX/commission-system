"""设计预约 — API 路由"""

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, File, UploadFile, BackgroundTasks
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

logger = logging.getLogger("design")

router = APIRouter()


# ── 申请单 CRUD ───────────────────────────────────────────


@router.post("/requests")
def create_request(
    data: DesignRequestCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """提交设计预约申请"""
    result = service.create_request(
        db, data, data.operator_id, data.operator_name, data.operator_role
    )

    # 触发钉钉通知
    req_status = result.get("data", {}).get("status")
    level_label, type_label = _translate_dict_fields(
        db, data.customer_level or "", data.shoot_type or "",
    )
    notify_kwargs = dict(
        request_no=result["data"]["request_no"],
        salesperson_name=data.salesperson_name or data.operator_name,
        customer_name=data.customer_name,
        customer_level=level_label,
        shoot_type=type_label,
        schedule_date=_fmt_schedule_date(
            data.expect_start_date, data.expect_end_date,
            data.expect_start_period, data.expect_end_period,
        ),
        priority=data.priority or "normal",
        remark=data.remark or "",
    )

    if req_status == "pending_audit":
        # 有冲突 → 通知主管审批
        background_tasks.add_task(
            _notify_audit_needed,
            db=db,
            conflict=result["data"].get("conflict"),
            **notify_kwargs,
        )
    elif req_status == "pending_design":
        # 无冲突 → 直接通知设计部
        background_tasks.add_task(
            _notify_design_dept,
            db=db,
            source="直接提交",
            **notify_kwargs,
        )

    return result


def _find_role_dingtalk_ids(db: Session, role_name: str) -> list[str]:
    """查找指定角色下所有已绑定钉钉的活跃用户ID"""
    from app.auth.models import ArkUser, ArkRole, ArkUserRole

    users = db.query(ArkUser).join(
        ArkUserRole, ArkUser.id == ArkUserRole.user_id
    ).join(
        ArkRole, ArkRole.id == ArkUserRole.role_id
    ).filter(
        ArkRole.name == role_name,
        ArkUser.is_active == True,
        ArkUser.deleted_at.is_(None),
        ArkUser.dingtalk_id.isnot(None),
        ArkUser.dingtalk_id != "",
    ).all()

    return [u.dingtalk_id for u in users]


_PERIOD_LABELS = {"am": "上午", "pm": "下午"}


def _fmt_schedule_date(
    start_date, end_date,
    start_period: str | None = None,
    end_period: str | None = None,
) -> str:
    """格式化期望日期，带上午/下午"""
    s = str(start_date)
    e = str(end_date)
    sp = _PERIOD_LABELS.get(start_period, "")
    ep = _PERIOD_LABELS.get(end_period, "")
    return f"{s} {sp} ~ {e} {ep}".strip()


def _translate_dict_fields(db: Session, customer_level: str, shoot_type: str) -> tuple[str, str]:
    """将客户等级和拍摄类型的字典 code 翻译为显示名"""
    from app.system.service import get_label_map as _get_dict_map

    level_label = customer_level
    if customer_level:
        level_map = _get_dict_map(db, "customer_level")
        level_label = level_map.get(customer_level, customer_level)

    type_label = shoot_type
    if shoot_type:
        type_map = _get_dict_map(db, "shoot_type")
        codes = [c.strip() for c in shoot_type.split(",") if c.strip()]
        type_label = "、".join(type_map.get(c, c) for c in codes)

    return level_label, type_label


async def _notify_audit_needed(
    db: Session,
    request_no: str,
    salesperson_name: str,
    customer_name: str,
    customer_level: str,
    shoot_type: str,
    schedule_date: str,
    priority: str,
    remark: str,
    conflict: dict | None = None,
):
    """查找所有主管的钉钉ID，发送审批通知"""
    from app.dingtalk.events import notify_design_audit_needed

    dingtalk_ids = _find_role_dingtalk_ids(db, "supervisor")

    # 构建冲突摘要
    conflict_summary = ""
    if conflict:
        parts = []
        unavail = conflict.get("conflicting_unavailable_slots", [])
        overload = conflict.get("overloaded_dates", [])
        if unavail:
            parts.append(f"包含 {len(unavail)} 个不可用时段")
        if overload:
            parts.append(f"{len(overload)} 个时段超容量")
        conflict_summary = "，".join(parts)

    await notify_design_audit_needed(
        reviewer_dingtalk_ids=dingtalk_ids,
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=customer_level,
        shoot_type=shoot_type,
        schedule_date=schedule_date,
        priority=priority,
        remark=remark,
        conflict_summary=conflict_summary,
    )


async def _notify_design_dept(
    db: Session,
    request_no: str,
    salesperson_name: str,
    customer_name: str,
    customer_level: str,
    shoot_type: str,
    schedule_date: str,
    priority: str,
    remark: str,
    source: str = "",
):
    """查找设计部所有成员的钉钉ID，发送待排期通知"""
    from app.dingtalk.events import notify_design_ready_for_design

    dingtalk_ids = _find_role_dingtalk_ids(db, "design_staff")

    await notify_design_ready_for_design(
        designer_dingtalk_ids=dingtalk_ids,
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=customer_level,
        shoot_type=shoot_type,
        schedule_date=schedule_date,
        priority=priority,
        remark=remark,
        source=source,
    )


@router.get("/requests")
def list_requests(
    status: Optional[str] = Query(None),
    salesperson_id: Optional[int] = Query(None),
    keyword: Optional[str] = Query(None),
    expect_start_date: Optional[str] = Query(None, description="期望开始日期 >=，格式 YYYY-MM-DD"),
    expect_end_date: Optional[str] = Query(None, description="期望开始日期 <=，格式 YYYY-MM-DD"),
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
    if expect_start_date:
        from datetime import date as _date
        query = query.filter(DesignScheduleRequest.expect_start_date >= _date.fromisoformat(expect_start_date))
    if expect_end_date:
        from datetime import date as _date
        query = query.filter(DesignScheduleRequest.expect_start_date <= _date.fromisoformat(expect_end_date))

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
                    "customer_level": r.customer_level,
                    "salesperson_id": r.salesperson_id,
                    "salesperson_name": r.salesperson_name,
                    "shoot_type": r.shoot_type,
                    "expect_start_date": r.expect_start_date.isoformat() if r.expect_start_date else None,
                    "expect_start_period": r.expect_start_period,
                    "expect_end_date": r.expect_end_date.isoformat() if r.expect_end_date else None,
                    "expect_end_period": r.expect_end_period,
                    "priority": r.priority,
                    "remark": r.remark,
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
            "customer_level": req.customer_level,
            "salesperson_id": req.salesperson_id,
            "salesperson_name": req.salesperson_name,
            "shoot_type": req.shoot_type,
            "shoot_type_remark": req.shoot_type_remark,
            "expect_start_date": req.expect_start_date.isoformat() if req.expect_start_date else None,
            "expect_start_period": req.expect_start_period,
            "expect_end_date": req.expect_end_date.isoformat() if req.expect_end_date else None,
            "expect_end_period": req.expect_end_period,
            "priority": req.priority,
            "remark": req.remark,
            "status": req.status,
            "conflict_detail": req.conflict_detail,
            "assigned_designer_id": req.assigned_designer_id,
            "actual_start_date": req.actual_start_date.isoformat() if req.actual_start_date else None,
            "actual_start_period": req.actual_start_period,
            "actual_end_date": req.actual_end_date.isoformat() if req.actual_end_date else None,
            "actual_end_period": req.actual_end_period,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "updated_at": req.updated_at.isoformat() if req.updated_at else None,
            "tasks": [
                {
                    "id": t.id,
                    "task_no": t.task_no,
                    "designer_id": t.designer_id,
                    "task_name": t.task_name,
                    "plan_start_date": t.plan_start_date.isoformat() if t.plan_start_date else None,
                    "plan_start_period": t.plan_start_period,
                    "plan_end_date": t.plan_end_date.isoformat() if t.plan_end_date else None,
                    "plan_end_period": t.plan_end_period,
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """主管审批申请单"""
    result = service.audit_request(db, request_id, data, data.operator_id, data.operator_name)

    # 审批完成后通知申请人
    background_tasks.add_task(
        _notify_audit_result,
        db=db,
        request_id=request_id,
        action=data.action,
        comment=data.comment,
    )

    return result


async def _notify_audit_result(
    db: Session,
    request_id: int,
    action: str,
    comment: str | None = None,
):
    """审批通过/拒绝后向申请人发送点对点通知；通过时同时通知设计部"""
    from app.auth.models import ArkUser
    from app.dingtalk.events import (
        notify_design_request_approved,
        notify_design_request_rejected,
        notify_design_ready_for_design,
    )

    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == request_id
    ).first()
    if not req:
        return

    # 查申请人的钉钉ID
    applicant_dingtalk_id = ""
    if req.salesperson_id:
        applicant = db.query(ArkUser).filter(ArkUser.id == req.salesperson_id).first()
        if applicant and applicant.dingtalk_id:
            applicant_dingtalk_id = applicant.dingtalk_id

    schedule_date = ""
    if req.expect_start_date and req.expect_end_date:
        schedule_date = _fmt_schedule_date(
            req.expect_start_date, req.expect_end_date,
            req.expect_start_period, req.expect_end_period,
        )

    level_label, type_label = _translate_dict_fields(
        db, req.customer_level or "", req.shoot_type or "",
    )

    common = dict(
        request_no=req.request_no,
        salesperson_name=req.salesperson_name or "",
        customer_name=req.customer_name,
        customer_level=level_label,
        shoot_type=type_label,
        schedule_date=schedule_date,
        priority=req.priority or "normal",
        remark=req.remark or "",
    )

    if action == "approve":
        # 通知申请人
        await notify_design_request_approved(
            applicant_dingtalk_id=applicant_dingtalk_id,
            **common,
        )
        # 通知设计部
        design_ids = _find_role_dingtalk_ids(db, "design_staff")
        await notify_design_ready_for_design(
            designer_dingtalk_ids=design_ids,
            source="审核通过",
            **common,
        )
    elif action == "reject":
        await notify_design_request_rejected(
            applicant_dingtalk_id=applicant_dingtalk_id,
            reject_reason=comment or "未说明原因",
            **common,
        )


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
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            query = query.filter(DesignScheduleTask.status == statuses[0])
        elif statuses:
            query = query.filter(DesignScheduleTask.status.in_(statuses))

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
                    "plan_start_period": t.plan_start_period,
                    "plan_end_date": t.plan_end_date.isoformat() if t.plan_end_date else None,
                    "plan_end_period": t.plan_end_period,
                    "actual_start_date": t.actual_start_date.isoformat() if t.actual_start_date else None,
                    "actual_start_period": t.actual_start_period,
                    "actual_end_date": t.actual_end_date.isoformat() if t.actual_end_date else None,
                    "actual_end_period": t.actual_end_period,
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
                "period": r.period,
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
    period: Optional[str] = Query(None),
    operator_id: int = Query(1),
    operator_name: str = Query("管理员"),
    db: Session = Depends(get_db),
):
    """删除不可用日期"""
    return service.delete_unavailable_date(db, date_str, operator_id, operator_name, period=period)


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
    start_period: Optional[str] = Query(None),
    end_period: Optional[str] = Query(None),
    designer_id: Optional[int] = Query(None),
    exclude_task_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """前端实时冲突检查（不写库）"""
    from app.design.conflict_engine import check_conflict
    result = check_conflict(
        db, start_date, end_date,
        start_period=start_period or "am",
        end_period=end_period or "pm",
        designer_id=designer_id,
        exclude_task_id=exclude_task_id,
    )
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


@router.post("/designers")
def create_designer(
    data: dict,
    db: Session = Depends(get_db),
):
    """新建设计师"""
    designer = DesignDesigner(
        name=data["name"],
        dingtalk_id=data.get("dingtalk_id"),
        email=data.get("email"),
        is_active=data.get("is_active", True),
    )
    db.add(designer)
    db.commit()
    db.refresh(designer)
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "id": designer.id,
            "name": designer.name,
            "dingtalk_id": designer.dingtalk_id,
            "email": designer.email,
            "is_active": designer.is_active,
        },
    }


@router.put("/designers/{designer_id}")
def update_designer(
    designer_id: int,
    data: dict,
    db: Session = Depends(get_db),
):
    """编辑设计师"""
    designer = db.query(DesignDesigner).filter(DesignDesigner.id == designer_id).first()
    if not designer:
        return {"code": 404, "message": "设计师不存在", "data": None}

    for field in ("name", "dingtalk_id", "email", "is_active"):
        if field in data:
            setattr(designer, field, data[field])

    db.commit()
    db.refresh(designer)
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "id": designer.id,
            "name": designer.name,
            "dingtalk_id": designer.dingtalk_id,
            "email": designer.email,
            "is_active": designer.is_active,
        },
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
