"""AI 通用接口必须走带证书校验的 httpx 请求链路。"""

import ssl
import urllib.request

import httpx
import pytest

from app.ai import call_service, http_client, provider_service
from app.ai import service as ai_service
from app.ai.models import AiCallLog, AiPreset, AiProvider
from app.expo import ai_pipeline
from app.training import draft_service


def _seed_direct_provider(db, *, preset_name: str = "general_tls_test"):
    provider = AiProvider(
        name=f"provider_{preset_name}",
        provider_type="direct",
        api_base="https://api.example.com/v1",
        api_key="encrypted-key",
        api_type="openai",
        is_enabled=True,
        timeout_sec=60,
    )
    db.add(provider)
    db.flush()
    preset = AiPreset(
        preset_name=preset_name,
        provider_id=provider.id,
        model="general-model",
        is_enabled=True,
    )
    db.add(preset)
    db.commit()
    return provider, preset


def _raise_certificate_error(*_args, **_kwargs):
    raise ssl.SSLCertVerificationError(1, "unable to get local issuer certificate")


def test_post_json_uses_verified_httpx_client(monkeypatch):
    assert hasattr(http_client, "post_json"), "通用 JSON 请求助手尚未实现"

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            captured["raised_for_status"] = True

        def json(self):
            return {"choices": []}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, **kwargs):
            captured["url"] = url
            captured["post_kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(http_client.httpx, "Client", FakeClient)

    result = http_client.post_json(
        "https://api.example.com/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        body={"model": "general-model"},
        timeout_sec=60,
    )

    assert result == {"choices": []}
    assert captured["client_kwargs"] == {
        "timeout": 60,
        "verify": True,
        "follow_redirects": False,
    }
    assert captured["post_kwargs"]["json"] == {"model": "general-model"}
    assert captured["raised_for_status"] is True


def test_provider_connection_test_uses_shared_verified_client(db, monkeypatch):
    provider, _preset = _seed_direct_provider(db, preset_name="provider_tls_test")
    captured = {}

    def fake_post_json(url, *, headers, body, timeout_sec):
        captured.update(url=url, headers=headers, body=body, timeout_sec=timeout_sec)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(provider_service, "post_json", fake_post_json)
    monkeypatch.setattr(provider_service, "decrypt_key", lambda _value: "secret")
    monkeypatch.setattr(urllib.request, "urlopen", _raise_certificate_error)

    result = provider_service.test_provider(db, provider.id)

    assert result["status"] == "ok"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["body"]["model"] == "general-model"
    assert captured["timeout_sec"] == 60


def test_synchronous_chat_uses_shared_verified_client(db, monkeypatch):
    _provider, preset = _seed_direct_provider(db)
    captured = {}

    def fake_post_json(url, *, headers, body, timeout_sec):
        captured.update(url=url, headers=headers, body=body, timeout_sec=timeout_sec)
        return {
            "choices": [{"message": {"content": "通用接口正常"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }

    monkeypatch.setattr(call_service, "post_json", fake_post_json)
    monkeypatch.setattr(call_service, "decrypt_key", lambda _value: "secret")
    monkeypatch.setattr(urllib.request, "urlopen", _raise_certificate_error)

    try:
        result = call_service.chat(
            db,
            preset_name=preset.preset_name,
            messages=[{"role": "user", "content": "hi"}],
            caller_module="test",
        )
    except ssl.SSLCertVerificationError:
        pytest.fail("同步通用 AI 调用仍在使用缺少受信任 CA 的 urllib 请求链路")

    assert result["content"] == "通用接口正常"
    assert result["tokens_used"] == 3
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["body"]["model"] == "general-model"
    assert captured["timeout_sec"] == 60
    assert db.query(AiCallLog).filter(AiCallLog.id == result["log_id"]).one().status == "success"


def test_post_json_does_not_follow_cross_origin_redirect(monkeypatch):
    real_client = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            307,
            headers={"location": "https://redirected.example.net/v1/chat/completions"},
            request=request,
        )

    def client_with_mock_transport(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(http_client.httpx, "Client", client_with_mock_transport)

    with pytest.raises(httpx.HTTPStatusError):
        http_client.post_json(
            "https://api.example.com/v1/chat/completions",
            headers={"x-api-key": "secret"},
            body={"model": "general-model", "messages": [{"role": "user", "content": "private"}]},
            timeout_sec=60,
        )

    assert len(requests) == 1
    assert requests[0].url.host == "api.example.com"


def test_provider_connection_test_handles_string_error_payload(db, monkeypatch):
    provider, _preset = _seed_direct_provider(db, preset_name="provider_error_shape")
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(401, request=request, json={"error": "unauthorized"})

    def reject_request(*_args, **_kwargs):
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(provider_service, "post_json", reject_request)
    monkeypatch.setattr(provider_service, "decrypt_key", lambda _value: "secret")

    result = provider_service.test_provider(db, provider.id)

    assert result["status"] == "error"
    assert "HTTP 401" in result["detail"]
    assert "unauthorized" in result["detail"]


@pytest.mark.parametrize(
    ("module", "caller_module"),
    [
        (ai_pipeline, "expo"),
        (draft_service, "training"),
    ],
)
def test_httpx_503_keeps_business_retry(module, caller_module, monkeypatch):
    attempts = []
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(503, request=request, text="temporarily unavailable")

    def fake_chat(**kwargs):
        attempts.append(kwargs["caller_module"])
        if len(attempts) < 3:
            raise httpx.HTTPStatusError(
                "upstream unavailable",
                request=request,
                response=response,
            )
        return {"content": "ok"}

    monkeypatch.setattr(ai_service, "chat", fake_chat)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    result = module._chat_with_transient_retry(None, "general-model", [])

    assert result == {"content": "ok"}
    assert attempts == [caller_module, caller_module, caller_module]
