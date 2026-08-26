"""钉钉 GMV 日报 APScheduler 入口。"""

import logging

from app.core.database import SessionLocal
from app.dingtalk.gmv_daily_service import send_daily_report


logger = logging.getLogger("commission.dingtalk.gmv_daily.scheduler")


async def send_gmv_daily_report_job() -> None:
    """08:00 首发；08:05/08:15/08:30 只重试未成功的同一快照。"""
    try:
        with SessionLocal() as db:
            result = await send_daily_report(db)
        logger.info("GMV daily report finished: %s", result.get("status"))
        if result.get("status") == "partial_failure":
            failed = [item for item in result.get("deliveries", []) if item.get("status") == "failed"]
            raise RuntimeError(f"GMV 日报有 {len(failed)} 个接收人发送失败")
    except Exception as exc:
        logger.exception("GMV daily report job failed")
        print(f"[GMV_DAILY] 定时任务失败: {exc}", flush=True)
        raise
