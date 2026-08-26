"""AI image generation/editing calls for OpenAI-compatible providers."""

import base64
import hashlib
import json
import logging
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from math import gcd
from typing import Optional, TypedDict

import httpx
from sqlalchemy.orm import Session

logger = logging.getLogger("commission.ai.image")

from app.ai.http_client import build_chat_url, build_headers, build_image_url
from app.ai.keyring import decrypt_key
from app.core.config import get_settings
from app.ai.log_snapshot import serialize_response_snapshot
from app.ai.models import AiCallLog, AiPreset
from app.ai.provider_service import get_provider


class ImageInput(TypedDict):
    filename: str
    content: bytes
    content_type: str


class ImageCallResult(TypedDict):
    content: str
    tokens_used: int | None
    usage_detail: dict
    duration_ms: int
    log_id: int
    provider_attempt_count: int
    request_id: str | None


@dataclass(frozen=True)
class ImageTransportResult:
    json: dict
    attempts: int
    request_id: str | None


@dataclass(frozen=True, slots=True)
class ImageProviderCallConfig:
    id: int
    name: str
    provider_type: str
    api_base: str
    api_key: str | None
    api_type: str
    extra_headers: dict | None
    timeout_sec: int


@dataclass(frozen=True, slots=True)
class ImagePresetCallConfig:
    id: int
    preset_name: str
    model: str
    parameters: dict


IMAGE_PARAMETER_KEYS = {
    "background",
    "input_fidelity",  # gpt-image edits：high 强力保留输入图脸部/细节（治合成脸变形，2026-07-16）
                       # 2026-07-20 起 wlai 中转站不再认 gpt-image-2+此参数（400），靠摘参重试兜底
    "moderation",
    "n",
    "output_compression",
    "output_format",
    "partial_images",
    "quality",
    "response_format",
    "size",
    "stream",
    "user",
}
GENERATION_PARAMETER_KEYS = IMAGE_PARAMETER_KEYS - {"input_fidelity", "stream", "partial_images"}
# ── 生图有两种 API 契约，按模型家族分（2026-07-27）──
# OpenAI 系（gpt-image-*/dall-e-*）走 /v1/images/edits：multipart 上传，size/quality 是请求参数。
# Google 系（gemini-*-image 等）不认这个端点——中转站会以 500 + code=local:convert_request_failed
# 拒绝，因为它压根无法把 multipart 转成 Gemini 的入参；这些模型走 /v1/chat/completions，
# 图片作为多模态 message content 传，产物是 content 里的 markdown data URL。
# 判据放 preset.parameters 的 api_style 而不是按模型名前缀硬编码：换模型是后台配置动作，
# 不该每次都改代码。该键不在下面任何白名单里，因此永远不会被当成请求参数发出去。
API_STYLE_KEY = "api_style"
API_STYLE_CHAT = "chat"
# chat 端点的可透传参数（size/quality 是 images/edits 专有，混进来会被上游拒收）
CHAT_IMAGE_PARAMETER_KEYS = {"max_tokens", "temperature", "top_p", "seed"}
# 三格模板（expo tryon 16:9 三场景拼接）实测单图 184~200s，180 会掐死正常请求；
# 调此值需联动 expo/service.py 的 STALE_GENERATING_SECS（看门狗必须大于本超时）
MIN_IMAGE_EDIT_TIMEOUT_SEC = 300

# 只重试**快速失败**的 502/503（网关立即拒绝，2026-07-16 生产实证 ~13% 失败多为 502，重试能救回）。
# **504 不重试**：它是「网关等上游超时」本质就慢，重试会叠加拖长；连同不重试的 ReadTimeout，都是
# 为了守住 expo 看门狗预算——单次超时 300s、看门狗 STALE_GENERATING_SECS(420s)，2 次慢速请求即越界，
# 迟到成功会被看门狗判死后覆写、但前端已 stopPolling 离场，造成 DB 有成品/前端已报错的错位。
_IMAGE_RETRY_STATUS = {502, 503}
_IMAGE_MAX_ATTEMPTS = 3          # 首次 + 2 次重试
_IMAGE_RETRY_BACKOFF_SEC = 1.5   # 线性退避 1.5s / 3s
# 连接/写入超时收紧到 15s（快速失败），只放长 read 给生图本身——否则 ConnectTimeout 也吃满 300s
_IMAGE_CONNECT_TIMEOUT_SEC = 15.0
_REQUEST_ID_HEADERS = ("x-request-id", "request-id", "openai-request-id")
_MAX_IMAGE_RESPONSE_BYTES = ((20 * 1024 * 1024 + 2) // 3) * 4 + 1024 * 1024


def _with_attempt_count(exc: Exception, attempts: int) -> Exception:
    setattr(exc, "provider_attempt_count", attempts)
    return exc


def _with_log_id(exc: Exception, log_id: int) -> Exception:
    setattr(exc, "log_id", log_id)
    return exc


def _reject_oversized_response(response) -> None:
    headers = getattr(response, "headers", {}) or {}
    raw_length = headers.get("content-length") or headers.get("Content-Length")
    if raw_length is None:
        return
    try:
        too_large = int(raw_length) > _MAX_IMAGE_RESPONSE_BYTES
    except (TypeError, ValueError):
        return
    if too_large:
        response.close()
        raise ValueError("provider image response is too large")


def _buffer_streamed_response(response: httpx.Response) -> httpx.Response:
    if not hasattr(response, "iter_bytes"):
        _reject_oversized_response(response)
        return response
    try:
        _reject_oversized_response(response)
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > _MAX_IMAGE_RESPONSE_BYTES:
                raise ValueError("provider image response is too large")
            chunks.append(chunk)
        # iter_bytes() already decompresses the wire body. Do not ask the new
        # Response to decode it again, or retain the compressed Content-Length.
        headers = response.headers.copy()
        headers.pop("content-encoding", None)
        headers.pop("content-length", None)
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=b"".join(chunks),
            request=response.request,
            extensions=dict(response.extensions),
        )
    finally:
        response.close()


def _build_request(client, method: str, url: str, **kwargs):
    return client.build_request(method, url, **kwargs)


def _send_streamed(client, request):
    return client.send(request, stream=True)


def _request_id(response) -> str | None:
    headers = getattr(response, "headers", {}) or {}
    for name in _REQUEST_ID_HEADERS:
        value = headers.get(name)
        if value:
            return str(value)
    return None


def _safe_response_body(response, limit: int = 300) -> str:
    try:
        payload = response.json()
    except Exception:
        return "[non-JSON response body omitted]"
    return serialize_response_snapshot(payload)[:limit]


def _enrich_status_error(exc: httpx.HTTPStatusError) -> httpx.HTTPStatusError:
    """httpx 的 raise_for_status 消息不含响应体，而中转站的真实失败原因全在体内
    error.message（2026-07-20 排障实证：光看 '400 Bad Request' 无从下手）——追加截断片段。"""
    body = _safe_response_body(exc.response)
    if not body:
        return exc
    return httpx.HTTPStatusError(
        f"{exc.args[0] if exc.args else exc} | 响应体: {body[:300]}",
        request=exc.request, response=exc.response,
    )


def _unsupported_param(exc: httpx.HTTPStatusError, data: dict) -> Optional[str]:
    """400 响应显式指认某参数不支持（error.param）且该参数确在本次请求里才返回参数名。
    model/prompt 是请求本体不算：摘了它们等于换了个请求。"""
    if exc.response.status_code != 400:
        return None
    try:
        err = (exc.response.json() or {}).get("error") or {}
    except Exception:
        return None
    param = err.get("param")
    if param and param in data and param not in ("model", "prompt"):
        return param
    return None


def _post_image_edits(
    url, headers, data, files, timeout_sec: int, caller_module: str,
    max_attempts: int | None = None,
    allow_parameter_fallback: bool = True,
) -> ImageTransportResult:
    """带摘参兜底的 edits 调用：上游 400 明确指认某可选参数不支持时（2026-07-20 中转站
    突然不认 gpt-image-2 + input_fidelity，preset 配置没变、上游能力漂移），摘掉该参数
    重发而不是硬失败——展位 kiosk 的可用性优先于单个参数带来的增强效果，摘参会大声记日志。
    每个参数只摘一次，防上游反复指认同一参数造成死循环。"""
    data = dict(data)  # 本地副本：摘参不改坏调用方字典
    stripped: set[str] = set()
    total_attempts = 0
    while True:
        try:
            transport = _post_image_edits_once(
                url, headers, data, files, timeout_sec, caller_module,
                max_attempts=max_attempts,
            )
            return ImageTransportResult(
                transport.json, total_attempts + transport.attempts, transport.request_id,
            )
        except httpx.HTTPStatusError as exc:
            total_attempts += getattr(exc, "provider_attempt_count", 1)
            bad = _unsupported_param(exc, data)
            if not allow_parameter_fallback or not bad or bad in stripped:
                raise _with_attempt_count(exc, total_attempts)
            stripped.add(bad)
            data.pop(bad, None)
            msg = (f"[{caller_module}] 上游拒收参数 {bad}（HTTP 400），已摘除重发。"
                   f"若长期如此请在 AI 后台把该参数从 preset 移除。响应体: "
                   f"{_safe_response_body(exc.response, 200)}")
            logger.warning(msg)
            print(msg, flush=True)


def _post_image_edits_once(
    url, headers, data, files, timeout_sec: int, caller_module: str,
    max_attempts: int | None = None,
) -> ImageTransportResult:
    """POST 到 /images/edits（multipart）。"""
    args = (
        lambda client: _build_request(
            client,
            "POST", url, headers=headers, data=data, files=files
        ),
        timeout_sec, caller_module, "image edit",
    )
    # 省略默认关键字，兼容历史测试/调用方对该内部发送函数的轻量 monkeypatch。
    if max_attempts is None:
        return _send_with_retry(*args)
    return _send_with_retry(*args, max_attempts=max_attempts)


def _post_chat_image(
    url, headers, payload, timeout_sec: int, caller_module: str,
    max_attempts: int | None = None,
) -> ImageTransportResult:
    """POST 到 /chat/completions（JSON 多模态）——Google 系生图模型的调用形态。

    没有 edits 那套摘参兜底：chat 入参白名单本就极窄（CHAT_IMAGE_PARAMETER_KEYS），
    不存在 size/quality 这类会被上游临时拒收的可选增强参数。"""
    args = (
        lambda client: _build_request(client, "POST", url, headers=headers, json=payload),
        timeout_sec, caller_module, "chat image",
    )
    if max_attempts is None:
        return _send_with_retry(*args)
    return _send_with_retry(*args, max_attempts=max_attempts)


def _send_with_retry(
    build_request, timeout_sec: int, caller_module: str, label: str,
    max_attempts: int | None = None,
) -> ImageTransportResult:
    """两条生图链路共用的发送+重试：对 502/503 与连接瞬断自动重试；504/ReadTimeout 不重试直接抛。

    build_request(client) -> httpx.Request；每次重试都会重建可发送请求。"""
    timeout = httpx.Timeout(timeout_sec, connect=_IMAGE_CONNECT_TIMEOUT_SEC, write=30.0)
    client_kwargs: dict = {
        "timeout": timeout,
    }
    # 生图专用代理（AI_IMAGE_PROXY，默认空=不传参，维持 httpx 既有行为）。
    # 配置时显式传参、只作用于生图两条链路——不用进程级 HTTP(S)_PROXY 正是为了
    # 别把文本 chat（elbnt 直连正常）一起拽进代理。
    proxy = (get_settings().AI_IMAGE_PROXY or "").strip()
    if proxy:
        client_kwargs["proxy"] = proxy
    attempt_limit = max(1, max_attempts or _IMAGE_MAX_ATTEMPTS)
    last_exc: Exception | None = None
    for attempt in range(1, attempt_limit + 1):
        try:
            with httpx.Client(**client_kwargs) as client:
                request = build_request(client)
                response = _buffer_streamed_response(_send_streamed(client, request))
            response.raise_for_status()
            return ImageTransportResult(response.json(), attempt, _request_id(response))
        except httpx.ReadTimeout as exc:
            error = TimeoutError(
                f"图片生成超时：上游 {timeout_sec} 秒内未返回。"
                "这通常是生图模型排队或代理池响应慢，请稍后重试或提高 Provider 超时时间。"
            )
            raise _with_attempt_count(error, attempt) from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _IMAGE_RETRY_STATUS:
                raise _with_attempt_count(_enrich_status_error(exc), attempt) from exc
            last_exc = exc
        except httpx.TransportError as exc:  # 连接/网络瞬断（ReadTimeout 已在上面拦掉）
            last_exc = exc
        except Exception as exc:
            # 隧道 sshd 按 permitopen 拒绝目标域名时不回 SOCKS 错误帧、直接断连，
            # socksio 报 ProtocolError("Malformed reply")——对现场是天书，翻译成可行动信息。
            # 按类名判而不 import socksio：不配代理的环境根本没装它。
            if client_kwargs.get("proxy") and type(exc).__name__ == "ProtocolError":
                error = RuntimeError(
                    "生图代理隧道拒绝了目标域名（SOCKS Malformed reply）——若刚更换生图 "
                    "provider 域名，需在隧道出口机 authorized_keys 加 permitopen 并重启 "
                    "wlai-tunnel，见 runbook「云端展会实例」节"
                )
                raise _with_attempt_count(error, attempt) from exc
            raise _with_attempt_count(exc, attempt)
        if attempt < attempt_limit:
            msg = (f"[{caller_module}] {label} transient error, retry {attempt}/"
                   f"{attempt_limit - 1}: {type(last_exc).__name__}: {last_exc}")
            logger.warning(msg)
            print(msg, flush=True)
            time.sleep(_IMAGE_RETRY_BACKOFF_SEC * attempt)
    if isinstance(last_exc, httpx.HTTPStatusError):
        raise _with_attempt_count(_enrich_status_error(last_exc), attempt_limit) from last_exc
    raise _with_attempt_count(last_exc, attempt_limit)


def _get_enabled_direct_preset(db: Session, preset_name: str) -> tuple[AiPreset, object]:
    preset = (
        db.query(AiPreset)
        .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
        .first()
    )
    if not preset:
        raise ValueError(f"Preset '{preset_name}' 不存在")
    if not preset.is_enabled:
        raise ValueError(f"Preset '{preset_name}' 已被禁用")

    provider = get_provider(db, preset.provider_id)
    if provider.provider_type != "direct":
        raise ValueError(f"Preset '{preset_name}' 绑定的不是直连 Provider，不能调用图片编辑接口")
    if not provider.is_enabled:
        raise ValueError(f"Provider '{provider.name}' 当前不可用")
    if (getattr(provider, "api_type", "openai") or "openai") != "openai":
        raise ValueError("图片编辑测试只支持 OpenAI-compatible Provider")
    return preset, provider


def build_image_config_version(preset, provider) -> str:
    call_config = {
        "provider": {
            "id": provider.id,
            "provider_type": provider.provider_type,
            "api_base": provider.api_base,
            "api_type": provider.api_type,
            "api_key": provider.api_key,
            "extra_headers": provider.extra_headers,
            "timeout_sec": provider.timeout_sec,
            "is_enabled": provider.is_enabled,
        },
        "preset": {
            "id": preset.id,
            "preset_name": preset.preset_name,
            "provider_id": preset.provider_id,
            "model": preset.model,
            "parameters": preset.parameters,
            "is_enabled": preset.is_enabled,
        },
    }
    canonical = json.dumps(
        call_config,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_config_version(preset, provider, expected: dict | None) -> None:
    if expected is None:
        return
    current = {
        "provider_id": provider.id,
        "fingerprint": build_image_config_version(preset, provider),
    }
    if current != expected:
        raise ValueError("design image provider configuration changed after queueing")


def _freeze_image_call_config(preset, provider):
    return (
        ImagePresetCallConfig(
            id=preset.id,
            preset_name=preset.preset_name,
            model=preset.model,
            parameters=deepcopy(preset.parameters or {}),
        ),
        ImageProviderCallConfig(
            id=provider.id,
            name=provider.name,
            provider_type=provider.provider_type,
            api_base=provider.api_base,
            api_key=provider.api_key,
            api_type=provider.api_type,
            extra_headers=deepcopy(provider.extra_headers),
            timeout_sec=provider.timeout_sec,
        ),
    )


def _warn_log_commit_failure(log_id: int, exc: Exception) -> None:
    message = f"AI image call log {log_id} error-state commit failed: {exc}"
    logger.warning(message)
    print(f"[ai-image] {message}", flush=True)


def _image_prompt_snapshot(prompt: str, images: list[ImageInput]) -> str:
    return json.dumps(
        {
            "prompt": prompt,
            "image_count": len(images),
            "images": [
                {
                    "filename": image["filename"],
                    "content_type": image["content_type"],
                    "size": len(image["content"]),
                }
                for image in images
            ],
        },
        ensure_ascii=False,
    )


def _apply_grok_aspect_ratio(params: dict) -> None:
    """Grok uses aspect_ratio; its images API silently ignores OpenAI size."""
    if params.get("model") != "grok-imagine-image-2.0" or not params.get("size"):
        return
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", str(params["size"]))
    if match is None:
        raise ValueError("Grok image size must be WIDTHxHEIGHT")
    width, height = map(int, match.groups())
    divisor = gcd(width, height)
    params["aspect_ratio"] = f"{width // divisor}:{height // divisor}"
    del params["size"]


def _image_params(
    preset: AiPreset, prompt: str, size: Optional[str] = None, quality: Optional[str] = None,
) -> dict:
    params = {
        "model": preset.model,
        "prompt": prompt,
    }
    for key, value in (preset.parameters or {}).items():
        if key in IMAGE_PARAMETER_KEYS:
            params[key] = value
    if size:  # 请求级尺寸覆盖 preset 配置（如 expo 竖版/横版按场景切换）
        params["size"] = size
    # 请求级档位覆盖 preset。注意：云雾中转站(api.wlai.vip)**不透传该参数**——2026-07-31
    # 同输入实测 high/medium/low 耗时(165~180s)、体积、output_tokens、目视画质全无差别，
    # expo 的客户端档位选择器已据此撤除。逻辑保留给将来真正支持该参数的通道。
    if quality:
        params["quality"] = quality
    _apply_grok_aspect_ratio(params)
    return params


def _generation_params(
    preset: AiPreset, prompt: str, size: Optional[str] = None, quality: Optional[str] = None,
) -> dict:
    params = {"model": preset.model, "prompt": prompt}
    for key, value in (preset.parameters or {}).items():
        if key in GENERATION_PARAMETER_KEYS:
            params[key] = value
    if size:
        params["size"] = size
    if quality:
        params["quality"] = quality
    _apply_grok_aspect_ratio(params)
    return params


def _uses_chat_style(preset: AiPreset) -> bool:
    return str((preset.parameters or {}).get(API_STYLE_KEY, "")).strip().lower() == API_STYLE_CHAT


def _chat_image_prompt(
    prompt: str,
    size: Optional[str] = None,
    quality: Optional[str] = None,
) -> str:
    """Encode image-only options in text for chat-compatible image models."""
    requirements: list[str] = []
    if size:
        requirements.append(f"目标画布尺寸为 {size.replace('x', '×')}，保持对应宽高比")
    quality_labels = {
        "low": "草稿质量",
        "medium": "标准成品质量",
        "high": "高精细成品质量",
    }
    if quality in quality_labels:
        requirements.append(quality_labels[quality])
    if not requirements:
        return prompt
    return f"{prompt}\n\n输出要求：{'；'.join(requirements)}。只返回最终图片。"


def _chat_image_payload(
    preset: AiPreset,
    prompt: str,
    images: list[ImageInput],
    size: Optional[str] = None,
    quality: Optional[str] = None,
) -> dict:
    """多模态 chat 入参：文本在前、图片按传入顺序在后——顺序即 prompt 里
    「The FIRST image is the customer's own photo」这类位置锚点的依据，不可打乱。"""
    content: list[dict] = [
        {"type": "text", "text": _chat_image_prompt(prompt, size, quality)}
    ]
    for image in images:
        encoded = base64.b64encode(image["content"]).decode()
        content.append({
            "type": "image_url",
            # 不传 detail：见 CLAUDE.md 硬约定，部分网关收到该字段会静默丢图
            "image_url": {"url": f"data:{image['content_type']};base64,{encoded}"},
        })
    payload = {"model": preset.model, "messages": [{"role": "user", "content": content}]}
    for key, value in (preset.parameters or {}).items():
        if key in CHAT_IMAGE_PARAMETER_KEYS:
            payload[key] = value
    return payload


def _extract_chat_image_content(result: dict) -> str:
    """Extract an exact data/HTTPS URL or bare base64 image from chat output."""
    choices = result.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    structured_parts: list[str] = []
    text_parts: list[str] = []
    if isinstance(content, list):  # 部分网关返回内容块数组，拼平后再交给正则
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("text"):
                text_parts.append(str(block["text"]))
            image_url = block.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if url:
                structured_parts.append(str(url))
    elif isinstance(content, str):
        text_parts.append(content)
    # OpenAI-compatible image chat gateways may return generated images beside
    # content instead of embedding them in Markdown.
    images = message.get("images") or []
    if isinstance(images, (str, dict)):
        images = [images]
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str):
                structured_parts.append(image)
                continue
            if not isinstance(image, dict):
                continue
            image_url = image.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            url = url or image.get("url")
            if url:
                structured_parts.append(str(url))
            elif image.get("b64_json"):
                structured_parts.append(f"data:image/png;base64,{image['b64_json']}")
    parts = [*structured_parts, *text_parts]
    if not parts:
        return ""
    content = " ".join(parts).strip()
    embedded = re.search(
        r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+|https://[^\s)]+",
        content,
        flags=re.IGNORECASE,
    )
    if embedded:
        return embedded.group(0)
    # Some compatible gateways return bare base64 instead of a data URL.
    return content if len(content) >= 128 and not any(char.isspace() for char in content) else ""


def _extract_image_content(result: dict, output_format: Optional[str] = None) -> str:
    image_format = (output_format or "png").lower()
    mime_format = "jpeg" if image_format in {"jpg", "jpeg"} else image_format
    data = result.get("data")
    if isinstance(data, list) and data:
        first = data[0] or {}
        if first.get("b64_json"):
            return f"data:image/{mime_format};base64,{first['b64_json']}"
        if first.get("url"):
            return first["url"]
    if isinstance(data, str):
        if data.startswith("data:image/") or data.startswith(("http://", "https://")):
            return data
        return f"data:image/{mime_format};base64,{data}"
    if result.get("b64_json"):
        return f"data:image/{mime_format};base64,{result['b64_json']}"
    if result.get("url"):
        return result["url"]
    return ""


def _extract_usage(result: dict) -> dict:
    usage = _usage_payload(result)
    if not usage:
        return {}
    return {
        "prompt_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
        "completion_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _extract_usage_detail(result: dict) -> dict:
    return dict(_usage_payload(result))


def _usage_payload(result: dict) -> dict:
    if "usage" in result:
        usage = result.get("usage")
        return usage if isinstance(usage, dict) else {}
    data = result.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        nested = data[0].get("usage")
        if isinstance(nested, dict):
            return nested
    return {}


def _effective_timeout_sec(provider) -> int:
    return max(provider.timeout_sec or 0, MIN_IMAGE_EDIT_TIMEOUT_SEC)


def generate_image(
    db: Session,
    preset_name: str,
    prompt: str,
    caller_module: str,
    caller_user_id: Optional[int] = None,
    size: Optional[str] = None,
    quality: Optional[str] = None,
    expected_config_version: Optional[dict] = None,
) -> ImageCallResult:
    """Call an OpenAI-compatible image generation endpoint."""
    preset, provider = _get_enabled_direct_preset(db, preset_name)
    _assert_config_version(preset, provider, expected_config_version)
    preset, provider = _freeze_image_call_config(preset, provider)
    log = AiCallLog(
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=_image_prompt_snapshot(prompt, []),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    start = time.time()
    transport: ImageTransportResult | None = None
    try:
        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        headers = build_headers(provider, api_key)
        timeout_sec = _effective_timeout_sec(provider)
        if _uses_chat_style(preset):
            url = build_chat_url(provider.api_base, provider.api_type or "openai")
            transport = _post_chat_image(
                url,
                headers,
                _chat_image_payload(preset, prompt, [], size, quality),
                timeout_sec,
                caller_module,
            )
        else:
            url = build_image_url(provider.api_base, "generations")
            transport = _send_with_retry(
                lambda client: _build_request(
                    client,
                    "POST", url, headers=headers,
                    json=_generation_params(preset, prompt, size, quality),
                ),
                timeout_sec, caller_module, "image generation",
            )
        result = transport.json
        content = (
            _extract_chat_image_content(result)
            if _uses_chat_style(preset)
            else _extract_image_content(
                result, (preset.parameters or {}).get("output_format")
            )
        )
        if not content:
            raise ValueError("图片接口响应中未找到 url 或 b64_json")

        usage = _extract_usage(result)
        usage_detail = _extract_usage_detail(result)
        duration_ms = int((time.time() - start) * 1000)
        log.status = "success"
        log.tokens_prompt = usage.get("prompt_tokens")
        log.tokens_completion = usage.get("completion_tokens")
        log.tokens_used = usage.get("total_tokens")
        log.usage_detail = usage_detail
        log.duration_ms = duration_ms
        log.response_snapshot = serialize_response_snapshot(result)
        db.commit()
        return {
            "content": content,
            "tokens_used": usage.get("total_tokens"),
            "usage_detail": usage_detail,
            "duration_ms": duration_ms,
            "log_id": log.id,
            "provider_attempt_count": transport.attempts,
            "request_id": transport.request_id,
        }
    except Exception as exc:
        _with_log_id(exc, log.id)
        if transport is not None and not hasattr(exc, "provider_attempt_count"):
            _with_attempt_count(exc, transport.attempts)
        db.rollback()
        try:
            log.status = "error"
            log.error_code = "unknown_error"
            log.error_message = str(exc)[:500]
            log.duration_ms = int((time.time() - start) * 1000)
            db.commit()
        except Exception as log_exc:
            db.rollback()
            _warn_log_commit_failure(log.id, log_exc)
        raise


def edit_image(
    db: Session,
    preset_name: str,
    prompt: str,
    images: list[ImageInput],
    caller_module: str,
    caller_user_id: Optional[int] = None,
    size: Optional[str] = None,
    quality: Optional[str] = None,
    expected_config_version: Optional[dict] = None,
    transport_max_attempts: int | None = None,
    transport_allow_parameter_fallback: bool = True,
) -> ImageCallResult:
    """Call an OpenAI-compatible image edit endpoint and return an image URL/data URL.

    Transport controls default to the shared image-service recovery policy.  A
    domain that owns a user-visible retry state machine may set attempts to ``1``
    and disable parameter fallback, so its displayed retry/error state matches the
    actual provider responses.
    """
    preset, provider = _get_enabled_direct_preset(db, preset_name)
    _assert_config_version(preset, provider, expected_config_version)
    preset, provider = _freeze_image_call_config(preset, provider)
    if not images:
        raise ValueError("图片编辑至少需要 1 张输入图片")

    log = AiCallLog(
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=_image_prompt_snapshot(prompt, images),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    start = time.time()
    transport: ImageTransportResult | None = None
    try:
        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        headers = build_headers(provider, api_key)
        timeout_sec = _effective_timeout_sec(provider)

        if _uses_chat_style(preset):
            # chat 端点没有 images API 的 size/quality 入参，统一编码进文本要求。
            url = build_chat_url(provider.api_base, provider.api_type or "openai")
            transport = _post_chat_image(
                url,
                headers,
                _chat_image_payload(preset, prompt, images, size, quality),
                timeout_sec,
                caller_module,
                max_attempts=transport_max_attempts,
            )
            result = transport.json
            content = _extract_chat_image_content(result)
        else:
            headers.pop("Content-Type", None)  # multipart 的 boundary 交给 httpx 生成

            files = [
                (
                    "image",
                    (image["filename"], image["content"], image["content_type"]),
                )
                for image in images
            ]
            url = build_image_url(provider.api_base, "edits")

            transport = _post_image_edits(
                url, headers, _image_params(preset, prompt, size, quality), files,
                timeout_sec,
                caller_module,
                max_attempts=transport_max_attempts,
                allow_parameter_fallback=transport_allow_parameter_fallback,
            )
            result = transport.json
            content = _extract_image_content(result, (preset.parameters or {}).get("output_format"))

        if not content:
            raise ValueError("图片接口响应中未找到 url 或 b64_json")

        usage = _extract_usage(result)
        usage_detail = _extract_usage_detail(result)
        duration_ms = int((time.time() - start) * 1000)
        log.status = "success"
        log.tokens_prompt = usage.get("prompt_tokens")
        log.tokens_completion = usage.get("completion_tokens")
        log.tokens_used = usage.get("total_tokens")
        log.usage_detail = usage_detail
        log.duration_ms = duration_ms
        log.response_snapshot = serialize_response_snapshot(result)
        db.commit()

        return {
            "content": content,
            "tokens_used": usage.get("total_tokens"),
            "usage_detail": usage_detail,
            "duration_ms": duration_ms,
            "log_id": log.id,
            "provider_attempt_count": transport.attempts,
            "request_id": transport.request_id,
        }
    except Exception as exc:
        _with_log_id(exc, log.id)
        if transport is not None and not hasattr(exc, "provider_attempt_count"):
            _with_attempt_count(exc, transport.attempts)
        db.rollback()
        try:
            log.status = "error"
            log.error_code = "unknown_error"
            log.error_message = str(exc)[:500]
            log.duration_ms = int((time.time() - start) * 1000)
            db.commit()
        except Exception as log_exc:
            db.rollback()
            _warn_log_commit_failure(log.id, log_exc)
        raise
