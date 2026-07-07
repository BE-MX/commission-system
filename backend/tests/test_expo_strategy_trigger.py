"""话术触发互斥（_start_strategy_once）：前置触发与兜底触发并发时同会话只跑一次。"""

import threading
import time

from app.expo import ai_pipeline


def _wait_until(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_start_strategy_once_dedupes_while_running(monkeypatch):
    calls = []
    release = threading.Event()

    def fake_run(session_id):
        calls.append(session_id)
        release.wait(timeout=5)

    monkeypatch.setattr(ai_pipeline, "_run_strategy", fake_run)
    try:
        ai_pipeline._start_strategy_once(9101)
        assert _wait_until(lambda: len(calls) == 1)

        # 生成进行中重复触发（兜底路径）被拒
        ai_pipeline._start_strategy_once(9101)
        time.sleep(0.1)
        assert calls == [9101]

        # 其他会话不受互斥影响
        ai_pipeline._start_strategy_once(9102)
        assert _wait_until(lambda: len(calls) == 2)
    finally:
        release.set()
    assert _wait_until(lambda: not ai_pipeline._strategy_inflight)

    # 完成后同会话允许再次触发（如兜底补跑）
    ai_pipeline._start_strategy_once(9101)
    assert _wait_until(lambda: len(calls) == 3)


def test_start_strategy_once_cleans_up_after_exception(monkeypatch):
    def boom(session_id):
        raise RuntimeError("ai down")

    monkeypatch.setattr(ai_pipeline, "_run_strategy", boom)
    ai_pipeline._start_strategy_once(9201)
    # finally 分支必须把 inflight 清干净，否则该会话的触发点从此哑火
    assert _wait_until(lambda: 9201 not in ai_pipeline._strategy_inflight)
