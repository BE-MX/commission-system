"""设计预约 — 申请单 CRUD / 审批 / 操作 / 修改备注与拍摄类型"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.design.models import (
    DesignScheduleRequest,
    DesignScheduleTask,
)
from app.design.state_machine import RequestStatus, OperatorRole, transition
from app.design.conflict_engine import check_conflict
from app.design.utils import generate_request_no, generate_task_no
from app.design.schemas import (
    DesignRequestCreate,
    DesignRequestAudit,
    DesignRequestAction,
)
from app.design.audit_log import write_audit_log as _write_audit_log

logger = __import__("logging").getLogger("design")


def create_request(
    db: Session,
    data: DesignRequestCreate,
    operator_id: int,
    operator_name: str,
    operator_role: str,
) -> dict:
    """创建设计预约申请"""
    # 冲突检测
    conflict = check_conflict(
        db, data.expect_start_date, data.expect_end_date,
        start_period=data.expect_start_period or "am",
        end_period=data.expect_end_period or "pm",
    )

    # Route to pending_design (skip audit) when no conflict and no unavailable overlap
    has_any_issue = conflict["has_conflict"]
    initial_status = "pending_audit" if has_any_issue else "pending_design"

    request_no = generate_request_no(db)

    req = DesignScheduleRequest(
        request_no=request_no,
        customer_name=data.customer_name,
        customer_level=data.customer_level,
        salesperson_id=data.salesperson_id,
        salesperson_name=data.salesperson_name,
        shoot_type=data.shoot_type,
        shoot_type_remark=data.shoot_type_remark,
        props_requirement=data.props_requirement,
        expect_start_date=data.expect_start_date,
        expect_start_period=data.expect_start_period or "am",
        expect_end_date=data.expect_end_date,
        expect_end_period=data.expect_end_period or "pm",
        priority=data.priority,
        remark=data.remark,
        preferred_designer_id=data.preferred_designer_id,
        status=initial_status,
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
        to_status=initial_status,
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
            plan_start_period=data.plan_start_period or req.expect_start_period or "am",
            plan_end_date=data.plan_end_date or req.expect_end_date,
            plan_end_period=data.plan_end_period or req.expect_end_period or "pm",
            status="scheduled",
            remark=data.comment,
        )
        db.add(task)
        db.flush()
        task_id = task.id
        req.assigned_designer_id = data.designer_id

        # 同步设置为不可用日期（跳过已存在的）
        if data.sync_unavailable:
            from datetime import timedelta
            from app.design.models import DesignUnavailableDate

            current = data.plan_start_date or req.expect_start_date
            end = data.plan_end_date or req.expect_end_date
            created_dates = []
            while current and end and current <= end:
                exists = db.query(DesignUnavailableDate).filter(
                    DesignUnavailableDate.date == current
                ).first()
                if not exists:
                    row = DesignUnavailableDate(
                        date=current,
                        period=None,
                        reason=f"排期任务 {task_no}",
                        created_by=operator_id,
                    )
                    db.add(row)
                    created_dates.append(current.isoformat())
                current += timedelta(days=1)
            if created_dates:
                logger.info("同步设置不可用日期: %s", created_dates)

    elif data.action == "start":
        req.actual_start_date = date.today()
        req.actual_start_period = "am"
        for t in req.tasks:
            if t.status == "scheduled":
                t.status = "in_progress"
                t.actual_start_date = date.today()
                t.actual_start_period = "am"
                t.updated_at = datetime.now()

    elif data.action == "complete":
        req.actual_end_date = date.today()
        req.actual_end_period = "pm"
        for t in req.tasks:
            if t.status == "in_progress":
                t.status = "completed"
                t.actual_end_date = date.today()
                t.actual_end_period = "pm"
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


def update_request_remark(
    db: Session,
    request_id: int,
    remark: str | None,
    operator_id: int,
    operator_name: str,
) -> dict:
    """修改预约单备注"""
    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ).first()
    if not req:
        raise ValueError("申请单不存在")

    req.remark = remark
    req.updated_at = datetime.now()
    db.commit()
    db.refresh(req)

    return {"code": 200, "message": "备注已更新", "data": None}


def update_request_shoot_type(
    db: Session,
    request_id: int,
    shoot_type: str,
    operator_id: int,
    operator_name: str,
) -> dict:
    """修改预约单拍摄类型"""
    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ).first()
    if not req:
        raise ValueError("申请单不存在")

    old_shoot_type = req.shoot_type
    req.shoot_type = shoot_type
    req.updated_at = datetime.now()

    _write_audit_log(
        db,
        request_id=req.id,
        operator_id=operator_id,
        operator_name=operator_name,
        operator_role="design_staff",
        action="reschedule",
        from_status=req.status,
        to_status=req.status,
        comment=f"修改拍摄类型: {old_shoot_type} → {shoot_type}",
    )
    db.commit()
    db.refresh(req)

    return {"code": 200, "message": "拍摄类型已更新", "data": None}


def update_task_shoot_type(
    db: Session,
    task_id: int,
    shoot_type: str,
    operator_id: int,
    operator_name: str,
) -> dict:
    """修改任务拍摄类型（同步更新关联预约单）"""
    task = db.query(DesignScheduleTask).filter(
        DesignScheduleTask.id == task_id,
    ).first()
    if not task:
        raise ValueError("任务不存在")

    old_shoot_type = task.shoot_type
    task.shoot_type = shoot_type
    task.updated_at = datetime.now()

    # 同步更新关联 request 的拍摄类型
    req = db.query(DesignScheduleRequest).filter(
        DesignScheduleRequest.id == task.request_id,
        DesignScheduleRequest.deleted_at.is_(None),
    ).first()
    if req:
        req.shoot_type = shoot_type
        req.updated_at = datetime.now()

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
        comment=f"修改拍摄类型: {old_shoot_type} → {shoot_type}",
    )
    db.commit()
    db.refresh(task)

    return {"code": 200, "message": "拍摄类型已更新", "data": None}
