"""设计预约 — 定时任务"""

import logging
from datetime import date

from app.core.database import SessionLocal
from app.design.models import DesignScheduleRequest

logger = logging.getLogger("design.scheduler")


async def check_today_shoot_reminders():
    """扫描待确认和已排期任务中排期日期=今天的预约单，推送钉钉提醒"""
    db = SessionLocal()
    try:
        from app.design.models import DesignScheduleTask

        today = date.today()

        # 1. 待确认预约单（pending_design）：期望开始日期=今天
        pending_requests = db.query(DesignScheduleRequest).filter(
            DesignScheduleRequest.deleted_at.is_(None),
            DesignScheduleRequest.status == "pending_design",
            DesignScheduleRequest.expect_start_date == today,
        ).all()

        # 2. 已排期/进行中任务（scheduled / in_progress）：计划开始日期=今天
        scheduled_tasks = db.query(DesignScheduleTask).filter(
            DesignScheduleTask.status.in_(["scheduled", "in_progress"]),
            DesignScheduleTask.plan_start_date == today,
        ).all()

        # 按 request 聚合今天的排期任务：精确定位被指派设计师 + 展示实际排期日期
        tasks_by_request: dict[int, list[DesignScheduleTask]] = {}
        for task in scheduled_tasks:
            tasks_by_request.setdefault(task.request_id, []).append(task)

        # 合并去重：以 request 为单位
        seen_ids = set()
        requests = []
        for req in pending_requests:
            if req.id not in seen_ids:
                seen_ids.add(req.id)
                requests.append(req)
        for task in scheduled_tasks:
            if task.request_id not in seen_ids:
                seen_ids.add(task.request_id)
                req = db.get(DesignScheduleRequest, task.request_id)
                if req and req.deleted_at is None:
                    requests.append(req)

        if not requests:
            logger.info("今日无需提醒的拍摄预约或排期任务")
            return

        from app.auth.models import ArkUser
        from app.design.models import DesignDesigner
        from app.design.notifications import _find_role_dingtalk_ids, _translate_dict_fields, _fmt_schedule_date, _get_designer_name

        design_ids = _find_role_dingtalk_ids(db, "design_staff")

        # 被指派设计师的钉钉ID在 design_designer 表（与 design_staff 角色是两套独立名单，
        # 设计师账号通常挂 designer 角色，不在 design_staff 广播名单里——必须按任务到人）
        assigned_ids = {t.designer_id for t in scheduled_tasks}
        designers_by_id = {
            d.id: d
            for d in db.query(DesignDesigner).filter(DesignDesigner.id.in_(assigned_ids)).all()
        } if assigned_ids else {}

        for req in requests:
            today_tasks = tasks_by_request.get(req.id, [])

            # 查申请人钉钉ID
            applicant_dingtalk_id = ""
            if req.salesperson_id:
                applicant = db.query(ArkUser).filter(ArkUser.id == req.salesperson_id).first()
                if applicant and applicant.dingtalk_id:
                    applicant_dingtalk_id = applicant.dingtalk_id

            # 被指派设计师：排期任务的提醒必须直达本人，不依赖角色广播
            designer_dingtalk_ids = []
            designer_names = []
            for t in today_tasks:
                d = designers_by_id.get(t.designer_id)
                if d is None:
                    continue
                designer_names.append(d.name)
                if d.dingtalk_id:
                    designer_dingtalk_ids.append(d.dingtalk_id)
                else:
                    msg = f"设计师 {d.name}(id={d.id}) 未绑定钉钉ID，今日排期提醒无法直达 (任务: {t.task_no})"
                    logger.warning(msg)
                    print(msg, flush=True)

            designer_names = list(dict.fromkeys(designer_names))  # 同一设计师多任务去重
            all_ids = list(set(
                ([applicant_dingtalk_id] if applicant_dingtalk_id else [])
                + design_ids + designer_dingtalk_ids
            ))
            if not all_ids:
                continue

            level_label, type_label, props_label = _translate_dict_fields(
                db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
            )
            # 已排期任务展示任务的计划日期（预约单的期望日期可能早已过时）
            if today_tasks:
                t0 = today_tasks[0]
                schedule_date = _fmt_schedule_date(
                    t0.plan_start_date, t0.plan_end_date,
                    t0.plan_start_period, t0.plan_end_period,
                )
            else:
                schedule_date = _fmt_schedule_date(
                    req.expect_start_date, req.expect_end_date,
                    req.expect_start_period, req.expect_end_period,
                )
            preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"

            from app.dingtalk.work_notify import get_work_notifier
            from app.dingtalk.events import _build_request_markdown

            # 区分提醒标题
            if req.status == "pending_design":
                reminder_title = "⏰ 拍摄提醒：今日有预约待处理"
            else:
                reminder_title = "⏰ 拍摄提醒：今日有排期任务"

            md = _build_request_markdown(
                reminder_title,
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
                extra_lines=[f"设计师：{'、'.join(designer_names)}"] if designer_names else None,
            )

            notifier = get_work_notifier()
            try:
                await notifier.send_to_users(
                    user_ids=all_ids,
                    title="拍摄提醒",
                    markdown_text=md,
                )
                logger.info("拍摄提醒已发送: %s -> %s", req.request_no, all_ids)
            except Exception as e:
                logger.warning("拍摄提醒发送失败 %s: %s", req.request_no, e)
                print(f"拍摄提醒发送失败 {req.request_no}: {e}", flush=True)
    finally:
        db.close()


