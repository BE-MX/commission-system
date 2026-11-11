"""项目雷达输入与 URL 归一。"""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.time import to_beijing_naive

_URL_RE = re.compile(r"(?:https?://|github\.com/)[^\s<>，。；、]+", re.IGNORECASE)
_TAG_RE = re.compile(r"(?<!\w)#([^\s#]+)", re.UNICODE)
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def parse_input(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    urls = []
    for match in _URL_RE.finditer(text):
        value = match.group(0).rstrip(")]}）】」’\"'")
        if value and value not in urls:
            urls.append(value)
    remainder = _URL_RE.sub(" ", text)
    tags = []
    for tag in _TAG_RE.findall(remainder):
        cleaned = tag.strip("，。；、,.;")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    note = re.sub(r"\s+", " ", _TAG_RE.sub(" ", remainder)).strip()
    return {"urls": urls, "note": note, "tags": tags}


def canonicalize_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise ValueError("链接不能为空")
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持 HTTP/HTTPS 链接")
    host = parsed.hostname.rstrip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    netloc = host + (f":{port}" if port and port not in {80, 443} else "")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    parts = [part for part in path.split("/") if part]
    if host == "github.com":
        if len(parts) < 2:
            raise ValueError("GitHub 链接需要包含仓库所有者和名称")
        owner, repo = parts[0], re.sub(r"\.git$", "", parts[1], flags=re.IGNORECASE)
        return f"https://github.com/{owner.lower()}/{repo.lower()}"
    path = "/" + "/".join(parts) if parts else ""
    query = urlencode([
        (key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ])
    return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def external_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    else:
        parsed = value
    return to_beijing_naive(parsed, naive_is_beijing=parsed.tzinfo is not None)
