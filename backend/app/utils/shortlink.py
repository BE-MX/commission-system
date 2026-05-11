"""is.gd 短链生成工具"""

import logging
import time

import httpx

logger = logging.getLogger("commission.shortlink")

_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600  # 60 分钟


def generate_short_link(url: str) -> str:
    """调用 is.gd 生成短链，失败时返回原始 URL。带 60 分钟内存缓存。"""
    now = time.time()
    cached = _cache.get(url)
    if cached:
        short_url, ts = cached
        if now - ts < _CACHE_TTL:
            return short_url

    try:
        resp = httpx.get(
            "https://is.gd/create.php",
            params={"format": "simple", "url": url},
            timeout=5,
            follow_redirects=True,
        )
        resp.raise_for_status()
        short_url = resp.text.strip()
        if short_url.startswith("http"):
            _cache[url] = (short_url, now)
            return short_url
        logger.warning("is.gd 返回异常: %s", short_url)
    except Exception as exc:
        logger.warning("is.gd 短链生成失败: %s", exc)

    return url
