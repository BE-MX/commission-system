"""方舟洞见 — 行业日报 / AI 工具速递 / 内部报告 (CRUD + 生成 + 渲染)"""

from __future__ import annotations

import csv
import html.parser
import io
import json
import logging
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, and_, desc, func
from sqlalchemy.orm import Session

from app.insight.models import (
    InsightReport,
    InsightSource,
    InsightCase,
    MeetingMinutes,
    InsightTask,
)
from app.insight.schemas import (
    ReportImport,
    SourceCreate,
    SourceUpdate,
    CaseManualCreate,
    CasePublish,
    CaseUpdate,
    MinutesUpload,
    TaskUpdate,
)

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

from app.insight.fetcher import fetch_rss, fetch_html, fetch_aihot_daily, filter_items


def list_reports(
    db: Session,
    report_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """报告列表查询 — 不返回 html_content 字段(性能)。"""
    query = db.query(
        InsightReport.id,
        InsightReport.report_type,
        InsightReport.report_date,
        InsightReport.title,
        InsightReport.status,
        InsightReport.report_metadata,
        InsightReport.created_at,
    )

    if report_type:
        if "," in report_type:
            types = [t.strip() for t in report_type.split(",") if t.strip()]
            query = query.filter(InsightReport.report_type.in_(types))
        else:
            query = query.filter(InsightReport.report_type == report_type)
    if start_date:
        query = query.filter(InsightReport.report_date >= start_date)
    if end_date:
        query = query.filter(InsightReport.report_date <= end_date)
    if status:
        query = query.filter(InsightReport.status == status)

    total = query.count()
    rows = (
        query.order_by(desc(InsightReport.report_date), desc(InsightReport.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": r.id,
            "report_type": r.report_type,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "title": r.title,
            "status": r.status,
            "report_metadata": r.report_metadata,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"total": total, "items": items}


def get_report(db: Session, report_id: int) -> InsightReport:
    r = db.query(InsightReport).filter(InsightReport.id == report_id).first()
    if not r:
        raise ValueError("报告不存在")
    return r


def get_report_html(db: Session, report_id: int) -> str:
    """获取报告 HTML 内容(优先 html_content,否则读 file_path)。"""
    r = get_report(db, report_id)
    if r.html_content:
        return r.html_content
    if r.file_path:
        p = Path(r.file_path)
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise ValueError("报告内容为空")


def import_report(db: Session, data: ReportImport, created_by: Optional[int] = None) -> InsightReport:
    """ACCIO WORK 等外部系统推送报告。"""
    valid_types = {"industry_daily", "ai_tools", "shop_analysis", "competitor_analysis", "inquiry_analysis"}
    if data.report_type not in valid_types:
        raise ValueError(f"非法的 report_type: {data.report_type}")

    r = InsightReport(
        report_type=data.report_type,
        report_date=data.report_date,
        title=data.title or f"{data.report_type} {data.report_date}",
        html_content=data.html_content,
        source_data=data.source_data,
        report_metadata=data.metadata,
        status="published",
        created_by=created_by,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    logger.info(f"Imported report id={r.id} type={r.report_type} date={r.report_date}")
    return r


def regenerate_report(db: Session, report_id: int, user_id: Optional[int] = None) -> InsightReport:
    """手动触发重新生成 — 按原 report_date 调用对应类型的 generate 函数。

    注意: _save_report 是幂等覆盖(同 report_type+date 删旧插新),返回的 InsightReport
    会是新 id,不再是入参 report_id 那一条。
    """
    r = get_report(db, report_id)
    report_type = r.report_type
    report_date_val = r.report_date

    r.status = "pending"
    r.error_msg = None
    db.commit()

    logger.info("Regenerating report id=%s type=%s date=%s", report_id, report_type, report_date_val)

    if report_type == "industry_daily":
        return generate_industry_daily_report(db, report_date_val)
    if report_type == "ai_tools":
        return generate_ai_tools_report(db, report_date_val)

    logger.warning("Report id=%s type=%s has no auto-regenerate impl, only status reset", report_id, report_type)
    db.refresh(r)
    return r


def render_industry_daily_html(report_date: date, data: dict) -> str:
    template = _jinja_env.get_template("industry_daily.html")
    return template.render(report_date=report_date, **data)


def render_ai_tools_html(report_date: date, grouped: dict) -> str:
    template = _jinja_env.get_template("ai_tools.html")
    return template.render(report_date=report_date, grouped=grouped)


def _save_report(
    db: Session,
    report_type: str,
    report_date: date,
    html_content: str,
    source_data: Any = None,
) -> InsightReport:
    """幂等保存报告：同日同类型覆盖旧记录。"""
    existing = (
        db.query(InsightReport)
        .filter(InsightReport.report_type == report_type, InsightReport.report_date == report_date)
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    r = InsightReport(
        report_type=report_type,
        report_date=report_date,
        title=f"{report_type} {report_date}",
        html_content=html_content,
        source_data=source_data,
        status="published",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    logger.info("Saved report id=%s type=%s date=%s", r.id, report_type, report_date)
    return r


def _organize_with_ai(db: Session, raw_items: list[dict], report_date: date) -> dict:
    """用 AI 将原始信源条目整理为行业日报 6 个板块。"""
    # 构建编号列表 prompt
    lines = []
    for i, item in enumerate(raw_items[:15], 1):  # 限制 15 条避免 token 超时
        title = item.get("title", "")
        summary = item.get("summary", "")
        src = item.get("source", "")
        entry = f"{i}. [{src}] {title}"
        if summary:
            entry += f" — {summary[:120]}"
        lines.append(entry)

    prompt = (
        f"以下是 {report_date} 从外部信源抓取的发制品行业相关条目。"
        "请整理为以下 JSON 对象（只输出 JSON，不要其他文字）：\n\n"
        "{\n"
        '  "quick_overview": ["条目1要点（20字以内）", ...],\n'
        '  "color_style_trends": "一段话总结今日发色/发型相关趋势（100字以内，无则空串）",\n'
        '  "trend_keywords": ["关键词1", "关键词2"],\n'
        '  "amazon_hot": [{"rank": 1, "name": "商品名", "change": "NEW/+2/-1", "reason": "简析"}],\n'
        '  "competitor_updates": [{"source": "信源名", "summary": "摘要（60字）", "url": "链接"}],\n'
        '  "supply_chain": "一段话总结供应链/原材料动态（80字以内，无则空串）"\n'
        "}\n\n"
        "规则：与发制品无关的条目直接忽略；没有数据的板块返回空数组或空字符串；不要编造信息。\n\n"
        f"原始条目：\n" + "\n".join(lines)
    )

    text = _try_invoke_ai(db, "insight_daily_organize", prompt)
    parsed = _safe_json_parse(text or "") if text else None

    if not parsed or not isinstance(parsed, dict):
        # 降级：raw_items 全部塞入 quick_overview
        logger.warning("AI organize failed or returned invalid JSON, using fallback")
        return {
            "quick_overview": [f"{item.get('title', '')}" for item in raw_items[:15] if item.get("title")],
            "color_style_trends": "",
            "trend_keywords": [],
            "amazon_hot": [],
            "competitor_updates": [],
            "supply_chain": "",
        }

    # 确保所有字段存在
    return {
        "quick_overview": parsed.get("quick_overview") or [],
        "color_style_trends": parsed.get("color_style_trends") or "",
        "trend_keywords": parsed.get("trend_keywords") or [],
        "amazon_hot": parsed.get("amazon_hot") or [],
        "competitor_updates": parsed.get("competitor_updates") or [],
        "supply_chain": parsed.get("supply_chain") or "",
    }


def generate_industry_daily_report(db: Session, report_date: date | None = None) -> InsightReport:
    """管线1：外部信源抓取 → 关键词过滤 → AI 整理 → 模板渲染 → 存库。"""
    report_date = report_date or date.today()
    sources = list_sources(db, is_active=True, pipeline="external")
    all_items: list[dict] = []

    for src in sources:
        try:
            if src.source_type.endswith("_rss"):
                raw = fetch_rss(src.url, src.request_headers, src.proxy_url)
            elif src.source_type in ("pinterest_scrape", "amazon_bestseller", "competitor_html"):
                raw = fetch_html(src.url, src.css_selector, src.request_headers, src.proxy_url)
            else:
                logger.warning("Unknown source_type: %s, skipping", src.source_type)
                continue

            filtered = filter_items(raw, src.keywords, src.exclude_keywords)
            # 给每条附加信源名称
            for item in filtered:
                item["source"] = src.name
            all_items.extend(filtered)

            src.last_fetched_at = datetime.utcnow()
            src.last_error = None
            src.consecutive_failures = 0
        except Exception as e:
            logger.exception("Source fetch failed: %s (id=%s)", src.name, src.id)
            src.last_error = str(e)[:500]
            src.consecutive_failures = (src.consecutive_failures or 0) + 1

    db.commit()

    logger.info("industry_daily: fetched %d items from %d sources", len(all_items), len(sources))

    # AI 整理
    data = _organize_with_ai(db, all_items, report_date)

    # 渲染 + 存库
    html_content = render_industry_daily_html(report_date, data)
    return _save_report(db, "industry_daily", report_date, html_content, source_data=data)


def generate_ai_tools_report(db: Session, report_date: date | None = None) -> InsightReport:
    """管线2：aihot API 日报 → 板块映射 → 模板渲染 → 存库。"""
    report_date = report_date or date.today()
    raw = fetch_aihot_daily()

    # 构建 grouped dict
    grouped: dict[str, list[dict]] = {"model": [], "product": [], "industry": [], "paper": [], "tips": []}
    for section in raw.get("sections", []):
        label = section.get("label", "")
        key = _AIHOT_SECTION_MAP.get(label, "industry")
        for item in section.get("items", []):
            grouped[key].append({
                "title": item.get("title", ""),
                "tag": item.get("sourceName", ""),
                "summary": item.get("summary", ""),
                "url": item.get("sourceUrl", ""),
            })

    # 快讯也加入 industry
    for flash in raw.get("flashes", []):
        grouped["industry"].append({
            "title": flash.get("title", ""),
            "tag": flash.get("sourceName", ""),
            "summary": "",
            "url": flash.get("sourceUrl", ""),
        })

    # 渲染 + 存库
    html_content = render_ai_tools_html(report_date, grouped)
    source_data = {"grouped": grouped, "api_date": raw.get("date")}
    return _save_report(db, "ai_tools", report_date, html_content, source_data=source_data)
