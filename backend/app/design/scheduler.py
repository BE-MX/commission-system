"""设计预约 — 定时任务"""

import logging
from datetime import date, datetime

from app.core.database import SessionLocal
from app.design.models import DesignScheduleRequest

logger = logging.getLogger("design.scheduler")


async def check_today_shoot_reminders():
    """扫描待确认任务中期望开始日期=今天的预约单，推送钉钉提醒"""
    db = SessionLocal()
    try:
        today = date.today()
        requests = db.query(DesignScheduleRequest).filter(
            DesignScheduleRequest.deleted_at.is_(None),
            DesignScheduleRequest.status == "pending_design",
            DesignScheduleRequest.expect_start_date == today,
        ).all()

        if not requests:
            logger.info("今日无需提醒的拍摄预约")
            return

        from app.auth.models import ArkUser, ArkRole, ArkUserRole
        from app.dingtalk.events import notify_design_status_change
        from app.design.router import _find_role_dingtalk_ids, _translate_dict_fields, _fmt_schedule_date, _get_designer_name

        design_ids = _find_role_dingtalk_ids(db, "design_staff")

        for req in requests:
            # 查申请人钉钉ID
            applicant_dingtalk_id = ""
            if req.salesperson_id:
                applicant = db.query(ArkUser).filter(ArkUser.id == req.salesperson_id).first()
                if applicant and applicant.dingtalk_id:
                    applicant_dingtalk_id = applicant.dingtalk_id

            all_ids = list(set(([applicant_dingtalk_id] if applicant_dingtalk_id else []) + design_ids))
            if not all_ids:
                continue

            level_label, type_label, props_label = _translate_dict_fields(
                db, req.customer_level or "", req.shoot_type or "", req.props_requirement or "",
            )
            schedule_date = _fmt_schedule_date(
                req.expect_start_date, req.expect_end_date,
                req.expect_start_period, req.expect_end_period,
            )
            preferred_name = _get_designer_name(db, req.preferred_designer_id) or "随机分配"

            from app.dingtalk.work_notify import get_work_notifier
            from app.dingtalk.events import _build_request_markdown, _PRIORITY_LABELS

            md = _build_request_markdown(
                "⏰ 拍摄提醒：今日有预约待处理",
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
    finally:
        db.close()


