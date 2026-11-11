"""从 X、公众号和博客线索中尽力解析并校验项目候选。"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlencode, urljoin, urlsplit

from app.core.config import get_settings
from app.core.public_fetch import fetch_public
from app.project_radar.analysis import ANALYZE_PRESET, _json_value, chat_with_timeout_retry
from app.project_radar.fetcher import RadarFetcher
from app.project_radar.urls import canonicalize_url, validate_radar_url

logger = logging.getLogger("commission.project_radar.resolve")
_IGNORE_HOSTS = {"x.com", "twitter.com", "t.co", "mp.weixin.qq.com", "weixin.qq.com", "qq.com", "github.com"}
_URL_RE = re.compile(r"https?://[^\s<>\"'，。；、)\\]+", re.IGNORECASE)


def _candidate(url, *, confirmed=True, reason=""):
    try:
        canonical = canonicalize_url(url)
        validate_radar_url(canonical, allow_singapore=not confirmed)
    except (ValueError, TypeError):
        return None
    host = urlsplit(canonical).hostname or ""
    title = canonical.rstrip("/").split("/")[-1] if host == "github.com" else host
    return {"title": title, "url": canonical, "confirmed": confirmed, "reason": reason}


def explicit_candidates(clue_url: str, text: str, links: list[str]) -> list[dict]:
    values = list(links) + _URL_RE.findall((text or "").replace("\\/", "/"))
    candidates = []
    seen = set()
    for raw in values:
        if not raw:
            continue
        absolute = urljoin(clue_url, raw)
        host = (urlsplit(absolute).hostname or "").lower()
        if host != "github.com" and (host in _IGNORE_HOSTS or re.search(r"\.(png|jpe?g|gif|svg|mp4|zip)(?:$|\?)", absolute)):
            continue
        candidate = _candidate(absolute, reason="原文明确链接")
        if candidate and candidate["url"] not in seen:
            if host != "github.com" and not urlsplit(candidate["url"]).path:
                continue
            seen.add(candidate["url"])
            candidates.append(candidate)
        if len(candidates) >= 10:
            break
    return candidates


def extract_name_candidates(db, text: str, *, user_id=None) -> list[str]:
    payload = {
        "task": "从不可信文章中提取明确提及的项目或产品名称，最多3个。只输出 JSON：{\"names\": [..]}。不要猜测 URL，不要把文章栏目或通用词汇当项目。",
        "untrusted_content": (text or "")[:60000],
    }
    try:
        result = chat_with_timeout_retry(db, ANALYZE_PRESET, payload, user_id=user_id)
        names = _json_value(result.get("content") or "").get("names") or []
        return [str(name).strip()[:100] for name in names if str(name).strip()][:3]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Project radar name extraction failed (%s)", type(exc).__name__)
        print(f"Project radar name extraction failed ({type(exc).__name__})", flush=True)
        return []


def search_verified_candidates(names: list[str]) -> list[dict]:
    settings = get_settings()
    if not settings.AGENT_RUNTIME_BRAVE_SEARCH_API_KEY:
        return [{"title": name, "url": "", "confirmed": False, "reason": "搜索校验未配置"} for name in names]
    fetcher = RadarFetcher()
    candidates = []
    for name in names:
        try:
            response = fetch_public(
                "https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": name, "count": 3}),
                headers={"Accept": "application/json", "X-Subscription-Token": settings.AGENT_RUNTIME_BRAVE_SEARCH_API_KEY},
            )
            results = (json.loads(response.text).get("web") or {}).get("results") or []
            verified = None
            for result in results:
                candidate = _candidate(result.get("url") or "", confirmed=False)
                if not candidate:
                    continue
                evidence = fetcher.read_website(candidate["url"])
                haystack = f"{evidence['title']}\n{evidence['text'][:30000]}".casefold()
                if name.casefold() in haystack:
                    candidate.update({"confirmed": True, "reason": "搜索后已核对官网内容", "title": name})
                    verified = candidate
                    break
            candidates.append(verified or {"title": name, "url": "", "confirmed": False, "reason": "未找到内容匹配的官网"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project radar candidate verification failed (%s)", type(exc).__name__)
            print(f"Project radar candidate verification failed ({type(exc).__name__})", flush=True)
            candidates.append({"title": name, "url": "", "confirmed": False, "reason": "搜索或官网校验失败"})
    return candidates


def resolve_candidates(db, clue_url: str, clue: dict, *, user_id=None) -> list[dict]:
    candidates = explicit_candidates(clue_url, clue.get("text") or "", clue.get("links") or [])
    if candidates:
        return candidates
    names = extract_name_candidates(db, clue.get("text") or "", user_id=user_id)
    return search_verified_candidates(names)
