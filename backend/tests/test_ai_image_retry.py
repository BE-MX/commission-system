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
    def __init__(self, status, payload=None, body=None):
        self.status_code = status
        self._payload = payload or {"ok": True}
        self._body = body  # 4xx 响应体（dict → JSON），摘参重试/错误信息增强用

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "http://x")
            resp = (
                httpx.Response(self.status_code, request=req, json=self._body)
                if self._body is not None
                else httpx.Response(self.status_code, request=req)
            )
            raise httpx.HTTPStatusError("err", request=req, response=resp)

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


# ── 上游拒收参数的摘参兜底（2026-07-20 中转站突然不认 gpt-image-2 + input_fidelity） ──

_PARAM_400 = {"error": {"message": "The model does not support the 'input_fidelity' parameter.",
                        "param": "input_fidelity", "code": "invalid_input_fidelity_model"}}


def _patch_recording_sequence(monkeypatch, seq):
    """同 _patch_sequence，另记录每次 post 的 data，供断言参数确被摘除。"""
    it = iter(seq)
    posted = []

    class _RecClient(_FakeClient):
        def post(self, *a, **k):
            posted.append(dict(k.get("data") or {}))
            return super().post(*a, **k)

    monkeypatch.setattr(image_service.httpx, "Client", lambda timeout=None: _RecClient(next(it)))
    return posted


def test_400_unsupported_param_stripped_and_retried(monkeypatch):
    posted = _patch_recording_sequence(
        monkeypatch, [_FakeResp(400, body=_PARAM_400), _FakeResp(200, {"data": 1})])
    data = {"model": "m", "prompt": "p", "quality": "high", "input_fidelity": "high"}
    result = image_service._post_image_edits("http://x/edits", {}, data, [], 300, "expo")
    assert result == {"data": 1}
    assert "input_fidelity" in posted[0] and "input_fidelity" not in posted[1]
    assert data["input_fidelity"] == "high"  # 调用方字典不被就地改坏


def test_400_param_not_in_request_raises(monkeypatch):
    # 上游指认的参数本次根本没发 → 不是摘参能救的，立即抛
    body = {"error": {"param": "nonexistent", "code": "x"}}
    posted = _patch_recording_sequence(monkeypatch, [_FakeResp(400, body=body)])
    with pytest.raises(httpx.HTTPStatusError):
        image_service._post_image_edits("http://x/edits", {}, {"model": "m", "prompt": "p"}, [], 300, "expo")
    assert len(posted) == 1


def test_400_same_param_only_stripped_once(monkeypatch):
    # 摘掉后上游仍报同一参数 → 不无限循环，第二次即抛
    posted = _patch_recording_sequence(
        monkeypatch, [_FakeResp(400, body=_PARAM_400), _FakeResp(400, body=_PARAM_400)])
    with pytest.raises(httpx.HTTPStatusError):
        image_service._post_image_edits(
            "http://x/edits", {}, {"model": "m", "prompt": "p", "input_fidelity": "high"}, [], 300, "expo")
    assert len(posted) == 2


def test_400_model_prompt_never_stripped(monkeypatch):
    # model/prompt 是请求的本体，被指认也不许摘——摘了等于换了个请求
    body = {"error": {"param": "model", "code": "x"}}
    posted = _patch_recording_sequence(monkeypatch, [_FakeResp(400, body=body)])
    with pytest.raises(httpx.HTTPStatusError):
        image_service._post_image_edits("http://x/edits", {}, {"model": "m", "prompt": "p"}, [], 300, "expo")
    assert len(posted) == 1


def test_status_error_message_includes_body(monkeypatch):
    # raise_for_status 的消息不含响应体，排障全靠 error.message → 必须带上
    _patch_sequence(monkeypatch, [_FakeResp(400, body={"error": {"message": "余额不足", "param": ""}})])
    with pytest.raises(httpx.HTTPStatusError, match="余额不足"):
        _call()
