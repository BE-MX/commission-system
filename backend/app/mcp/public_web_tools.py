"""Controlled public-web evidence tools for sales-discovery shadow runs."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from html.parser import HTMLParser
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.mcp.auth import MCPAuthError, require_identity


logger = logging.getLogger("commission.mcp.public_web")
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@contextmanager
def _session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str, indent=2)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _authorized(ctx, tool_name: str):
    with _session() as db:
        identity = require_identity(ctx, db, tool_name=tool_name)
        if not identity.get("_agent_run"):
            raise MCPAuthError("公开网络工具仅允许受控 Agent Run 调用")
        roles = set(identity.get("roles") or [])
        permissions = set(identity.get("permissions") or [])
        if "super_admin" not in roles and not ({"sales_automation:read", "sales_automation:invoke"} & permissions):
            raise MCPAuthError("权限不足：需要智能获客查看权限")


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.is_global)


def _validate_public_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("只允许访问公开 HTTPS URL")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("URL 不允许包含凭证或非标准端口")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("目标地址不是公开互联网主机")
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("目标域名无法解析") from exc
    if not addresses or any(not _public_ip(item) for item in addresses):
        raise ValueError("目标域名解析到非公开地址")
    return parsed.geturl()


def _validate_peer(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if not isinstance(peer, (tuple, list)) or not peer:
        raise ValueError("无法验证实际连接目标地址")
    if not _public_ip(str(peer[0])):
        raise ValueError("实际连接目标不是公开地址")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self.parts.append(cleaned)


class WebSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=2, max_length=300)
    count: int = Field(5, ge=1, le=10)


class PublicPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(..., min_length=12, max_length=2048)
    max_chars: int = Field(20_000, ge=1000, le=30_000)


def register_public_web_tools(mcp) -> None:
    @mcp.tool(name="search_web", annotations={"readOnlyHint": True, "openWorldHint": True})
    async def search_web(params: WebSearchInput, ctx: Context) -> str:
        try:
            _authorized(ctx, "search_web")
        except MCPAuthError as exc:
            return _err(str(exc))
        settings = get_settings()
        if not settings.AGENT_RUNTIME_WEB_SEARCH_ENABLED or not settings.AGENT_RUNTIME_BRAVE_SEARCH_API_KEY:
            return _err("受控网页搜索尚未配置")
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": settings.AGENT_RUNTIME_BRAVE_SEARCH_API_KEY,
            "User-Agent": "Leshine-Ark-Public-Evidence/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, verify=True) as client:
                response = await client.get(_BRAVE_SEARCH_URL, headers=headers, params={
                    "q": params.query, "count": params.count, "safesearch": "moderate",
                })
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Controlled web search failed: %s", type(exc).__name__)
            return _err("网页搜索暂时失败，请稍后重试")
        rows = ((payload.get("web") or {}).get("results") or [])[:params.count]
        return _ok([{
            "title": str(item.get("title") or "")[:500],
            "url": item.get("url"),
            "description": str(item.get("description") or "")[:1500],
        } for item in rows if isinstance(item, dict) and item.get("url")])

    @mcp.tool(name="fetch_public_page", annotations={"readOnlyHint": True, "openWorldHint": True})
    async def fetch_public_page(params: PublicPageInput, ctx: Context) -> str:
        try:
            _authorized(ctx, "fetch_public_page")
            url = await asyncio.to_thread(_validate_public_url, params.url)
        except (MCPAuthError, ValueError) as exc:
            return _err(str(exc))
        settings = get_settings()
        if not settings.AGENT_RUNTIME_WEB_SEARCH_ENABLED:
            return _err("受控网页抓取尚未开启")
        max_bytes = settings.AGENT_RUNTIME_PUBLIC_FETCH_MAX_BYTES
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, verify=True) as client:
                async with client.stream("GET", url, headers={
                    "Accept": "text/html,text/plain;q=0.9",
                    "User-Agent": "Leshine-Ark-Public-Evidence/1.0",
                }) as response:
                    response.raise_for_status()
                    _validate_peer(response)
                    content_type = response.headers.get("content-type", "").lower()
                    if not (content_type.startswith("text/html") or content_type.startswith("text/plain")):
                        return _err("目标页面不是支持的 HTML/纯文本类型")
                    declared = int(response.headers.get("content-length") or 0)
                    if declared > max_bytes:
                        return _err("目标页面超过抓取大小限制")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > max_bytes:
                            return _err("目标页面超过抓取大小限制")
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Controlled public fetch failed: %s", type(exc).__name__)
            return _err("公开页面抓取失败，请检查 URL 或稍后重试")
        text = chunks.decode(response.encoding or "utf-8", errors="replace")
        if content_type.startswith("text/html"):
            parser = _TextExtractor()
            parser.feed(text)
            text = "\n".join(parser.parts)
        return _ok({
            "url": url,
            "content_type": content_type.split(";", 1)[0],
            "text": text[:params.max_chars],
            "truncated": len(text) > params.max_chars,
        })
