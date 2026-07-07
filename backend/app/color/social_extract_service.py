"""社媒色彩提取服务 — 从 Xpoz 竞品帖子提取主色并匹配色族

定时任务:
    - 每日 08:00 执行 social_color_extraction
    - 每周一 06:00 执行 sales_color_aggregation

TODO: Xpoz SDK 接入完成后实现 _fetch_xpoz_posts
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.color.calc_service import extract_dominant_colors, find_nearest_palette
from app.color.models import ColorPalette, ColorTrendData, CompetitorColorWatch
from app.color.trend_service import normalize_scores, write_trend_data

logger = logging.getLogger("color.social")

# 竞品 Instagram 账号列表（从信源配置或环境变量读取）
from app.core.config import get_settings

DEFAULT_TARGET_ACCOUNTS = get_settings().XPOZ_TARGET_ACCOUNTS.split(",")
DEFAULT_TARGET_ACCOUNTS = [a.strip() for a in DEFAULT_TARGET_ACCOUNTS if a.strip()]


def _fetch_xpoz_posts(accounts: list[str], days: int = 1) -> list[dict]:
    """
    从 Xpoz SDK 拉取竞品社媒帖子。

    TODO: 接入 Xpoz MCP Server 后实现。
    当前返回空列表。
    """
    logger.info("Xpoz fetch not yet implemented, accounts=%s", accounts)
    return []


def _download_image(url: str) -> Optional[str]:
    """下载图片到临时文件，返回本地路径"""
    try:
        suffix = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            f.write(resp.content)
            return f.name
    except Exception as e:
        logger.warning("Download image failed: %s, error=%s", url, e)
        return None


def _match_color_family(hex_code: str, db: Session) -> Optional[str]:
    """匹配最近色号，返回色族"""
    result = find_nearest_palette(hex_code, db)
    return result["code"] if result else None


# ── 定时任务：社媒色彩提取 ─────────────────────────────────


def extract_social_colors(db: Session, target_accounts: Optional[list[str]] = None) -> dict:
    """
    每日定时任务：从 Xpoz 拉取竞品帖子 → 下载图片 → 提取主色 → 匹配色族 → 写入趋势表。

    返回统计信息。
    """
    accounts = target_accounts or DEFAULT_TARGET_ACCOUNTS
    if not accounts:
        logger.warning("No XPOZ target accounts configured, skipping social color extraction")
        return {"status": "skipped", "reason": "no_accounts"}

    posts = _fetch_xpoz_posts(accounts, days=1)
    if not posts:
        return {"status": "no_data", "posts_fetched": 0}

    family_counts = {}
    processed = 0
    errors = 0

    for post in posts:
        image_url = post.get("image_url") or post.get("media_url")
        if not image_url:
            continue

        tmp_path = _download_image(image_url)
        if not tmp_path:
            errors += 1
            continue

        try:
            colors = extract_dominant_colors(tmp_path, k=3)
            for color in colors:
                family = _match_color_family(color["hex"], db)
                if family:
                    family_counts[family] = family_counts.get(family, 0) + 1
            processed += 1
        except Exception as e:
            logger.warning("Extract colors failed: %s", e)
            errors += 1
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

    # 写入趋势表
    today = date.today()
    for family, count in family_counts.items():
        write_trend_data(
            db=db,
            color_family=family,
            data_source="social_xpoz",
            period_date=today,
            raw_value=float(count),
            period_type="daily",
        )

    # 归一化
    normalize_scores(db, today, "social_xpoz", "daily")

    return {
        "status": "success",
        "posts_fetched": len(posts),
        "images_processed": processed,
        "errors": errors,
        "family_counts": family_counts,
    }


# ── 定时任务：销售色彩聚合 ─────────────────────────────────


def aggregate_sales_by_color(db: Session) -> dict:
    """
    每周定时任务：从 okki_orders 按颜色字段聚合销量 → 写入趋势表。

    TODO: 需要确认 okki_orders 表中颜色字段的列名和值格式。
    """
    from app.core.database import engine

    week_start = date.today() - timedelta(days=date.today().weekday())

    try:
        # 尝试从 okki_orders 聚合（假设有 color 字段）
        # 注意：这是跨库查询，需要确认实际表结构
        sql = """
            SELECT color, SUM(quantity) as total_qty
            FROM lsordertest.okki_orders
            WHERE created_at >= %(start)s
              AND color IS NOT NULL AND color != ''
            GROUP BY color
        """
        with engine.connect() as conn:
            result = conn.execute(sql, {"start": week_start.isoformat()})
            rows = result.fetchall()

        # 将颜色字符串映射到色族（需要维护映射表）
        color_to_family = {
            "黑色": "black", "自然黑": "black", "乌黑": "black",
            "棕色": "brown", "深棕": "brown", "巧克力棕": "brown", "栗棕": "brown", "灰棕": "brown",
            "金色": "blonde", "脏金": "blonde", "蜜金": "blonde", "白金": "blonde", "极浅金": "blonde",
            "红色": "red", "亮红": "red", "勃艮第": "red",
            "银色": "silver", "灰色": "silver",
        }

        family_sales = {}
        for row in rows:
            color_name = row[0]
            qty = row[1] or 0
            family = color_to_family.get(color_name)
            if family:
                family_sales[family] = family_sales.get(family, 0) + qty

        # 写入趋势表
        for family, qty in family_sales.items():
            write_trend_data(
                db=db,
                color_family=family,
                data_source="sales",
                period_date=week_start,
                raw_value=float(qty),
                period_type="weekly",
            )

        normalize_scores(db, week_start, "sales", "weekly")

        return {
            "status": "success",
            "week_start": week_start.isoformat(),
            "families": len(family_sales),
            "family_sales": family_sales,
        }

    except Exception as e:
        logger.exception("Sales aggregation failed: %s", e)
        return {"status": "error", "error": str(e)}


# ── 竞品色号监控 ───────────────────────────────────────────


def scan_competitor_colors(db: Session, brand: str, product_url: str) -> Optional[dict]:
    """
    扫描竞品产品页，提取色号信息。
    TODO: 需要具体网站的爬虫逻辑。
    """
    logger.info("Competitor scan not yet implemented for %s", brand)
    return None
