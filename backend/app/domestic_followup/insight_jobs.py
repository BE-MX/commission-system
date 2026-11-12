"""洞见生成独立线程池，不能挤占录入 AI/OCR 的 3 个线程。"""
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

logger = logging.getLogger("commission")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="followup-insight")
_pending = set()
_pending_lock = Lock()


def _run(fn, args: tuple) -> None:
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 — 线程池异常必须落日志
        name = getattr(fn, "__name__", repr(fn))
        logger.warning("followup insight job %s failed: %s", name, type(exc).__name__)
        print(f"[domestic_followup] insight job {name} failed: {type(exc).__name__}", flush=True)


def submit(fn, *args) -> Future:
    return _executor.submit(_run, fn, args)


def submit_snapshots(ids):
    from app.domestic_followup import insight_generation
    for identifier in ids:
        with _pending_lock:
            if identifier in _pending:
                continue
            _pending.add(identifier)
        try:
            future = submit(insight_generation.run_snapshots, [identifier])
            if future is not None:
                future.add_done_callback(lambda _future, key=identifier: _forget(key))
            else:
                _forget(identifier)
        except Exception:
            _forget(identifier)
            raise


def _forget(identifier):
    with _pending_lock:
        _pending.discard(identifier)
