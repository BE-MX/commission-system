"""APScheduler 任务注册与生命周期管理"""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.database import SessionLocal

logger = logging.getLogger("commission")

# 任务 ID 常量,避免散落字符串
JOB_DESIGN_SHOOT_REMINDER = "design_shoot_reminder"
JOB_SHIPPING_DAILY_REPORT = "shipping_daily_report"
JOB_STAGING_SCAN = "staging_scan"
JOB_INSIGHT_INDUSTRY_DAILY = "insight_industry_daily"
JOB_INSIGHT_AI_TOOLS = "insight_ai_tools"
JOB_STOCK_DAILY_REPORT = "stock_daily_report"


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    """注册所有定时任务。新增任务时在此追加。"""
    from app.design.scheduler import check_today_shoot_reminders
    from app.tracking.daily_report_service import generate_daily_reports
    from app.tracking.staging_service import scan_staging
    from app.insight.scheduler import generate_industry_daily, generate_ai_tools
    from app.stock.scheduler import generate_stock_daily_report

    async def _scan_staging_job():
        with SessionLocal() as db:
            await scan_staging(db)

    scheduler.add_job(
        check_today_shoot_reminders,
        trigger="cron", hour=8, minute=30,
        id=JOB_DESIGN_SHOOT_REMINDER, replace_existing=True,
    )
    scheduler.add_job(
        generate_daily_reports,
        trigger="cron", hour=8, minute=30,
        id=JOB_SHIPPING_DAILY_REPORT, replace_existing=True,
    )
    scheduler.add_job(
        _scan_staging_job,
        trigger="interval", minutes=2,
        id=JOB_STAGING_SCAN, replace_existing=True,
    )
    scheduler.add_job(
        generate_industry_daily,
        trigger="cron", hour=8, minute=30,
        id=JOB_INSIGHT_INDUSTRY_DAILY, replace_existing=True,
    )
    scheduler.add_job(
        generate_ai_tools,
        trigger="cron", hour=8, minute=35,
        id=JOB_INSIGHT_AI_TOOLS, replace_existing=True,
    )
    scheduler.add_job(
        generate_stock_daily_report,
        trigger="cron", hour=8, minute=30,
        id=JOB_STOCK_DAILY_REPORT, replace_existing=True,
    )


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """启动 APScheduler。SCHEDULER_ENABLED=false 时返回 None。"""
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        logger.info("APScheduler disabled (SCHEDULER_ENABLED=false)")
        return None

    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    _register_jobs(scheduler)
    scheduler.start()

    job_ids = [job.id for job in scheduler.get_jobs()]
    logger.info(
        "APScheduler started (timezone=%s, %d jobs): %s",
        settings.SCHEDULER_TIMEZONE, len(job_ids), ", ".join(job_ids),
    )
    return scheduler


def shutdown_scheduler(scheduler: Optional[AsyncIOScheduler]) -> None:
    """关闭 APScheduler。None 时直接跳过。"""
    if scheduler is None:
        return
    scheduler.shutdown(wait=False)
    logger.info("APScheduler shutdown")
