import base64
from dataclasses import FrozenInstanceError

import httpx
import pytest

from app.ai import image_job_runtime as runtime
from app.ai.image_job_runtime import ImageInput, ImageJobRequest


PNG = b"\x89PNG\r\n\x1a\ncontent"
JPEG = b"\xff\xd8\xffcontent"
WEBP = b"RIFF\x04\x00\x00\x00WEBPcontent"


def _request(**values):
    defaults = {
        "preset_name": "design_image_generation",
        "prompt": "keep logo exact",
        "caller_module": "customer_image",
        "caller_user_id": 7,
        "size": "1024x1024",
        "quality": "medium",
        "input_images": (),
        "expected_config_version": None,
        "download_hosts": frozenset(),
        "pricing_snapshot": None,
    }
    return ImageJobRequest(**(defaults | values))


def _result(content, **values):
    return {
        "content": content,
        "log_id": 11,
        "provider_attempt_count": 2,
        "usage_detail": {
            "input_tokens": 5,
            "output_tokens": 7,
            "total_tokens": 12,
            "output_tokens_details": {"image_tokens": 7},
        },
        **values,
    }


def test_image_job_request_is_immutable():
    request = _request()
    with pytest.raises(FrozenInstanceError):
        request.prompt = "changed"


def test_call_image_provider_routes_edit_when_inputs_exist(monkeypatch):
    request = _request(
        input_images=(ImageInput("logo.png", b"png", "image/png"),)
    )
    calls = []
    monkeypatch.setattr(
        runtime.ai_service,
        "edit_image",
        lambda **kwargs: calls.append(kwargs) or _result(base64.b64encode(PNG).decode()),
    )

    result = runtime.call_image_provider(object(), request)

    assert result.image.declared_mime == "image/png"
    assert result.image.content == PNG
    assert calls[0]["images"] == [
        {"filename": "logo.png", "content": b"png", "content_type": "image/png"}
    ]


def test_call_image_provider_routes_generate_without_inputs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        runtime.ai_service,
        "generate_image",
        lambda **kwargs: calls.append(kwargs) or _result(base64.b64encode(PNG).decode()),
    )

    runtime.call_image_provider(object(), _request(expected_config_version={"v": 3}))

    assert calls[0]["expected_config_version"] == {"v": 3}
    assert "images" not in calls[0]


@pytest.mark.parametrize(
    ("mime", "content"),
    [("image/png", PNG), ("image/jpeg", JPEG), ("image/webp", WEBP)],
)
def test_decode_image_payload_supports_declared_image_formats(mime, content):
    encoded = base64.b64encode(content).decode()
    image = runtime.decode_image_payload(f"data:{mime};base64,{encoded}", frozenset())
    assert image.content == content
    assert image.declared_mime == mime


def test_decode_image_payload_rejects_magic_mismatch():
    encoded = base64.b64encode(PNG).decode()
    with pytest.raises(ValueError, match="does not match"):
        runtime.decode_image_payload(f"data:image/jpeg;base64,{encoded}", frozenset())


def test_decode_image_payload_url_requires_allowlisted_host(monkeypatch):
    with pytest.raises(ValueError, match="not configured"):
        runtime.decode_image_payload("https://cdn.example.test/image", frozenset())

    image = runtime.decode_image_payload(
        "https://cdn.example.test/image",
        frozenset({"cdn.example.test"}),
        download_image=lambda url, hosts: PNG,
    )
    assert image == runtime.ImagePayload(PNG, "image/png")

    with pytest.raises(ValueError, match="not allowlisted"):
        runtime.decode_image_payload(
            "https://other.example.test/image",
            frozenset({"cdn.example.test"}),
            download_image=lambda url, hosts: PNG,
        )


def test_usage_and_cost_are_parsed_with_overflow_protection(monkeypatch):
    monkeypatch.setattr(
        runtime.ai_service,
        "generate_image",
        lambda **kwargs: _result(base64.b64encode(PNG).decode()),
    )
    result = runtime.call_image_provider(
        object(),
        _request(pricing_snapshot={"output_image_microusd_per_token": 31}),
    )
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (5, 7, 12)
    assert result.estimated_cost_microusd == 217
    assert result.billing_certainty == "estimated"

    assert runtime.estimated_cost_microusd(
        {"output_image_microusd_per_token": 2**63 - 1},
        {"output_tokens_details": {"image_tokens": 2}},
    ) is None


def test_decode_failure_preserves_provider_audit_fields(monkeypatch):
    monkeypatch.setattr(
        runtime.ai_service,
        "generate_image",
        lambda **kwargs: _result("invalid-base64", log_id=19, provider_attempt_count=3),
    )

    with pytest.raises(ValueError) as error:
        runtime.call_image_provider(object(), _request())

    assert error.value.log_id == 19
    assert error.value.provider_attempt_count == 3


def _http_error(status, body):
    response = httpx.Response(
        status, text=body, request=httpx.Request("POST", "https://provider")
    )
    return httpx.HTTPStatusError(body, request=response.request, response=response)


def test_classify_image_error_marks_moderation_as_not_refundable():
    exc = _http_error(400, "content_policy")
    setattr(exc, "provider_attempt_count", 1)
    setattr(exc, "log_id", 42)
    failure = runtime.classify_image_error(exc)
    assert failure.code == "moderation_blocked"
    assert failure.refund_eligible is False
    assert failure.provider_attempt_count == 1
    assert failure.log_id == 42


def test_classify_image_error_refunds_only_proven_before_send_failure():
    exc = ValueError("bad request")
    setattr(exc, "provider_attempt_count", 0)
    assert runtime.classify_image_error(exc).refund_eligible is True

    uncertain = TimeoutError("slow")
    assert runtime.classify_image_error(uncertain).refund_eligible is False
