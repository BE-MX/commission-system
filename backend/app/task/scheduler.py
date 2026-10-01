"""任务中心定时任务入口（单活 scheduler 内运行，自建 session）。

AI 与数据库是同步阻塞调用，放到线程池；只有钉钉异步发送留在主事件循环（registry.py 禁止 async job 里做同步 IO）。
"""
import asyncio
import logging
from datetime import date

from app.core.database import SessionLocal
from app.core.time import beijing_today
from app.task import brief_service

logger = logging.getLogger("commission")


def _prepare(today: date) -> list[dict]:
    with SessionLocal() as db:
        return brief_service.prepare_pushes(db, today, commit=db.commit)


def _mark(brief_ids: list[int]) -> None:
    with SessionLocal() as db:
        brief_service.mark_pushed(db, brief_ids)
        db.commit()


async def send_task_briefs_job():
    try:
        pushes = await asyncio.to_thread(_prepare, beijing_today())
        ok_ids = await brief_service.send_pushes(pushes)
        await asyncio.to_thread(_mark, ok_ids)
        print(f"[task] daily briefs pushed: {len(ok_ids)}/{len(pushes)}", flush=True)
    except Exception as exc:
        logger.warning("task brief job failed: %s", type(exc).__name__)
        print(f"[task] brief job failed: {type(exc).__name__}: {exc}", flush=True)
        raise
