"""设计预约 — 钉钉通知 helper 与字段翻译

router.py 的私有 helper 函数集中处, 包括:
- 钉钉用户/角色查询 (按角色查 dingtalk_id)
- 字段格式化 (期望日期/字典翻译/设计师名)
- 通知发送 (审批待定/通过/拒绝/状态变更/排期变更/设计师变更)
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.auth.models import ArkUser
from app.design.models import (
    DesignScheduleRequest, DesignScheduleTask, DesignDesigner,
)
from app.dingtalk.events import (
    notify_design_audit_needed,
    notify_design_ready_for_design,
    notify_design_request_approved,
    notify_design_request_rejected,
    notify_design_status_change,
)
from app.system.service import get_label_map as _get_dict_map

logger = logging.getLogger("design")


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


def _translate_dict_fields(db: Session, customer_level: str, shoot_type: str, props_requirement: str = "") -> tuple[str, str, str]:
    """将客户等级、拍摄类型、道具要求的字典 code 翻译为显示名"""
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

    props_label = ""
    if props_requirement:
        props_map = _get_dict_map(db, "props_requirement")
        codes = [c.strip() for c in props_requirement.split(",") if c.strip()]
        props_label = "、".join(props_map.get(c, c) for c in codes)

    return level_label, type_label, props_label


def _get_designer_name(db: Session, designer_id: int | None) -> str:
    """根据设计师ID获取姓名"""
    if not designer_id:
        return ""
    from app.design.models import DesignDesigner
    d = db.query(DesignDesigner).filter(DesignDesigner.id == designer_id).first()
    return d.name if d else ""


async def _notify_audit_needed(
    request_no: str,
    salesperson_name: str,
    customer_name: str,
    customer_level: str,
    shoot_type: str,
    schedule_date: str,
    priority: str,
    remark: str,
    conflict: dict | None = None,
    props_requirement: str = "",
    preferred_designer: str = "",
):
    """查找所有主管的钉钉ID，发送审批通知（内部新建 Session）"""
    from app.dingtalk.events import notify_design_audit_needed
    from app.core.database import SessionLocal

    with SessionLocal() as db:
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
    request_no: str,
    salesperson_name: str,
    customer_name: str,
    customer_level: str,
    shoot_type: str,
    schedule_date: str,
    priority: str,
    remark: str,
    source: str = "",
    props_requirement: str = "",
    preferred_designer: str = "",
):
    """查找设计部所有成员的钉钉ID，发送待排期通知（内部新建 Session）"""
    from app.dingtalk.events import notify_design_ready_for_design
    from app.core.database import SessionLocal

    with SessionLocal() as db:
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


async def _notify_audit_result(
    request_id: int,
    action: str,
    comment: str | None = None,
):
    """审批通过/拒绝后向申请人发送点对点通知；通过时同时通知设计部（内部新建 Session）"""
    from app.auth.models import ArkUser
    from app.dingtalk.events import (
        notify_design_request_approved,
        notify_design_request_rejected,
        notify_design_ready_for_design,
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
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

        level_label, type_label, props_label = _translate_dict_fields(
            db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
        )
        preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"

        common = dict(
            request_no=req.request_no,
            salesperson_name=req.salesperson_name or "",
            customer_name=req.customer_name,
            customer_level=level_label,
            shoot_type=type_label,
            props_requirement=props_label,
            schedule_date=schedule_date,
            priority=req.priority or "normal",
            remark=req.remark or "",
            preferred_designer=preferred_name,
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


_ACTION_TITLES = {
    "confirm": "📅 你的设计预约已排期",
    "start": "🚀 你的设计预约已开始执行",
    "complete": "🎉 你的设计预约已完成",
}


async def _notify_action_to_applicant(
    request_id: int,
    action: str,
):
    """confirm/start/complete 后向申请人发送状态变更通知（内部新建 Session）"""
    from app.auth.models import ArkUser
    from app.dingtalk.events import notify_design_status_change
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        req = db.query(DesignScheduleRequest).filter(
            DesignScheduleRequest.id == request_id,
        ).first()
        if not req:
            return

        # 查申请人的钉钉ID
        applicant_dingtalk_id = ""
        if req.salesperson_id:
            applicant = db.query(ArkUser).filter(ArkUser.id == req.salesperson_id).first()
            if applicant and applicant.dingtalk_id:
                applicant_dingtalk_id = applicant.dingtalk_id

        if not applicant_dingtalk_id:
            return

        schedule_date = ""
        if req.expect_start_date and req.expect_end_date:
            schedule_date = _fmt_schedule_date(
                req.expect_start_date, req.expect_end_date,
                req.expect_start_period, req.expect_end_period,
            )

        level_label, type_label, props_label = _translate_dict_fields(
            db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
        )
        preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"

        # 优先使用任务的备注（排期确认备注），其次用预约单备注
        task_remark = req.remark or ""
        for t in req.tasks:
            if t.status not in ("cancelled",):
                task_remark = t.remark or req.remark or ""
                break

        # 构建额外信息
        extra = []
        if action == "confirm" and req.assigned_designer_id:
            designer_name = _get_designer_name(db, req.assigned_designer_id)
            if designer_name:
                extra.append(f"设计师：{designer_name}")

        title = _ACTION_TITLES.get(action, f"预约单状态更新: {action}")

    await notify_design_status_change(
        applicant_dingtalk_id,
        title=title,
        request_no=req.request_no,
        salesperson_name=req.salesperson_name or "",
        customer_name=req.customer_name,
        customer_level=level_label,
        shoot_type=type_label,
        props_requirement=props_label,
        schedule_date=schedule_date,
        priority=req.priority or "normal",
        remark=task_remark,
        preferred_designer=preferred_name,
        extra_lines=extra or None,
    )


async def _notify_confirm_to_designer(request_id: int):
    """确认排期后向被指派的设计师发送通知（内部新建 Session）"""
    from app.dingtalk.events import notify_design_status_change
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        req = db.query(DesignScheduleRequest).filter(
            DesignScheduleRequest.id == request_id,
        ).first()
        if not req or not req.assigned_designer_id:
            return

        # 查设计师的钉钉ID（DesignDesigner 表自带 dingtalk_id 字段）
        designer = db.query(DesignDesigner).filter(
            DesignDesigner.id == req.assigned_designer_id,
        ).first()
        if not designer or not designer.dingtalk_id:
            logger.info(
                "设计师 %s 未绑定钉钉ID，跳过指派通知 (单号: %s)",
                req.assigned_designer_id, req.request_no,
            )
            return

        schedule_date = ""
        if req.expect_start_date and req.expect_end_date:
            schedule_date = _fmt_schedule_date(
                req.expect_start_date, req.expect_end_date,
                req.expect_start_period, req.expect_end_period,
            )

        level_label, type_label, props_label = _translate_dict_fields(
            db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
        )
        preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"

        # 优先使用任务的备注（排期确认备注），其次用预约单备注
        task_remark = req.remark or ""
        for t in req.tasks:
            if t.status not in ("cancelled",):
                task_remark = t.remark or req.remark or ""
                break

        # 在 session 关闭前抽出所有需要的字段
        designer_dingtalk_id = designer.dingtalk_id
        request_no = req.request_no
        salesperson_name = req.salesperson_name or ""
        customer_name = req.customer_name
        priority = req.priority or "normal"

    await notify_design_status_change(
        designer_dingtalk_id,
        title="📐 你有新的设计任务",
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=level_label,
        shoot_type=type_label,
        props_requirement=props_label,
        schedule_date=schedule_date,
        priority=priority,
        remark=task_remark,
        preferred_designer=preferred_name,
    )


async def _notify_reschedule_designer_changed(task_id: int, new_designer_id: int):
    """改期时设计师变更 → 通知新设计师"""
    from app.dingtalk.events import notify_design_status_change
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        task = db.query(DesignScheduleTask).filter(
            DesignScheduleTask.id == task_id,
        ).first()
        if not task:
            return
        req = db.query(DesignScheduleRequest).filter(
            DesignScheduleRequest.id == task.request_id,
        ).first()
        if not req:
            return

        designer = db.query(DesignDesigner).filter(
            DesignDesigner.id == new_designer_id,
        ).first()
        if not designer or not designer.dingtalk_id:
            return

        schedule_date = _fmt_schedule_date(
            task.plan_start_date, task.plan_end_date,
            task.plan_start_period, task.plan_end_period,
        )
        level_label, type_label, props_label = _translate_dict_fields(
            db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
        )
        preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"
        task_remark = task.remark or req.remark or ""

        designer_dingtalk_id = designer.dingtalk_id
        request_no = req.request_no
        customer_name = req.customer_name
        priority = req.priority or "normal"
        salesperson_name = req.salesperson_name or ""

    await notify_design_status_change(
        designer_dingtalk_id,
        title="📐 设计任务设计师变更通知",
        request_no=request_no,
        salesperson_name=salesperson_name,
        customer_name=customer_name,
        customer_level=level_label,
        shoot_type=type_label,
        props_requirement=props_label,
        schedule_date=schedule_date,
        priority=priority,
        remark=task_remark,
        preferred_designer=preferred_name,
        extra_lines=["你已被指派为该任务的新设计师"],
    )


async def _notify_reschedule_date_changed(
    task_id: int,
    new_start: str,
    new_start_period: str,
    new_end: str,
    new_end_period: str,
    comment: str | None = None,
):
    """改期时日期变更 → 通知设计师 + 申请人"""
    from app.auth.models import ArkUser
    from app.dingtalk.events import notify_design_status_change
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        task = db.query(DesignScheduleTask).filter(
            DesignScheduleTask.id == task_id,
        ).first()
        if not task:
            return
        req = db.query(DesignScheduleRequest).filter(
            DesignScheduleRequest.id == task.request_id,
        ).first()
        if not req:
            return

        schedule_date = _fmt_schedule_date(
            task.plan_start_date, task.plan_end_date,
            task.plan_start_period, task.plan_end_period,
        )
        level_label, type_label, props_label = _translate_dict_fields(
            db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
        )
        preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"
        task_remark = task.remark or req.remark or ""

        # 收集接收人
        recipients = []

        # 设计师
        designer = db.query(DesignDesigner).filter(
            DesignDesigner.id == task.designer_id,
        ).first()
        if designer and designer.dingtalk_id:
            recipients.append(("designer", designer.dingtalk_id))

        # 申请人
        applicant_dingtalk_id = ""
        if req.salesperson_id:
            applicant = db.query(ArkUser).filter(ArkUser.id == req.salesperson_id).first()
            if applicant and applicant.dingtalk_id:
                applicant_dingtalk_id = applicant.dingtalk_id
                recipients.append(("applicant", applicant_dingtalk_id))

        request_no = req.request_no
        customer_name = req.customer_name
        priority = req.priority or "normal"
        salesperson_name = req.salesperson_name or ""

    extra = [f"新排期：{new_start} {_PERIOD_LABELS.get(new_start_period, '')} ~ {new_end} {_PERIOD_LABELS.get(new_end_period, '')}"]
    if comment:
        extra.append(f"改期备注：{comment}")

    for role, dingtalk_id in recipients:
        title = "📅 设计预约排期变更通知" if role == "applicant" else "📅 设计任务排期变更通知"
        await notify_design_status_change(
            dingtalk_id,
            title=title,
            request_no=request_no,
            salesperson_name=salesperson_name,
            customer_name=customer_name,
            customer_level=level_label,
            shoot_type=type_label,
            props_requirement=props_label,
            schedule_date=schedule_date,
            priority=priority,
            remark=task_remark,
            preferred_designer=preferred_name,
            extra_lines=extra,
        )
