"""APScheduler 任务注册与生命周期管理"""

import asyncio
import logging
import socket
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
    JobSubmissionEvent,
)
from apscheduler.executors.base import MaxInstancesReachedError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.database import SessionLocal

logger = logging.getLogger("commission")

_active_scheduler: Optional[AsyncIOScheduler] = None
_job_runtime: dict[str, dict] = {}
_job_runtime_lock = threading.Lock()

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
JOB_FESTIVAL_EVENT_MONITOR = "festival_event_monitor"
JOB_FESTIVAL_DAILY_REPORT = "festival_daily_report"
JOB_DESIGN_IMAGE_QUEUE = "design_image_queue"
JOB_CUSTOMER_IMAGE_QUEUE = "customer_image_queue"
JOB_CUSTOMER_IMAGE_CLEANUP = "customer_image_cleanup"
JOB_SALES_PUBLIC_POOL_DAILY = "sales_public_pool_daily"


def _console_safe(value: object, encoding: str | None = None) -> str:
    """把服务日志文本转换为当前控制台可编码形式，避免告警监听器二次失败。"""
    target_encoding = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    text = str(value)
    try:
        return text.encode(target_encoding, errors="backslashreplace").decode(target_encoding)
    except LookupError:
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


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
    from app.festival.notification_service import (
        monitor_festival_and_recover_daily,
        send_daily_report_if_due,
    )
    from app.design_image.worker import process_design_image_queue
    from app.customer_image.worker import (
        process_customer_image_cleanup,
        process_customer_image_queue,
    )
    from app.sales_automation.scheduler import generate_public_pool_daily_batch

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
        monitor_festival_and_recover_daily,
        trigger="interval", minutes=1,
        id=JOB_FESTIVAL_EVENT_MONITOR, replace_existing=True,
        max_instances=1, coalesce=True, misfire_grace_time=60,
    )
    scheduler.add_job(
        send_daily_report_if_due,
        trigger="cron", hour=17, minute=30,
        id=JOB_FESTIVAL_DAILY_REPORT, replace_existing=True,
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        process_design_image_queue,
        trigger="interval",
        seconds=settings.DESIGN_IMAGE_WORKER_INTERVAL_SECONDS,
        id=JOB_DESIGN_IMAGE_QUEUE,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_customer_image_queue,
        trigger="interval",
        seconds=settings.DESIGN_IMAGE_WORKER_INTERVAL_SECONDS,
        id=JOB_CUSTOMER_IMAGE_QUEUE,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_customer_image_cleanup,
        trigger="cron",
        hour=3,
        minute=30,
        id=JOB_CUSTOMER_IMAGE_CLEANUP,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
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
    if settings.SALES_PUBLIC_POOL_AUTO_BATCH_ENABLED:
        scheduler.add_job(
            generate_public_pool_daily_batch,
            trigger="cron",
            hour=settings.SALES_PUBLIC_POOL_BATCH_HOUR,
            minute=settings.SALES_PUBLIC_POOL_BATCH_MINUTE,
            id=JOB_SALES_PUBLIC_POOL_DAILY,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )


def _make_job_event_listener(loop: asyncio.AbstractEventLoop):
    """job 失败/错过执行 → 日志 + service.log + 钉钉群告警（B-1）。

    listener 可能在执行器线程回调，钉钉发送（async）用 run_coroutine_threadsafe
    排回主事件循环——直接调用只会得到一个从未 await 的 coroutine（静默失败）。
    """

    def _on_job_event(event):
        if getattr(event, "exception", None):
            detail = getattr(event, "traceback", "") or ""
            msg = f"定时任务失败: {event.job_id}\n{event.exception}"
            logger.error("%s\n%s", msg, detail)
            print(_console_safe(f"{msg}\n{detail}"), flush=True)  # NSSM service.log 只认 print
        else:
            msg = f"定时任务错过执行(missed): {event.job_id}"
            logger.error(msg)
            print(_console_safe(msg), flush=True)
        try:
            from app.dingtalk.webhook import get_webhook_sender

            coro = get_webhook_sender().send_markdown("定时任务告警", msg)
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            logger.exception("job alert dingtalk notify failed")
            print("job alert dingtalk notify failed", flush=True)

    return _on_job_event


def _record_job_event(event) -> None:
    """Record non-sensitive in-memory runtime facts for the operations center."""
    job_id = getattr(event, "job_id", None)
    if not job_id:
        return

    now = datetime.now(timezone.utc).isoformat()
    with _job_runtime_lock:
        state = _job_runtime.setdefault(job_id, {"running_instances": 0})
        if event.code == EVENT_JOB_SUBMITTED:
            submitted_count = max(1, len(getattr(event, "scheduled_run_times", []) or []))
            state["last_started_at"] = now
            state["last_status"] = "running"
            state["running_instances"] = int(state.get("running_instances") or 0) + submitted_count
            return

        if event.code in (EVENT_JOB_EXECUTED, EVENT_JOB_ERROR):
            state["running_instances"] = max(0, int(state.get("running_instances") or 0) - 1)
            state["last_finished_at"] = now
            state["last_status"] = "failed" if event.code == EVENT_JOB_ERROR else "success"
            exception = getattr(event, "exception", None)
            state["last_error"] = (
                f"任务执行失败（{type(exception).__name__}）" if exception else None
            )
            return

        if event.code == EVENT_JOB_MISSED:
            # Executor emits one MISSED event for each scheduled run time submitted.
            state["running_instances"] = max(0, int(state.get("running_instances") or 0) - 1)
            state["last_finished_at"] = now
            state["last_status"] = "missed"
            state["last_error"] = "任务错过计划执行时间"
            return

        if event.code == EVENT_JOB_MAX_INSTANCES:
            state["last_finished_at"] = now
            state["last_status"] = "skipped"
            state["last_error"] = "达到任务最大并发数，未提交执行"


def get_active_scheduler() -> Optional[AsyncIOScheduler]:
    """Return the scheduler owned by this process, if it is enabled and running."""
    return _active_scheduler


def get_job_runtime_snapshot() -> dict[str, dict]:
    """Return a copy so API serialization never races with scheduler callbacks."""
    with _job_runtime_lock:
        return {job_id: dict(state) for job_id, state in _job_runtime.items()}


def submit_job_now(scheduler: AsyncIOScheduler, job_id: str) -> None:
    """Submit one execution without changing the recurring trigger's next fire time."""
    job = scheduler.get_job(job_id)
    if job is None:
        raise ValueError("任务不存在")
    run_time = datetime.now(scheduler.timezone)
    jobstore_alias = getattr(job, "_jobstore_alias", "default")
    executor = scheduler._lookup_executor(job.executor)
    try:
        executor.submit_job(job, [run_time])
    except MaxInstancesReachedError as exc:
        scheduler._dispatch_event(JobSubmissionEvent(
            EVENT_JOB_MAX_INSTANCES, job.id, jobstore_alias, [run_time],
        ))
        raise ValueError("任务已达到最大并发数，本次没有提交执行") from exc
    scheduler._dispatch_event(JobSubmissionEvent(
        EVENT_JOB_SUBMITTED, job.id, jobstore_alias, [run_time],
    ))


def _apply_persisted_job_policies(scheduler: AsyncIOScheduler) -> None:
    """Reapply pause policies after process restarts; failure must not stop startup."""
    try:
        from app.operations.db_models import SchedulerJobPolicy

        with SessionLocal() as db:
            paused_ids = {
                row.job_id
                for row in db.query(SchedulerJobPolicy).filter(
                    SchedulerJobPolicy.instance_id == socket.gethostname(),
                    SchedulerJobPolicy.paused == 1,
                ).all()
            }
        for job_id in paused_ids:
            if scheduler.get_job(job_id):
                scheduler.pause_job(job_id)
    except Exception as exc:
        logger.warning("scheduler policies unavailable (%s)", type(exc).__name__)
        print(f"scheduler policies unavailable ({type(exc).__name__})", flush=True)


def start_scheduler() -> Optional[AsyncIOScheduler]:
    """启动 APScheduler。SCHEDULER_ENABLED=false 时返回 None。"""
    settings = get_settings()
    if not settings.SCHEDULER_ENABLED:
        logger.info("APScheduler disabled (SCHEDULER_ENABLED=false)")
        return None

    global _active_scheduler, _job_runtime
    with _job_runtime_lock:
        _job_runtime = {}
    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    _register_jobs(scheduler)
    _apply_persisted_job_policies(scheduler)
    scheduler.add_listener(
        _make_job_event_listener(asyncio.get_event_loop()),
        EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    scheduler.add_listener(
        _record_job_event,
        EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED
        | EVENT_JOB_MAX_INSTANCES,
    )
    scheduler.start()
    _active_scheduler = scheduler

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
    global _active_scheduler
    scheduler.shutdown(wait=False)
    if _active_scheduler is scheduler:
        _active_scheduler = None
    logger.info("APScheduler shutdown")
