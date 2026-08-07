"""Provider-neutral runtime for image generation jobs."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from app.ai import service as ai_service


MAX_DECODED_IMAGE_BYTES = 20 * 1024 * 1024
_SUPPORTED_MIME_MAGIC = {
    "image/png": lambda payload: payload.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda payload: payload.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda payload: (
        payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"
    ),
}


@dataclass(frozen=True, slots=True)
class ImageInput:
    filename: str
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class ImageJobRequest:
    preset_name: str
    prompt: str
    caller_module: str
    caller_user_id: int
    size: str | None
    quality: str | None
    input_images: tuple[ImageInput, ...]
    expected_config_version: dict | None
    download_hosts: frozenset[str]
    pricing_snapshot: dict | None


@dataclass(frozen=True, slots=True)
class ImagePayload:
    content: bytes
    declared_mime: str


@dataclass(frozen=True, slots=True)
class ImageJobResult:
    image: ImagePayload
    log_id: int | None
    provider_attempt_count: int
    billing_certainty: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost_microusd: int | None


@dataclass(frozen=True, slots=True)
class ImageJobFailure:
    code: str
    customer_message: str
    provider_attempt_count: int
    log_id: int | None
    refund_eligible: bool


def _mime_from_magic(payload: bytes) -> str | None:
    return next(
        (mime for mime, matches in _SUPPORTED_MIME_MAGIC.items() if matches(payload)),
        None,
    )


def _normalized_host(host: str) -> str:
    try:
        return host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("provider URL host is invalid") from None


def _validate_download_url(url: str, allowed_hosts: frozenset[str]) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port if parsed.port is not None else 443
    except ValueError:
        raise ValueError("provider URL is invalid") from None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("provider URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("provider URL must not contain credentials")
    if port != 443:
        raise ValueError("provider URL must use port 443")
    host = _normalized_host(parsed.hostname)
    normalized_allowed = {_normalized_host(item) for item in allowed_hosts if item}
    if host not in normalized_allowed:
        raise ValueError("provider URL host is not allowlisted")


def decode_image_payload(
    content: str,
    allowed_hosts: frozenset[str],
    *,
    download_image: Callable[[str, frozenset[str]], bytes] | None = None,
) -> ImagePayload:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned no image")
    content = content.strip()
    declared_mime = "image/png"
    if content.startswith("https://"):
        if not allowed_hosts:
            raise ValueError("provider download host is not configured")
        _validate_download_url(content, allowed_hosts)
        if download_image is None:
            raise ValueError("provider image downloader is not configured")
        payload = download_image(content, allowed_hosts)
        if len(payload) > MAX_DECODED_IMAGE_BYTES:
            raise ValueError("provider image is too large")
        declared_mime = _mime_from_magic(payload) or ""
        if not declared_mime:
            raise ValueError("provider URL did not return a supported image")
    else:
        encoded = content
        if content.startswith("data:"):
            header, separator, encoded = content.partition(",")
            if not separator or ";base64" not in header.lower():
                raise ValueError("provider image data URL is invalid")
            declared_mime = header[5:].split(";", 1)[0].lower()
            if declared_mime not in _SUPPORTED_MIME_MAGIC:
                raise ValueError("provider image type is unsupported")
        if len(encoded) > ((MAX_DECODED_IMAGE_BYTES + 2) // 3) * 4:
            raise ValueError("provider image is too large")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("provider image base64 is invalid") from None
        if len(payload) > MAX_DECODED_IMAGE_BYTES:
            raise ValueError("provider image is too large")
        actual_mime = _mime_from_magic(payload)
        if actual_mime is None:
            raise ValueError("provider image type is unsupported")
        if actual_mime != declared_mime:
            raise ValueError("provider image type does not match declared MIME")
    return ImagePayload(content=payload, declared_mime=declared_mime)


def _safe_nonnegative_bigint(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > 2**63 - 1:
        return None
    return value


def usage_values(result: dict) -> tuple[int | None, int | None, int | None]:
    raw_usage = result.get("usage_detail")
    usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
    return (
        _safe_nonnegative_bigint(usage.get("input_tokens", usage.get("prompt_tokens"))),
        _safe_nonnegative_bigint(usage.get("output_tokens", usage.get("completion_tokens"))),
        _safe_nonnegative_bigint(usage.get("total_tokens", result.get("tokens_used"))),
    )


def estimated_cost_microusd(pricing: dict | None, usage: dict) -> int | None:
    if not pricing:
        return None
    total = 0
    found = False
    limit = 2**63 - 1
    for direction in ("input", "output"):
        details = usage.get(f"{direction}_tokens_details")
        for kind in ("text", "image"):
            rate = pricing.get(f"{direction}_{kind}_microusd_per_token")
            if rate is None:
                continue
            found = True
            tokens = details.get(f"{kind}_tokens") if isinstance(details, dict) else None
            try:
                if isinstance(tokens, bool) or isinstance(rate, bool):
                    return None
                tokens_int = int(tokens)
                rate_int = int(rate)
                if tokens_int != tokens or rate_int != rate:
                    return None
            except (TypeError, ValueError, OverflowError):
                return None
            if tokens_int < 0 or rate_int < 0 or tokens_int > limit or rate_int > limit:
                return None
            amount = tokens_int * rate_int
            if amount > limit - total:
                return None
            total += amount
    return total if found else None


def call_image_provider(
    db,
    request: ImageJobRequest,
    *,
    download_image: Callable[[str, frozenset[str]], bytes] | None = None,
) -> ImageJobResult:
    kwargs = {
        "db": db,
        "preset_name": request.preset_name,
        "prompt": request.prompt,
        "caller_module": request.caller_module,
        "caller_user_id": request.caller_user_id,
        "size": request.size,
        "quality": request.quality,
    }
    if request.expected_config_version is not None:
        kwargs["expected_config_version"] = request.expected_config_version
    if request.input_images:
        raw_result = ai_service.edit_image(
            images=[
                {
                    "filename": item.filename,
                    "content": item.content,
                    "content_type": item.content_type,
                }
                for item in request.input_images
            ],
            **kwargs,
        )
    else:
        raw_result = ai_service.generate_image(**kwargs)
    try:
        image = decode_image_payload(
            raw_result.get("content", ""),
            request.download_hosts,
            download_image=download_image,
        )
    except Exception as exc:
        setattr(exc, "log_id", raw_result.get("log_id"))
        setattr(
            exc,
            "provider_attempt_count",
            max(0, int(raw_result.get("provider_attempt_count", 0) or 0)),
        )
        raise
    input_tokens, output_tokens, total_tokens = usage_values(raw_result)
    raw_usage = raw_result.get("usage_detail")
    usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}
    estimated_cost = estimated_cost_microusd(request.pricing_snapshot, usage)
    return ImageJobResult(
        image=image,
        log_id=raw_result.get("log_id"),
        provider_attempt_count=max(0, int(raw_result.get("provider_attempt_count", 0) or 0)),
        billing_certainty="estimated" if estimated_cost is not None else "unknown",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_microusd=estimated_cost,
    )


def classify_image_error(exc: Exception) -> ImageJobFailure:
    detail = str(exc).lower()
    code = "unknown_error"
    message = "生成失败，请稍后重试；若持续失败请联系管理员"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            code, message = "rate_limited", "服务请求过多，请稍后手动重试"
        elif status in {502, 503}:
            code, message = "provider_unavailable", "图片服务暂不可用，请稍后重试"
        elif status == 504:
            code, message = "provider_timeout", "图片服务响应超时，请稍后重试"
        elif status in {400, 422} and any(
            word in detail for word in ("moderation", "safety", "content_policy")
        ):
            code, message = "moderation_blocked", "内容未通过安全检查，请修改描述后重试"
        elif status in {400, 422}:
            code, message = "validation_error", "图片参数无效，请调整后重试"
    elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        code, message = "provider_timeout", "图片服务响应超时，请稍后重试"
    elif isinstance(exc, ValueError):
        code, message = "validation_error", "图片或参数无效，请调整后重试"
    attempts = max(0, int(getattr(exc, "provider_attempt_count", 0) or 0))
    explicitly_not_billed = getattr(exc, "billing_certainty", None) == "not_billed"
    refund_eligible = explicitly_not_billed or (
        code == "validation_error" and not isinstance(exc, httpx.HTTPStatusError) and attempts == 0
    )
    return ImageJobFailure(
        code=code,
        customer_message=message,
        provider_attempt_count=attempts,
        log_id=getattr(exc, "log_id", None),
        refund_eligible=refund_eligible,
    )
