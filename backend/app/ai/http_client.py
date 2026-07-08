"""AI HTTP 调用层公共助手

集中 chat/completions URL 拼接与请求头构造,供 Provider 测试 / Preset 测试 / chat 复用。
支持 OpenAI (Chat Completions) 和 Anthropic (Messages) 两种 API 协议。
"""

import re

from app.ai.models import AiProvider

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


def build_chat_url(api_base: str, api_type: str = "openai") -> str:
    """根据 api_base 和 api_type 构造完整的 API URL。

    api_type="anthropic" 时拼 /messages; api_type="openai" 时拼 /chat/completions。
    如果 api_base 已包含完整端点路径,直接使用。
    """
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


def build_image_url(api_base: str, endpoint: str = "edits") -> str:
    """Build an OpenAI-compatible image endpoint URL."""
    base = api_base.rstrip("/")
    image_suffixes = ("/images/generations", "/images/edits", "/images/variations")
    if any(base.endswith(s) for s in image_suffixes):
        return base
    clean_endpoint = endpoint.strip("/")
    if any(base.endswith(v) for v in ("/v1", "/v2", "/v3", "/v4", "/api")):
        return f"{base}/images/{clean_endpoint}"
    return f"{base}/v1/images/{clean_endpoint}"


def build_headers(provider: AiProvider, api_key: str | None) -> dict:
    """构造请求头。支持通过 extra_headers 自定义认证方式 (如 api-key)。

    Anthropic 协议使用 x-api-key 头; OpenAI 使用 Bearer Authorization。
    extra_headers 中填 {"api-key": ""} 表示使用 api_key 字段的值作为 api-key。
    """
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "LeShine-Ark-AI/1.0",
    }
    extra = provider.extra_headers or {}
    for k, v in extra.items():
        if v == "" and k.lower() == "api-key" and api_key:
            headers[k] = api_key
        else:
            headers[k] = v

    has_auth = any(k.lower() in ("authorization", "api-key", "x-api-key") for k in headers)
    if api_key and not has_auth:
        if provider.api_type == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"
    return headers


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

    body = {
        "model": model,
        "messages": user_messages,
        "max_tokens": (parameters or {}).get("max_tokens", 4096),
    }
    if system_prompt:
        body["system"] = system_prompt

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
    usage = result.get("usage", {})
    return {
        "prompt_tokens": usage.get("input_tokens"),
        "completion_tokens": usage.get("output_tokens"),
        "total_tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
    }
