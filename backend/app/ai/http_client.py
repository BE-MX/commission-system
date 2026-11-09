"""AI HTTP 调用层公共助手

集中 chat/completions URL 拼接与请求头构造,供 Provider 测试 / Preset 测试 / chat 复用。
支持 OpenAI (Chat Completions) 和 Anthropic (Messages) 两种 API 协议。
"""

import asyncio
import re

import httpx

from app.ai.preset_config import text_request_parameters
from app.ai.models import AiProvider
from app.ai.provider_config import provider_options

# data URL: data:<media_type>;base64,<data>
_DATA_URL_RE = re.compile(r"^data:(?P<media>[^;,]+)(?P<b64>;base64)?,(?P<data>.*)$", re.DOTALL)


def _openai_block_to_anthropic(block):
    """OpenAI 的 image_url 内容块 → Anthropic 的 image/source 块；非图片块原样返回。

    调用方（expo 面容分析等）统一按 OpenAI 多模态格式 {"type":"image_url",...} 组装，
    发到 anthropic 类 Provider 时若不转换，网关会静默丢图 → 模型「未收到照片」
    （2026-07-08 线上 session=28/29/30 实case）。
    """
    if not isinstance(block, dict) or block.get("type") != "image_url":
        return block
    image_url = block.get("image_url")
    url = image_url.get("url") if isinstance(image_url, dict) else image_url
    if not isinstance(url, str):
        return block
    if url.startswith("data:"):
        m = _DATA_URL_RE.match(url)
        if not m or not m.group("b64"):
            return block  # 非 base64 data URL 不猜，保持原样
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": m.group("media") or "image/jpeg",
                "data": m.group("data"),
            },
        }
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return block


def _to_anthropic_content(content):
    """消息 content 从 OpenAI 多模态格式转 Anthropic 格式；字符串或非图片块保持不变。"""
    if not isinstance(content, list):
        return content
    return [_openai_block_to_anthropic(b) for b in content]


def build_chat_url(api_base: str, api_type: str = "openai", *, provider=None) -> str:
    """根据 api_base 和 api_type 构造完整的 API URL。

    api_type="anthropic" 时拼 /messages; api_type="openai" 时拼 /chat/completions。
    如果 api_base 已包含完整端点路径,直接使用。
    """
    if provider is not None and provider_options(provider).get("chat_path"):
        return api_base.rstrip("/") + "/" + provider_options(provider)["chat_path"]
    base = api_base.rstrip("/")
    # 已包含完整端点路径,直接使用
    endpoint_suffixes = ("/messages", "/chat/completions", "/completions")
    if any(base.endswith(s) for s in endpoint_suffixes):
        return base
    # 以版本号或 /api 结尾
    if any(base.endswith(v) for v in ("/v1", "/v2", "/v3", "/v4", "/api")):
        suffix = "/messages" if api_type == "anthropic" else "/chat/completions"
        return f"{base}{suffix}"
    # 默认补全
    suffix = "/v1/messages" if api_type == "anthropic" else "/v1/chat/completions"
    return f"{base}{suffix}"


def build_image_url(api_base: str, endpoint: str = "edits", *, provider=None) -> str:
    """Build an OpenAI-compatible image endpoint URL."""
    key = "image_edit_path" if endpoint == "edits" else "image_generation_path"
    if provider is not None and provider_options(provider).get(key):
        return api_base.rstrip("/") + "/" + provider_options(provider)[key]
    base = api_base.rstrip("/")
    image_suffixes = ("/images/generations", "/images/edits", "/images/variations")
    if any(base.endswith(s) for s in image_suffixes):
        return base.rsplit("/", 1)[0] + "/" + endpoint.strip("/")
    clean_endpoint = endpoint.strip("/")
    if any(base.endswith(v) for v in ("/v1", "/v2", "/v3", "/v4", "/api")):
        return f"{base}/images/{clean_endpoint}"
    return f"{base}/v1/images/{clean_endpoint}"


def build_headers(provider: AiProvider, api_key: str | None) -> dict:
    """构造请求头。支持通过 extra_headers 自定义认证方式 (如 api-key)。

    Anthropic 协议使用 x-api-key 头; OpenAI 使用 Bearer Authorization。
    extra_headers 中填 {"api-key": ""} 表示使用 api_key 字段的值作为 api-key。
    """
    options = provider_options(provider)
    headers = httpx.Headers({"Content-Type": "application/json", "User-Agent": "LeShine-Ark-AI/1.0"})
    if provider.api_type == "anthropic":
        headers["anthropic-version"] = options.get("anthropic_version", "2023-06-01")
    for key, value in (provider.extra_headers or {}).items():
        if value == "{api_key}" or (value == "" and key.lower() in {"api-key", "x-api-key"}):
            value = api_key or ""
        headers[key] = value
    auth_header = options.get("auth_header")
    if api_key and auth_header:
        scheme = options.get("auth_scheme", "")
        headers[auth_header] = f"{scheme} {api_key}".strip()
    elif api_key and not any(key in headers for key in ("authorization", "api-key", "x-api-key")):
        if provider.api_type == "anthropic":
            headers["x-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    return headers


def apply_token_parameter(body, provider):
    if provider.api_type == "anthropic":
        return body
    key = provider_options(provider).get("token_parameter")
    if key:
        other = "max_completion_tokens" if key == "max_tokens" else "max_tokens"
        if other in body:
            value = body.pop(other)
            body.setdefault(key, value)
    return body


def transport_http_timeout(read_timeout, options=None):
    options = options or {}
    if not {"connect_timeout_sec", "write_timeout_sec"}.intersection(options):
        return read_timeout
    return httpx.Timeout(read_timeout, connect=min(read_timeout, options.get("connect_timeout_sec", read_timeout)),
                         write=min(read_timeout, options.get("write_timeout_sec", read_timeout)))


def post_json(
    url: str,
    *,
    headers: dict,
    body: dict,
    timeout_sec: int | float,
    enforce_total_timeout: bool = False,
    transport: dict | None = None,
) -> dict:
    """通过 httpx 的受信任 CA 链发送通用 AI JSON 请求。"""
    if enforce_total_timeout:
        # The reply route is synchronous (FastAPI worker thread). Cancellation
        # propagates into the async socket operation and closes the client, unlike
        # timing out a Future while its paid HTTP request keeps running unchecked.
        return asyncio.run(_post_json_with_deadline(url, headers, body, timeout_sec, transport))
    with httpx.Client(
        timeout=transport_http_timeout(timeout_sec, transport),
        verify=True,
        follow_redirects=False,
    ) as client:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


async def _post_json_with_deadline(url, headers, body, timeout_sec, transport=None):
    async with asyncio.timeout(timeout_sec):
        async with httpx.AsyncClient(timeout=transport_http_timeout(timeout_sec, transport), verify=True, follow_redirects=False) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()


def build_anthropic_body(
    model: str,
    messages: list,
    system_prompt: str | None = None,
    parameters: dict | None = None,
) -> dict:
    """构造 Anthropic Messages API 请求体。

    与 OpenAI 格式的主要区别:
    - system 是顶层参数,不在 messages 里
    - 必须有 max_tokens
    """
    # 分离 system message 和 user/assistant messages；user/assistant 的多模态 content
    # 从 OpenAI image_url 格式转成 Anthropic image/source 格式（否则图被网关静默丢弃）
    user_messages = [
        {**m, "content": _to_anthropic_content(m.get("content"))}
        for m in messages
        if m.get("role") != "system"
    ]

    parameters = text_request_parameters(parameters)
    body = {
        "model": model,
        "messages": user_messages,
        "max_tokens": (parameters or {}).get("max_tokens", 4096),
    }
    systems = [system_prompt] if system_prompt else []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "system" and content and content not in systems:
            systems.append(content)
    if systems:
        body["system"] = "\n\n".join(systems)

    # 传递其他参数 (temperature 等),但排除 OpenAI 特有的
    skip_keys = {"max_tokens", "max_completion_tokens", "stream"}
    if parameters:
        for k, v in parameters.items():
            if k not in skip_keys and k not in body:
                body[k] = v

    return body


def extract_anthropic_content(result: dict) -> str:
    """从 Anthropic Messages API 响应中提取文本内容。

    响应格式: {"content": [{"type": "text", "text": "..."}], "usage": {"input_tokens": N, "output_tokens": N}}
    """
    content_blocks = result.get("content", [])
    if isinstance(content_blocks, str):
        return content_blocks
    if isinstance(content_blocks, list):
        texts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        return "".join(texts)
    return ""


def extract_anthropic_usage(result: dict) -> dict:
    """从 Anthropic 响应中提取 token 用量,映射为 OpenAI 兼容字段。"""
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    input_tokens = input_tokens if type(input_tokens) is int and input_tokens >= 0 else None
    output_tokens = output_tokens if type(output_tokens) is int and output_tokens >= 0 else None
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None,
    }
