"""AI HTTP 调用层公共助手

集中 chat/completions URL 拼接与请求头构造,供 Provider 测试 / Preset 测试 / chat 复用。
"""

from app.ai.models import AiProvider


def build_chat_url(api_base: str) -> str:
    """根据 api_base 构造完整的 chat/completions URL。

    如果 api_base 已包含版本号 (/v1 /v2 等) 或 /api 路径,直接拼接;
    否则自动补全 /v1 (主流平台默认)。
    """
    base = api_base.rstrip("/")
    if any(base.endswith(v) for v in ("/v1", "/v2", "/v3", "/v4", "/api")):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def build_headers(provider: AiProvider, api_key: str | None) -> dict:
    """构造请求头。支持通过 extra_headers 自定义认证方式 (如 api-key)。

    extra_headers 中填 {"api-key": ""} 表示使用 api_key 字段的值作为 api-key。
    没有显式 Authorization / api-key 时,自动追加 Bearer。
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

    has_auth = any(k.lower() in ("authorization", "api-key") for k in headers)
    if api_key and not has_auth:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
