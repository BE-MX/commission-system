"""跟进模块定时任务入口（单活 scheduler 内运行，自建 session，红线 4）。

DB 同步操作放线程池；钉钉异步发送留在主事件循环（照 app/task/scheduler.py）。
"""
import asyncio
import logging

from app.core.database import SessionLocal
from app.core.time import beijing_today
from app.domestic_followup import digest_service, receipt_service

logger = logging.getLogger("commission")


def _prepare(kind: str) -> list[dict]:
    today = beijing_today()
    with SessionLocal() as db:
        if kind == "daily":
            digest_service.build_daily(db, today)
        pushes = digest_service.pending(db, kind, today)
        db.commit()
        return pushes


def _mark(ok_ids: list[int], failed_ids: list[int]) -> None:
    with SessionLocal() as db:
        digest_service.mark(db, ok_ids=ok_ids, failed_ids=failed_ids)
        db.commit()


async def _push(kind: str) -> None:
    try:
        pushes = await asyncio.to_thread(_prepare, kind)
        if not pushes:
            return
        ok_ids, failed = await digest_service.send(pushes)
        await asyncio.to_thread(_mark, ok_ids, failed)
        print(f"[domestic_followup] {kind} pushed {len(ok_ids)}/{len(pushes)}", flush=True)
    except Exception as exc:
        logger.warning("followup %s push job failed: %s", kind, type(exc).__name__)
        print(f"[domestic_followup] {kind} push job failed: {type(exc).__name__}: {exc}", flush=True)
        raise


async def send_daily_digest_job():
    await _push("daily")


async def send_urgent_job():
    await _push("urgent")


def _maintenance() -> dict:
    with SessionLocal() as db:
        result = {
            "receipt": receipt_service.scan(db, today=beijing_today()),
            "expired": receipt_service.expire_tasks(db, today=beijing_today()),
            "drafts": receipt_service.cleanup_drafts(db),
        }
        db.commit()
        return result


async def maintenance_job():
    try:
        result = await asyncio.to_thread(_maintenance)
        print(f"[domestic_followup] maintenance {result}", flush=True)
    except Exception as exc:
        logger.warning("followup maintenance failed: %s", type(exc).__name__)
        print(f"[domestic_followup] maintenance failed: {type(exc).__name__}: {exc}", flush=True)
        raise
