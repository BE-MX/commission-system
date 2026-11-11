"""项目雷达 GitHub、网站与线索抓取适配。"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import get_settings
from app.core.public_fetch import clean_html, fetch_public
from app.project_radar.urls import external_datetime


def _status_code(exc: BaseException) -> int | None:
    cause = exc.__cause__
    return cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else None


def _repo_parts(canonical_url: str) -> tuple[str, str]:
    parts = [part for part in urlsplit(canonical_url).path.split("/") if part]
    if len(parts) != 2:
        raise ValueError("GitHub 仓库地址不完整")
    return parts[0], parts[1]


def _kind_for_page(url: str, text: str = "") -> str | None:
    value = (url + " " + text).lower()
    if any(token in value for token in ("changelog", "release", "releases", "what-s-new", "whats-new", "news")):
        return "changelog"
    if any(token in value for token in ("rss", "atom", "feed", ".xml")):
        return "rss"
    if any(token in value for token in ("pricing", "price", "plans")):
        return "pricing"
    if any(token in value for token in ("docs", "documentation", "developer")):
        return "docs"
    return None


class RadarFetcher:
    def __init__(self, *, transport=None):
        self.settings = get_settings()
        self.transport = transport

    def _get(self, url, *, github=False, etag=None, x_proxy=False, headers=None):
        request_headers = dict(headers or {})
        if github:
            request_headers["Accept"] = "application/vnd.github+json"
            request_headers["X-GitHub-Api-Version"] = "2022-11-28"
            if self.settings.PROJECT_RADAR_GITHUB_TOKEN:
                request_headers["Authorization"] = f"Bearer {self.settings.PROJECT_RADAR_GITHUB_TOKEN}"
        if etag:
            request_headers["If-None-Match"] = etag
        proxy = self.settings.PROJECT_RADAR_X_PROXY if x_proxy else self.settings.PROJECT_RADAR_HTTP_PROXY
        return fetch_public(
            url, headers=request_headers, proxy_url=proxy or None,
            transport=self.transport,
        )

    @staticmethod
    def _json(response):
        if response.status_code == 304:
            return None
        return json.loads(response.text)

    def read_target(self, target, *, include_content=True):
        if target.kind == "repo":
            return self.read_repo(target, include_content=include_content)
        return self.read_website(target.canonical_url)

    def read_repo(self, target, *, include_content=True):
        owner, repo = _repo_parts(target.canonical_url)
        base = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            repo_response = self._get(base, github=True, etag=target.repo_etag)
        except RuntimeError as exc:
            if _status_code(exc) == 404:
                return {"deleted": True, "unchanged": False, "facts": {}, "events": []}
            raise
        release_response = self._get(f"{base}/releases?per_page=5", github=True, etag=target.release_etag)
        unchanged = repo_response.status_code == 304 and release_response.status_code == 304
        repo_data = self._json(repo_response) or {}
        releases = self._json(release_response) or []
        latest = next((item for item in releases if not item.get("draft")), None)
        facts = {
            "title": repo_data.get("name") or target.title,
            "description_source": repo_data.get("description") or "",
            "stars": repo_data.get("stargazers_count", target.stars),
            "license": (repo_data.get("license") or {}).get("spdx_id") or target.license,
            "language": repo_data.get("language") or target.language,
            "archived": repo_data.get("archived", target.archived),
            "version": (latest or {}).get("tag_name") or (target.version if release_response.status_code == 304 else None),
            "last_updated_at": external_datetime((latest or {}).get("published_at")) or (
                target.last_updated_at if release_response.status_code == 304 else external_datetime(repo_data.get("pushed_at"))
            ),
        }
        if not latest and release_response.status_code != 304:
            tags_response = self._get(f"{base}/tags?per_page=1", github=True)
            tags = self._json(tags_response) or []
            facts["version"] = (tags[0].get("name") if tags else None)
        text = ""
        if include_content:
            try:
                readme = self._get(f"{base}/readme", github=True, headers={"Accept": "application/vnd.github.raw+json"})
                text = readme.text[:500_000]
            except RuntimeError as exc:
                if _status_code(exc) != 404:
                    raise
        return {
            "deleted": False, "unchanged": unchanged, "facts": facts, "text": text,
            "latest_release": latest, "repo_etag": repo_response.etag or target.repo_etag,
            "release_etag": release_response.etag or target.release_etag,
        }

    def read_website(self, url):
        response = self._get(url)
        cleaned = clean_html(response.text)
        source_path = urlsplit(response.url).path.rstrip("/")
        pages = []
        for link in cleaned["links"]:
            absolute = urljoin(response.url, link["href"])
            parsed = urlsplit(absolute)
            if parsed.hostname != urlsplit(response.url).hostname:
                continue
            kind = _kind_for_page(parsed.path, link.get("text") or "")
            if kind and parsed.path.rstrip("/") != source_path and absolute not in {item["url"] for item in pages}:
                pages.append({"url": absolute, "page_kind": kind})
            if len(pages) >= 3:
                break
        return {
            "title": cleaned["title"] or urlsplit(response.url).hostname,
            "text": cleaned["text"][:500_000], "links": cleaned["links"], "tracked_pages": pages,
            "etag": response.etag, "final_url": response.url,
        }

    def read_page(self, url, *, etag=None):
        response = self._get(url, etag=etag)
        if response.status_code == 304:
            return {"unchanged": True, "etag": etag, "text": ""}
        return {
            "unchanged": False, "etag": response.etag or etag,
            "text": clean_html(response.text)["text"], "final_url": response.url,
        }

    def read_clue(self, url):
        host = (urlsplit(url).hostname or "").lower()
        if host in {"x.com", "twitter.com"}:
            match = re.search(r"/status(?:es)?/(\d+)", urlsplit(url).path)
            if not match:
                raise ValueError("X 帖子地址缺少状态 ID")
            response = self._get(
                f"https://cdn.syndication.twimg.com/tweet-result?id={match.group(1)}&lang=zh-cn",
                x_proxy=True,
            )
            payload = self._json(response)
            text = payload.get("text") or ""
            links = [item.get("expanded_url") for item in (payload.get("entities", {}).get("urls") or [])]
            return {"title": (payload.get("user", {}).get("name") or "X 帖子"), "text": text,
                    "links": [link for link in links if link]}
        page = self.read_website(url)
        return {"title": page["title"], "text": page["text"], "links": [item["href"] for item in page["links"]]}
