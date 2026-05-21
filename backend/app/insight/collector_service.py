"""方舟洞见 — 采集引擎 (按信源类型路由采集器)"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.insight.models import InsightCollectionLog, InsightItem, InsightSource
from app.insight.fetcher import fetch_rss, fetch_html, filter_items

logger = logging.getLogger("insight")


# ── 采集器注册表 ──────────────────────────────────────────
_COLLECTORS = {}


def register_collector(source_type: str):
    """装饰器：注册采集器函数。"""
    def decorator(fn):
        _COLLECTORS[source_type] = fn
        return fn
    return decorator


# ── RSS 采集器 ────────────────────────────────────────────
@register_collector("google_alerts_rss")
@register_collector("google_trends_rss")
@register_collector("competitor_rss")
def _collect_rss(source: InsightSource, db: Session) -> list[dict]:
    """RSS/Atom 采集。"""
    raw = fetch_rss(source.url, source.request_headers, source.proxy_url)
    return filter_items(raw, source.keywords, source.exclude_keywords)


# ── HTML 采集器 ───────────────────────────────────────────
@register_collector("pinterest_scrape")
@register_collector("amazon_bestseller")
@register_collector("competitor_html")
def _collect_html(source: InsightSource, db: Session) -> list[dict]:
    """HTML 页面采集。"""
    raw = fetch_html(source.url, source.css_selector, source.request_headers, source.proxy_url)
    return filter_items(raw, source.keywords, source.exclude_keywords)


# ── aihot API 采集器 ──────────────────────────────────────
@register_collector("aihot_api")
def _collect_aihot(source: InsightSource, db: Session) -> list[dict]:
    """aihot 内部 API — 不写入 intelligence_item，直接用于报告生成管线。"""
    # aihot 数据走现有 reports_service 管线，不通过采集库
    logger.debug("aihot_api source skipped in collector (handled by reports_service)")
    return []


# ── XPOZ 采集器 (TODO) ───────────────────────────────────
@register_collector("xpoz")
def _collect_xpoz(source: InsightSource, db: Session) -> list[dict]:
    """XPOZ SDK 社媒采集 — 待接入。"""
    config = source.config_json or {}
    target_accounts = config.get("target_accounts", [])
    if not target_accounts:
        logger.warning("XPOZ source %s has no target_accounts, skipping", source.id)
        return []
    # TODO: 接入 XPOZ MCP Server
    logger.info("XPOZ collection not yet implemented for source %s", source.id)
    return []


# ── 竞品监控采集器 (TODO) ─────────────────────────────────
@register_collector("competitor_monitor")
def _collect_competitor(source: InsightSource, db: Session) -> list[dict]:
    """竞品定向监控 — 待接入。"""
    config = source.config_json or {}
    monitor_fields = config.get("monitor_fields", [])
    logger.info("Competitor monitor not yet implemented for source %s, fields=%s", source.id, monitor_fields)
    return []


# ── Perplexity 采集器 (TODO) ──────────────────────────────
@register_collector("perplexity")
def _collect_perplexity(source: InsightSource, db: Session) -> list[dict]:
    """Perplexity Pro 报告采集 — 待接入。"""
    logger.info("Perplexity collection not yet implemented for source %s", source.id)
    return []


# ── Amazon 采集器 (TODO) ──────────────────────────────────
@register_collector("amazon")
def _collect_amazon(source: InsightSource, db: Session) -> list[dict]:
    """Amazon BSR/评论采集 — 待接入。"""
    logger.info("Amazon collection not yet implemented for source %s", source.id)
    return []


# ── 手工上传 (不走自动采集) ───────────────────────────────
@register_collector("manual")
def _collect_manual(source: InsightSource, db: Session) -> list[dict]:
    """手工信源 — 不自动采集。"""
    return []


# ── 统一入库 ──────────────────────────────────────────────
def _write_items(db: Session, source: InsightSource, raw_items: list[dict]) -> int:
    """将原始条目写入 intelligence_item 表。返回写入数量。"""
    written = 0
    for raw in raw_items:
        title = raw.get("title", "")[:512]
        url = raw.get("url", "")
        summary = raw.get("summary", "")

        # 去重：同 source + url 已存在则跳过
        if url:
            existing = (
                db.query(InsightItem)
                .filter(InsightItem.source_id == source.id, InsightItem.original_url == url)
                .first()
            )
            if existing:
                continue

        item = InsightItem(
            source_id=source.id,
            source_type=source.source_type,
            collected_at=datetime.utcnow(),
            title=title,
            content_mode="summary",
            content_md=summary,
            original_url=url,
            item_type="industry_news",
            status="active",
            priority="medium",
        )
        db.add(item)
        written += 1

    db.commit()
    return written


# ── 对外接口 ──────────────────────────────────────────────
def collect_source(db: Session, source_id: int) -> dict:
    """对指定信源立即触发一次采集。返回执行结果。"""
    source = db.query(InsightSource).filter(InsightSource.id == source_id).first()
    if not source:
        raise ValueError(f"信源不存在: id={source_id}")
    if not source.is_active:
        raise ValueError(f"信源已停用: id={source_id}")

    start_time = time.time()
    collector = _COLLECTORS.get(source.source_type)

    log = InsightCollectionLog(
        source_id=source.id,
        run_at=datetime.utcnow(),
        status="success",
    )

    try:
        if collector is None:
            raise ValueError(f"未找到采集器: source_type={source.source_type}")

        raw_items = collector(source, db)
        log.items_fetched = len(raw_items)

        # 关键词过滤统计
        if source.keywords or source.exclude_keywords:
            # collector 内部已做 filter_items，这里统计差值
            pass

        written = _write_items(db, source, raw_items)
        log.items_written = written
        log.items_filtered = len(raw_items) - written

        # 更新信源状态
        source.last_fetched_at = datetime.utcnow()
        source.last_error = None
        source.consecutive_failures = 0

        logger.info("Collected source id=%s type=%s fetched=%d written=%d",
                    source.id, source.source_type, len(raw_items), written)

    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)[:500]
        source.last_error = str(e)[:500]
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        logger.exception("Collect source failed: id=%s", source_id)

    log.duration_ms = int((time.time() - start_time) * 1000)
    db.add(log)
    db.commit()

    return {
        "source_id": source_id,
        "status": log.status,
        "items_fetched": log.items_fetched,
        "items_written": log.items_written,
        "items_filtered": log.items_filtered,
        "duration_ms": log.duration_ms,
        "error_message": log.error_message,
    }


def run_collection_batch(db: Session, source_type: Optional[str] = None) -> list[dict]:
    """批量执行采集 — 遍历所有活跃信源。"""
    query = db.query(InsightSource).filter(InsightSource.is_active == True)
    if source_type:
        query = query.filter(InsightSource.source_type == source_type)

    sources = query.all()
    results = []
    for source in sources:
        try:
            result = collect_source(db, source.id)
            results.append(result)
        except Exception:
            logger.exception("Batch collect failed for source id=%s", source.id)
            results.append({
                "source_id": source.id,
                "status": "failed",
                "error_message": "批量采集异常",
            })
    return results
