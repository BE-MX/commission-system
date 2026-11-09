"""Validated provider transport configuration shared by every AI adapter."""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


MASKED_HEADER_VALUE = "__KEEP_EXISTING_SECRET__"


def sensitive_header(key, auth_header=None):
    return key.lower() == (auth_header or "").lower() or any(word in key.lower() for word in ("authorization", "api-key", "apikey", "token", "secret", "cookie"))


def public_extra_headers(value, auth_header=None):
    return {key: MASKED_HEADER_VALUE if sensitive_header(key, auth_header) and item not in ("", "{api_key}") else item
            for key, item in (value or {}).items()}


class TransportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    timeout_sec: float | None = Field(None, ge=1, le=3600)
    multimodal_timeout_sec: float | None = Field(None, ge=1, le=3600)
    image_timeout_sec: float | None = Field(None, ge=1, le=3600)
    connect_timeout_sec: float | None = Field(None, ge=1, le=120)
    write_timeout_sec: float | None = Field(None, ge=1, le=3600)
    image_max_attempts: int | None = Field(None, ge=1, le=3, strict=True)
    image_retry_backoff_sec: float | None = Field(None, ge=0, le=10)
    image_retry_statuses: list[int] | None = None
    image_parameter_fallback: bool | None = None

    @field_validator("image_retry_statuses")
    @classmethod
    def safe_retry_statuses(cls, value):
        if value is not None and (len(set(value)) != len(value) or set(value) - {429, 502, 503}):
            raise ValueError("重试状态码仅支持 429、502、503；超时请求可能已计费，不自动重试")
        return value


class ProviderOptions(TransportOptions):
    chat_path: str | None = None
    image_generation_path: str | None = None
    image_edit_path: str | None = None
    auth_header: str | None = None
    auth_scheme: str | None = None
    anthropic_version: str | None = None
    image_proxy: str | None = None
    test_model: str | None = Field(None, max_length=128)
    test_message: str | None = Field(None, max_length=1000)
    test_max_tokens: int | None = Field(None, ge=1, le=256, strict=True)
    token_parameter: str | None = None

    @field_validator("chat_path", "image_generation_path", "image_edit_path")
    @classmethod
    def relative_path(cls, value):
        if value is None or value == "":
            return None
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", value) or ".." in value or value.startswith("//"):
            raise ValueError("端点须为当前 API Base 下的相对路径，不含域名、查询参数或 ..")
        return value.lstrip("/")

    @field_validator("auth_header", "auth_scheme", "anthropic_version")
    @classmethod
    def header_token(cls, value):
        if value and not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
            raise ValueError("认证头、认证前缀和协议版本只能包含字母、数字、点、下划线和连字符")
        return value

    @field_validator("token_parameter")
    @classmethod
    def token_key(cls, value):
        if value not in (None, "max_tokens", "max_completion_tokens"):
            raise ValueError("Token 参数须为 max_tokens 或 max_completion_tokens")
        return value

    @field_validator("image_proxy")
    @classmethod
    def proxy_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
                raise ValueError("代理须为 HTTP(S)/SOCKS5 地址，不得包含凭据")
        return value


def validate_provider_options(value):
    return ProviderOptions.model_validate({} if value is None else value).model_dump(exclude_none=True)


def validate_transport_options(value):
    return TransportOptions.model_validate({} if value is None else value).model_dump(exclude_none=True)


def provider_options(provider) -> dict:
    return validate_provider_options(getattr(provider, "runtime_config", None))


def transport_options(provider, preset=None) -> dict:
    result = provider_options(provider)
    if preset is not None:
        result.update(validate_transport_options((preset.parameters or {}).get("transport")))
    return result


def request_timeout(provider, kind="text", preset=None, deadline=None):
    options = transport_options(provider, preset)
    base = options.get("timeout_sec", provider.timeout_sec or 60)
    if kind == "image":
        value = options.get("image_timeout_sec", max(base, 300))
    elif kind == "multimodal":
        value = options.get("multimodal_timeout_sec", max(base, 120))
    else:
        value = base
    if deadline is not None:
        if deadline <= 0:
            raise ValueError("timeout_sec must be positive")
        value = min(value, deadline)
    return value


def validate_extra_headers(value, auth_header=None):
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("附加请求头必须是 JSON 对象")
    for key, item in value.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or not isinstance(item, str) or "\r" in item or "\n" in item:
            raise ValueError("请求头名称或值格式不正确")
        if sensitive_header(key, auth_header) and item not in ("", "{api_key}", MASKED_HEADER_VALUE):
            raise ValueError("认证凭据请填入加密 API Key；附加请求头使用 {api_key} 占位符")


def image_request_timeout(provider, preset, caller_module):
    """A network timeout cannot outlive the owning task's lease/watchdog."""
    from app.core.config import get_settings
    settings = get_settings()
    budgets = {
        "design_image": min(settings.DESIGN_IMAGE_LEASE_SECONDS, settings.DESIGN_IMAGE_STALE_SECONDS) - 60,
        "customer_image": min(settings.CUSTOMER_IMAGE_LEASE_SECONDS, settings.CUSTOMER_IMAGE_STALE_SECONDS) - 60,
        "expo": 300,
        "expo_beautify": 300,
    }
    return request_timeout(provider, "image", preset, deadline=max(1, budgets[caller_module]) if caller_module in budgets else None)
