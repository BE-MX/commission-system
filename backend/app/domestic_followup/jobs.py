"""跟进后台 AI/OCR 的有界线程池。

一次 AI 整理最长要等 120 秒，BackgroundTasks 会占用 Starlette 共享线程池；
业务员集中提交时大量长任务会挤掉其他请求的同步端点。这里单独开 3 个线程排队，
超出的任务等前面的跑完再跑（草稿保持 running，前端轮询或「我的草稿」继续）。
"""
import logging
from concurrent.futures import Future, ThreadPoolExecutor

logger = logging.getLogger("commission")

MAX_WORKERS = 3
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="followup-ai")


def _run(fn, args: tuple) -> None:
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 — 线程池里的异常没人 result()，不记就彻底无声
        name = getattr(fn, "__name__", repr(fn))
        logger.warning("followup background job %s failed: %s: %s", name, type(exc).__name__, str(exc)[:200])
        print(f"[domestic_followup] background job {name} failed: {type(exc).__name__}: {str(exc)[:200]}",
              flush=True)


def submit(fn, *args) -> Future:
    """排一个后台任务；调用方不等待结果。"""
    return _executor.submit(_run, fn, args)
