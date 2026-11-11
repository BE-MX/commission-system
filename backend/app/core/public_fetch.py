"""受限公网抓取：URL 校验、逐跳重定向、响应上限与正文提取。"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import logging
import socket
from urllib.parse import urljoin

import httpx

from app.mcp.public_web_tools import _validate_peer, _validate_public_url

logger = logging.getLogger("commission.public_fetch")
_ALLOWED_CONTENT = ("text/", "application/json", "application/xml", "application/rss+xml", "application/atom+xml")


@dataclass
class PublicResponse:
    url: str
    status_code: int
    content: bytes
    content_type: str
    encoding: str
    etag: str | None

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.title_parts = []
        self.hidden_depth = 0
        self.in_title = False
        self.current_href = None
        self.current_link_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.hidden_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "a":
            self.current_href = attrs.get("href") or ""
            self.current_link_text = []
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "tr"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "template"} and self.hidden_depth:
            self.hidden_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.current_href is not None:
            text = " ".join(" ".join(self.current_link_text).split())
            if self.current_href and not self.current_href.startswith(("javascript:", "data:")):
                self.links.append({"href": self.current_href, "text": text})
            self.current_href = None
            self.current_link_text = []
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "tr"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.hidden_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self.in_title:
            self.title_parts.append(cleaned)
        self.parts.append(cleaned + " ")
        if self.current_href is not None:
            self.current_link_text.append(cleaned)


def fetch_public(
    url: str,
    *,
    headers: dict | None = None,
    proxy_url: str | None = None,
    timeout: float = 15,
    max_bytes: int = 5 * 1024 * 1024,
    max_redirects: int = 5,
    transport: httpx.BaseTransport | None = None,
) -> PublicResponse:
    current = _validate_public_url(url)
    request_headers = {"User-Agent": "Leshine-Ark-Project-Radar/1.0", "Accept": "*/*"}
    request_headers.update({str(k): str(v) for k, v in (headers or {}).items()})
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=False, verify=True,
            proxy=proxy_url or None, transport=transport,
        ) as client:
            for redirect_count in range(max_redirects + 1):
                with client.stream("GET", current, headers=request_headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect_count >= max_redirects:
                            raise ValueError("重定向次数超过限制")
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("重定向缺少目标地址")
                        current = _validate_public_url(urljoin(current, location))
                        continue
                    if not proxy_url:
                        _validate_peer(response)
                    content_type = response.headers.get("content-type", "").lower()
                    if response.status_code == 304 and (
                        "if-none-match" in response.request.headers
                        or "if-modified-since" in response.request.headers
                    ):
                        return PublicResponse(
                            url=current, status_code=304, content=b"",
                            content_type=content_type, encoding=response.encoding or "utf-8",
                            etag=response.headers.get("etag"),
                        )
                    response.raise_for_status()
                    if content_type and not content_type.startswith(_ALLOWED_CONTENT):
                        raise ValueError("目标响应不是支持的文本类型")
                    declared = int(response.headers.get("content-length") or 0)
                    if declared > max_bytes:
                        raise ValueError("目标页面超过抓取大小限制")
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > max_bytes:
                            raise ValueError("目标页面超过抓取大小限制")
                    return PublicResponse(
                        url=current, status_code=response.status_code, content=bytes(chunks),
                        content_type=content_type, encoding=response.encoding or "utf-8",
                        etag=response.headers.get("etag"),
                    )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Public fetch failed (%s)", type(exc).__name__)
        print(f"Public fetch failed ({type(exc).__name__})", flush=True)
        raise RuntimeError("公开页面读取失败，请稍后重试") from exc
    raise ValueError("重定向次数超过限制")


def clean_html(html: str) -> dict:
    parser = _PageParser()
    parser.feed(html or "")
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return {
        "title": " ".join(parser.title_parts).strip(),
        "text": "\n".join(line for line in lines if line).strip(),
        "links": parser.links,
    }
