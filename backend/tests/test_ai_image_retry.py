"""生图接口瞬时错误重试（2026-07-16 展会 kiosk 合成偶发失败治理）。

只重试 502/503/504 与连接瞬断（快速失败）；4xx 与 ReadTimeout(单次已 300s)不重试。
"""

import httpx
import pytest

from app.ai import image_service


class _CountingStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.yielded = 0

    def __iter__(self):
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk


def test_response_cap_stops_reading_chunked_body_early(monkeypatch):
    chunk = b"x" * (image_service._MAX_IMAGE_RESPONSE_BYTES // 2 + 1)
    stream = _CountingStream([chunk, chunk, chunk])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream, request=request)
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        image_service.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )

    with pytest.raises(ValueError, match="too large"):
        image_service._post_chat_image("https://example.test/chat", {}, {}, 30, "test")
    assert stream.yielded == 2


def test_response_cap_accepts_legal_chunked_body_without_content_length(monkeypatch):
    stream = _CountingStream([b'{"ok":', b"true}"])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream, request=request)
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        image_service.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )

    result = image_service._post_chat_image(
        "https://example.test/chat", {}, {}, 30, "test"
    )
    assert result.json == {"ok": True}
    assert stream.yielded == 2


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

    def build_request(self, method, url, **kwargs):
        return method, url, kwargs

    def send(self, request, stream=False):
        assert stream is True
        method, url, kwargs = request
        return self.post(url, **kwargs)


class _FakeResp:
    def __init__(self, status, payload=None, body=None, headers=None):
        self.status_code = status
        self._payload = payload or {"ok": True}
        self._body = body  # 4xx 响应体（dict → JSON），摘参重试/错误信息增强用
        self.headers = headers or {}

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


@pytest.fixture(autouse=True)
def _no_image_proxy(monkeypatch):
    # 隔离真实 .env：在配了 AI_IMAGE_PROXY 的机器（展会云机）上跑测试，
    # 假 Client 收不到意外的 proxy 参数（审查 2026-07-31）
    monkeypatch.setattr(image_service, "get_settings", lambda: _FakeSettings(""))


def _patch_sequence(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr(image_service.httpx, "Client", lambda timeout=None, **kwargs: _FakeClient(next(it)))


def _call():
    return image_service._post_image_edits("http://x/edits", {}, {}, [], 300, "expo")


def test_retries_502_then_succeeds(monkeypatch):
    _patch_sequence(monkeypatch, [_FakeResp(502), _FakeResp(502), _FakeResp(200, {"data": 1})])
    result = _call()
    assert result.json == {"data": 1}
    assert result.attempts == 3


def test_retries_503_then_succeeds(monkeypatch):
    _patch_sequence(monkeypatch, [_FakeResp(503), _FakeResp(200, {"data": 1})])
    result = _call()
    assert result.json == {"data": 1}
    assert result.attempts == 2


def test_4xx_not_retried(monkeypatch):
    calls = {"n": 0}
    def make(timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeClient(_FakeResp(400))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        _call()
    assert calls["n"] == 1  # 4xx 立即抛，不重试
    assert caught.value.provider_attempt_count == 1


def test_all_502_raises_after_max_attempts(monkeypatch):
    _patch_sequence(monkeypatch, [_FakeResp(502), _FakeResp(502), _FakeResp(502)])
    with pytest.raises(httpx.HTTPStatusError) as caught:
        _call()
    assert caught.value.provider_attempt_count == 3


def test_caller_can_disable_inner_retries(monkeypatch):
    """Expo owns a user-visible retry counter, so one facade call must equal one attempt."""
    calls = {"n": 0}

    def make(timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeClient(_FakeResp(502))

    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        image_service._post_image_edits(
            "http://x/edits", {}, {}, [], 300, "expo", max_attempts=1,
        )
    assert calls["n"] == 1
    assert caught.value.provider_attempt_count == 1


def test_caller_can_disable_unsupported_parameter_fallback(monkeypatch):
    calls = {"n": 0}

    def make(timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeClient(_FakeResp(400, {"error": {"param": "quality"}}))

    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError):
        image_service._post_image_edits(
            "http://x/edits",
            {},
            {"quality": "high"},
            [],
            300,
            "expo",
            max_attempts=1,
            allow_parameter_fallback=False,
        )
    assert calls["n"] == 1


def test_504_not_retried(monkeypatch):
    # 504=网关等上游超时(慢)，重试会顶穿看门狗预算 → 立即抛不重试
    calls = {"n": 0}
    def make(timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeClient(_FakeResp(504))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        _call()
    assert calls["n"] == 1
    assert caught.value.provider_attempt_count == 1


def test_429_not_retried_and_reports_attempt_count(monkeypatch):
    calls = {"n": 0}
    def make(timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeClient(_FakeResp(429))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        _call()
    assert calls["n"] == 1
    assert caught.value.provider_attempt_count == 1


def test_read_timeout_not_retried(monkeypatch):
    calls = {"n": 0}
    def make(timeout=None, **kwargs):
        calls["n"] += 1
        return _FakeClient(httpx.ReadTimeout("timeout"))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    with pytest.raises(TimeoutError) as caught:  # ReadTimeout → 转 TimeoutError，且不重试
        _call()
    assert calls["n"] == 1
    assert caught.value.provider_attempt_count == 1


def test_transport_error_retried_then_succeeds(monkeypatch):
    _patch_sequence(monkeypatch, [httpx.ConnectError("boom"), _FakeResp(200, {"ok": 1})])
    result = _call()
    assert result.json == {"ok": 1}
    assert result.attempts == 2


def test_request_id_header_precedence(monkeypatch):
    _patch_sequence(monkeypatch, [_FakeResp(200, {"ok": 1}, headers={
        "openai-request-id": "openai", "request-id": "fallback", "x-request-id": "primary",
    })])
    assert _call().request_id == "primary"


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

    monkeypatch.setattr(image_service.httpx, "Client", lambda timeout=None, **kwargs: _RecClient(next(it)))
    return posted


def test_400_unsupported_param_stripped_and_retried(monkeypatch):
    posted = _patch_recording_sequence(
        monkeypatch, [_FakeResp(400, body=_PARAM_400), _FakeResp(200, {"data": 1})])
    data = {"model": "m", "prompt": "p", "quality": "high", "input_fidelity": "high"}
    result = image_service._post_image_edits("http://x/edits", {}, data, [], 300, "expo")
    assert result.json == {"data": 1}
    assert result.attempts == 2
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
    with pytest.raises(httpx.HTTPStatusError) as caught:
        image_service._post_image_edits(
            "http://x/edits", {}, {"model": "m", "prompt": "p", "input_fidelity": "high"}, [], 300, "expo")
    assert len(posted) == 2
    assert caught.value.provider_attempt_count == 2


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


def test_status_error_message_redacts_sensitive_response_values(monkeypatch):
    raw_b64 = "QUJD" * 200
    body = {
        "error": {"message": "bad request", "param": ""},
        "Authorization": "Bearer leaked",
        "token": "secret-token",
        "b64_json": "raw-private-image",
        "url": "https://cdn.test/a.png?sig=secret",
        "data": raw_b64,
        "nested": [{"payload": raw_b64}],
    }
    _patch_sequence(monkeypatch, [_FakeResp(400, body=body)])
    with pytest.raises(httpx.HTTPStatusError) as caught:
        _call()
    message = str(caught.value)
    assert "bad request" in message
    assert "https://cdn.test/a.png" in message
    for secret in ("Bearer leaked", "secret-token", "raw-private-image", "sig=secret", raw_b64):
        assert secret not in message


def test_safe_response_body_redacts_embedded_data_url_and_signed_url():
    raw_b64 = "QUJD" * 200
    response = _FakeResp(400, payload={
        "message": (
            f"keep-before ![image](data:image/png;base64,{raw_b64}) keep-after "
            "https://user:pass@cdn.test/a.png?signature=secret#fragment"
        ),
    })
    safe = image_service._safe_response_body(response, 2000)
    assert raw_b64 not in safe
    assert "signature=secret" not in safe
    assert "user:pass" not in safe
    assert "keep-before" in safe and "keep-after" in safe
    assert "https://cdn.test/a.png" in safe


# ── 生图专用代理（2026-07-31 北京展会实例 api.wlai.vip 被 SNI 阻断，借道隧道） ──

class _FakeSettings:
    def __init__(self, proxy=""):
        self.AI_IMAGE_PROXY = proxy


def test_proxy_setting_passed_to_client(monkeypatch):
    seen = {}
    def make(timeout=None, proxy=None, **kwargs):
        seen["proxy"] = proxy
        return _FakeClient(_FakeResp(200, {"ok": 1}))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    monkeypatch.setattr(image_service, "get_settings", lambda: _FakeSettings("socks5://127.0.0.1:1081"))
    assert _call().json == {"ok": 1}
    assert seen["proxy"] == "socks5://127.0.0.1:1081"


def test_no_proxy_kwarg_when_unset(monkeypatch):
    # 未配置时不往 Client 传 proxy 参数——办公室生产直连行为零变化
    seen = {}
    def make(**kwargs):
        seen.update(kwargs)
        return _FakeClient(_FakeResp(200, {"ok": 1}))
    monkeypatch.setattr(image_service.httpx, "Client", make)
    monkeypatch.setattr(image_service, "get_settings", lambda: _FakeSettings(""))
    assert _call().json == {"ok": 1}
    assert "proxy" not in seen


def test_proxy_protocol_error_translated(monkeypatch):
    # 隧道 permitopen 拒目标域名 → socksio ProtocolError → 翻译成可行动的 RuntimeError
    class ProtocolError(Exception):
        pass
    monkeypatch.setattr(image_service.httpx, "Client",
                        lambda timeout=None, proxy=None, **kwargs: _FakeClient(ProtocolError("Malformed reply")))
    monkeypatch.setattr(image_service, "get_settings", lambda: _FakeSettings("socks5://127.0.0.1:1081"))
    with pytest.raises(RuntimeError, match="permitopen"):
        _call()
