"""方舟洞见 — 信源数据抓取 (RSS / HTML / aihot API) + 过滤"""

from __future__ import annotations

import html.parser
import json
import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


logger = logging.getLogger("insight")

# ── 上传目录 ──────────────────────────────────────────
INSIGHT_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "insight"
INSIGHT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Jinja2 模板环境 ─────────────────────────────────────
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)



def filter_items(items: list[dict], keywords: list[str] | None, exclude_keywords: list[str] | None) -> list[dict]:
    """
    两级过滤：先包含，再排除。
    - keywords: 非空时，标题/摘要必须命中至少一个关键词，未命中则丢弃
    - exclude_keywords: 非空时，标题/摘要命中任一排除词则丢弃
    """
    result = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

        # 第1级：包含过滤
        if keywords:
            if not any(str(kw).lower() in text for kw in keywords):
                continue

        # 第2级：排除过滤
        if exclude_keywords:
            if any(str(kw).lower() in text for kw in exclude_keywords):
                continue

        result.append(item)

    return result


def _build_urlopen_handler(proxy_url: str | None) -> urllib.request.OpenerDirector:
    """根据 proxy_url 构建 urllib opener；None 则返回默认 opener。"""
    if proxy_url:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()


def _make_request(url: str, headers: dict | None = None, proxy_url: str | None = None, timeout: int = 15):
    """构建并发起 urllib 请求,返回 response 对象。"""
    hdrs = {"User-Agent": _DEFAULT_UA, "Accept": "*/*"}
    if headers and isinstance(headers, dict):
        # 只接受 string→string 的 header 对，过滤掉配置数据误存的情况
        for k, v in headers.items():
            if isinstance(k, str) and isinstance(v, str):
                hdrs[k] = v
    opener = _build_urlopen_handler(proxy_url)
    req = urllib.request.Request(url, headers=hdrs)
    return opener.open(req, timeout=timeout)


def fetch_rss(url: str, headers: dict | None = None, proxy_url: str | None = None) -> list[dict]:
    """抓取并解析 RSS 2.0 / Atom feed。返回 [{title, summary, url, published}]。"""
    try:
        with _make_request(url, headers, proxy_url) as resp:
            content = resp.read()
    except Exception as e:
        logger.warning("RSS fetch failed: %s — %s", url, e)
        return []

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.warning("RSS parse failed: %s — %s", url, e)
        return []

    items: list[dict] = []

    # RSS 2.0: rss/channel/item
    for item_el in root.findall(".//item"):
        title = (item_el.findtext("title") or "").strip()
        link = (item_el.findtext("link") or "").strip()
        desc = (item_el.findtext("description") or "").strip()
        pub = (item_el.findtext("pubDate") or "").strip()
        if title:
            items.append({"title": title, "summary": desc, "url": link, "published": pub})

    # Atom: feed/entry
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry_el in root.findall(".//atom:entry", ns) or root.findall(".//entry"):
            title = (entry_el.findtext("atom:title", namespaces=ns) or entry_el.findtext("title") or "").strip()
            link_el = entry_el.find("atom:link[@rel='alternate']", ns) or entry_el.find("atom:link", ns) or entry_el.find("link")
            link = ""
            if link_el is not None:
                link = link_el.get("href", "") or (link_el.text or "").strip()
            summary = (entry_el.findtext("atom:summary", namespaces=ns) or entry_el.findtext("summary") or
                       entry_el.findtext("atom:content", namespaces=ns) or entry_el.findtext("content") or "").strip()
            pub = (entry_el.findtext("atom:published", namespaces=ns) or entry_el.findtext("published") or
                   entry_el.findtext("atom:updated", namespaces=ns) or entry_el.findtext("updated") or "").strip()
            if title:
                items.append({"title": title, "summary": summary, "url": link, "published": pub})

    return items


class _CssSelectorMatcher:
    """简易 CSS 选择器匹配器,支持 tag / .class / #id / tag.class / tag#id。"""

    def __init__(self, selector: str):
        self.tag = None
        self.cls = None
        self.id_ = None
        # 解析 "tag.class#id" 格式
        parts = selector.split("#", 1)
        before_hash = parts[0]
        if len(parts) > 1:
            self.id_ = parts[1]
        dot_parts = before_hash.split(".", 1)
        self.tag = dot_parts[0] or None
        if len(dot_parts) > 1:
            self.cls = dot_parts[1]

    def matches(self, tag: str, attrs: dict) -> bool:
        if self.tag and tag != self.tag:
            return False
        if self.cls:
            classes = attrs.get("class", "").split()
            if self.cls not in classes:
                return False
        if self.id_:
            if attrs.get("id") != self.id_:
                return False
        return True


class _HtmlExtractor(html.parser.HTMLParser):
    """HTML 解析器：按 CSS 选择器提取匹配元素的文本和链接。"""

    def __init__(self, matcher: _CssSelectorMatcher | None):
        super().__init__()
        self.matcher = matcher
        self.results: list[dict] = []
        self._depth = 0  # 匹配元素内的嵌套深度
        self._capturing = False
        self._current_text: list[str] = []
        self._current_url: str = ""
        self._stack: list[tuple[str, dict]] = []  # (tag, attrs) 栈

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._stack.append((tag, attrs_dict))
        if self.matcher and self.matcher.matches(tag, attrs_dict):
            self._capturing = True
            self._depth = 0
            self._current_text = []
            self._current_url = attrs_dict.get("href", "")
        elif self._capturing:
            self._depth += 1
            # 捕获子元素的 href
            if tag == "a" and not self._current_url:
                self._current_url = attrs_dict.get("href", "")

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()
        if self._capturing:
            if self._depth == 0:
                text = " ".join(self._current_text).strip()
                text = re.sub(r"\s+", " ", text)
                if text:
                    self.results.append({
                        "title": text[:200],
                        "summary": text[:500],
                        "url": self._current_url,
                    })
                self._capturing = False
                self._current_text = []
                self._current_url = ""
            else:
                self._depth -= 1

    def handle_data(self, data):
        if self._capturing and data.strip():
            self._current_text.append(data.strip())


def fetch_html(
    url: str,
    css_selector: str | None = None,
    headers: dict | None = None,
    proxy_url: str | None = None,
) -> list[dict]:
    """抓取 HTML 并按 CSS 选择器提取元素。返回 [{title, summary, url}]。"""
    try:
        with _make_request(url, headers, proxy_url) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("HTML fetch failed: %s — %s", url, e)
        return []

    if not css_selector:
        # 无选择器，返回整页纯文本
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return [{"title": text[:200], "summary": text[:500], "url": url}]
        return []

    matcher = _CssSelectorMatcher(css_selector)
    parser = _HtmlExtractor(matcher)
    try:
        parser.feed(content)
    except Exception as e:
        logger.warning("HTML parse failed: %s — %s", url, e)
        return []
    return parser.results


def fetch_aihot_daily() -> dict:
    """从 aihot API 拉取最新日报。返回 {date, lead, sections, flashes}。"""
    url = f"{_AIHOT_BASE_URL}/api/public/daily"
    hdrs = {"User-Agent": _DEFAULT_UA, "Accept": "application/json"}
    opener = _build_urlopen_handler(None)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with opener.open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception as e:
        logger.exception("aihot daily fetch failed")
        raise RuntimeError(f"aihot API 调用失败: {e}") from e
