"""生图接口瞬时错误重试（2026-07-16 展会 kiosk 合成偶发失败治理）。

只重试 502/503/504 与连接瞬断（快速失败）；4xx 与 ReadTimeout(单次已 300s)不重试。
"""

import httpx
import pytest

from app.ai import image_service


class _FakeClient:
    """一次 with 块=一个 attempt：post 返回预置响应或抛预置异常。"""

    def __init__(self, item):
        self._item = item

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, *a, **k):
        if isinstance(self._item, Exception):
            raise self._item
        return self._item


class _FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "http://x")
            raise httpx.HTTPStatusError(
                "err", request=req, response=httpx.Response(self.status_code, request=req)
            )

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(image_service.time, "sleep", lambda s: None)


def _patch_sequence(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr(image_service.httpx, "Client", lambda timeout=None: _FakeClient(next(it)))


def _call():
    return image_service._post_image_edits("http://x/edits", {}, {}, [], 300, "expo")


def test_retries_502_then_succeeds(monkeypatch):
    _patch_sequence(monkeypatch, [_FakeResp(502), _FakeResp(502), _FakeResp(200, {"data": 1})])
    assert _call() == {"data": 1}  # 前两次 502，第三次成功


def test_4xx_not_retried(monkeypatch):
    calls = {"n": 0}
    def make(timeout=None):
        calls["n"] += 1
        return _FakeClient(_FakeResp(400))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError):
        _call()
    assert calls["n"] == 1  # 4xx 立即抛，不重试


def test_all_502_raises_after_max_attempts(monkeypatch):
    _patch_sequence(monkeypatch, [_FakeResp(502), _FakeResp(502), _FakeResp(502)])
    with pytest.raises(httpx.HTTPStatusError):
        _call()


def test_504_not_retried(monkeypatch):
    # 504=网关等上游超时(慢)，重试会顶穿看门狗预算 → 立即抛不重试
    calls = {"n": 0}
    def make(timeout=None):
        calls["n"] += 1
        return _FakeClient(_FakeResp(504))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError):
        _call()
    assert calls["n"] == 1


def test_read_timeout_not_retried(monkeypatch):
    calls = {"n": 0}
    def make(timeout=None):
        calls["n"] += 1
        return _FakeClient(httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(TimeoutError):  # ReadTimeout → 转 TimeoutError，且不重试
        _call()
    assert calls["n"] == 1


def test_transport_error_retried_then_succeeds(monkeypatch):
    _patch_sequence(monkeypatch, [httpx.ConnectError("boom"), _FakeResp(200, {"ok": 1})])
    assert _call() == {"ok": 1}  # 连接瞬断重试后成功
