"""方舟洞见 — 信源 CRUD + 连通性测试"""

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

from app.insight.fetcher import fetch_rss, fetch_html


def list_sources(
    db: Session,
    source_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    pipeline: Optional[str] = None,
) -> list[InsightSource]:
    query = db.query(InsightSource)
    if source_type:
        query = query.filter(InsightSource.source_type == source_type)
    if is_active is not None:
        query = query.filter(InsightSource.is_active.is_(is_active))
    if pipeline:
        query = query.filter(InsightSource.pipeline == pipeline)
    return query.order_by(InsightSource.sort_order, InsightSource.id).all()


def get_source(db: Session, source_id: int) -> InsightSource:
    s = db.query(InsightSource).filter(InsightSource.id == source_id).first()
    if not s:
        raise ValueError("信源不存在")
    return s


def create_source(db: Session, data: SourceCreate) -> InsightSource:
    s = InsightSource(**data.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def update_source(db: Session, source_id: int, data: SourceUpdate) -> InsightSource:
    s = get_source(db, source_id)
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


def delete_source(db: Session, source_id: int) -> None:
    """软删除:置 is_active=False。"""
    s = get_source(db, source_id)
    s.is_active = False
    db.commit()


def test_source(db: Session, source_id: int) -> dict:
    """信源连通性测试 — HEAD/GET 探测，支持代理。"""
    import urllib.request
    import urllib.error

    s = get_source(db, source_id)
    start = time.time()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }
    if s.request_headers:
        headers.update(s.request_headers)

    opener = _build_urlopen_handler(s.proxy_url)

    try:
        req = urllib.request.Request(s.url, method="GET", headers=headers)
        with opener.open(req, timeout=15) as resp:
            status_code = resp.status
            content = resp.read(2048).decode("utf-8", errors="replace")
        elapsed = int((time.time() - start) * 1000)

        # 简单解析:RSS 检测 <item> 数量
        preview = []
        if "<item>" in content or "<entry>" in content:
            # 粗略统计
            import re as _re
            items = _re.findall(r"<title[^>]*>(.*?)</title>", content)
            preview = [{"title": (t or "")[:80]} for t in items[:5]]

        # 标记成功
        s.last_fetched_at = datetime.utcnow()
        s.last_error = None
        s.consecutive_failures = 0
        db.commit()

        return {
            "success": True,
            "status_code": status_code,
            "latency_ms": elapsed,
            "preview": preview,
            "error": None,
        }
    except urllib.error.HTTPError as e:
        elapsed = int((time.time() - start) * 1000)
        msg = f"HTTP {e.code} {e.reason}"
        s.last_error = msg
        s.consecutive_failures = (s.consecutive_failures or 0) + 1
        db.commit()
        return {"success": False, "status_code": e.code, "latency_ms": elapsed, "preview": [], "error": msg}
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        s.last_error = msg
        s.consecutive_failures = (s.consecutive_failures or 0) + 1
        db.commit()
        return {"success": False, "status_code": None, "latency_ms": elapsed, "preview": [], "error": msg}
