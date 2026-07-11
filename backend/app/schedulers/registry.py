"""APScheduler 任务注册与生命周期管理"""

import asyncio
import logging
from typing import Optional

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
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
JOB_INSIGHT_INTELLIGENCE = "insight_intelligence_overview"
JOB_STOCK_DAILY_REPORT = "stock_daily_report"
JOB_TRACKING_POLL_ACTIVE = "tracking_poll_active"
JOB_COLOR_SOCIAL_EXTRACT = "color_social_extract"
JOB_COLOR_SALES_AGGREGATE = "color_sales_aggregate"
JOB_WHATSAPP_AUTO_SYNC = "whatsapp_auto_sync"
JOB_AFTERSALES_NOTIFICATION_RETRY = "aftersales_notification_retry"


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    """注册所有定时任务。新增任务时在此追加。"""
    from app.design.scheduler import check_today_shoot_reminders
    from app.tracking.daily_report_service import generate_daily_reports
    from app.tracking.polling_service import poll_active_shipments
    from app.tracking.staging_service import scan_staging
    from app.insight.scheduler import generate_industry_daily, generate_ai_tools, generate_intelligence_overview
    from app.stock.scheduler import generate_stock_daily_report
    from app.color.social_extract_service import extract_social_colors, aggregate_sales_by_color
    from app.whatsapp.scheduler import sync_whatsapp_accounts_job
    from app.aftersales.notification_service import process_due_notifications
    from app.aftersales.ai_service import recover_stale_analyses

    settings = get_settings()

    async def _scan_staging_job():
        with SessionLocal() as db:
            await scan_staging(db)

    async def _poll_active_job():
        with SessionLocal() as db:
            await poll_active_shipments(db)

    async def _aftersales_notification_retry_job():
        with SessionLocal() as db:
            recover_stale_analyses(db)
            db.commit()
            await process_due_notifications(db)

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
        _poll_active_job,
        trigger="interval", hours=3,
        id=JOB_TRACKING_POLL_ACTIVE, replace_existing=True,
    )
    scheduler.add_job(
        _aftersales_notification_retry_job,
        trigger="interval", minutes=1,
        id=JOB_AFTERSALES_NOTIFICATION_RETRY, replace_existing=True,
        max_instances=1, coalesce=True,
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
        generate_intelligence_overview,
        trigger="cron", hour=8, minute=40,
        id=JOB_INSIGHT_INTELLIGENCE, replace_existing=True,
    )
    scheduler.add_job(
        generate_stock_daily_report,
        trigger="cron", hour=8, minute=30,
        id=JOB_STOCK_DAILY_REPORT, replace_existing=True,
    )

    # ── 色彩趋势 ──────────────────────────────────────────
    # 注意：这两个管线是纯同步（HTTP + OpenCV），注册为同步函数让
    # AsyncIOScheduler 放线程池执行，不许写成 async def（会阻塞事件循环，B-1/S3）
    def _color_social_extract_job():
        with SessionLocal() as db:
            extract_social_colors(db)

    def _color_sales_aggregate_job():
        with SessionLocal() as db:
            aggregate_sales_by_color(db)

    scheduler.add_job(
        _color_social_extract_job,
        trigger="cron", hour=8, minute=0,
        id=JOB_COLOR_SOCIAL_EXTRACT, replace_existing=True,
    )
    scheduler.add_job(
        _color_sales_aggregate_job,
        trigger="cron", day_of_week="mon", hour=6, minute=0,
        id=JOB_COLOR_SALES_AGGREGATE, replace_existing=True,
    )
    if settings.WHATSAPP_AUTO_SYNC_ENABLED:
        scheduler.add_job(
            sync_whatsapp_accounts_job,
            trigger="interval", minutes=settings.WHATSAPP_AUTO_SYNC_INTERVAL_MINUTES,
            id=JOB_WHATSAPP_AUTO_SYNC, replace_existing=True,
            max_instances=1,
            coalesce=True,
        )


def _make_job_event_listener(loop: asyncio.AbstractEventLoop):
    """job 失败/错过执行 → 日志 + service.log + 钉钉群告警（B-1）。

    listener 可能在执行器线程回调，钉钉发送（async）用 run_coroutine_threadsafe
    排回主事件循环——直接调用只会得到一个从未 await 的 coroutine（静默失败）。
    """

    def _on_job_event(event):
        if getattr(event, "exception", None):
            detail = getattr(event, "traceback", "") or ""
            msg = f"⚠️ 定时任务失败: {event.job_id}\n{event.exception}"
            logger.error("%s\n%s", msg, detail)
            print(f"{msg}\n{detail}", flush=True)  # NSSM service.log 只认 print
        else:
            msg = f"⚠️ 定时任务错过执行(missed): {event.job_id}"
            logger.error(msg)
            print(msg, flush=True)
        try:
            from app.dingtalk.webhook import get_webhook_sender

            coro = get_webhook_sender().send_markdown("定时任务告警", msg)
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            logger.exception("job alert dingtalk notify failed")
            print("job alert dingtalk notify failed", flush=True)

    return _on_job_event


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """启动 APScheduler。SCHEDULER_ENABLED=false 时返回 None。"""
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        logger.info("APScheduler disabled (SCHEDULER_ENABLED=false)")
        return None

    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    _register_jobs(scheduler)
    scheduler.add_listener(
        _make_job_event_listener(asyncio.get_event_loop()),
        EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
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
