"""方舟洞见 — 工作台摘要"""

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



def get_dashboard_summary(db: Session, user_name: str = "") -> dict:
    """工作台首页方舟洞见摘要小组件数据。"""
    # 行业情报日报最新一份
    industry = (
        db.query(InsightReport)
        .filter(InsightReport.report_type == "industry_daily", InsightReport.status == "published")
        .order_by(desc(InsightReport.report_date), desc(InsightReport.id))
        .first()
    )
    industry_data = None
    if industry:
        sd = industry.source_data or {}
        quick = sd.get("quick_overview") if isinstance(sd, dict) else None
        industry_data = {
            "latest_date": industry.report_date.isoformat(),
            "report_id": industry.id,
            "quick_overview": quick or [],
        }

    # AI 工具速递最新一份
    ai_tools = (
        db.query(InsightReport)
        .filter(InsightReport.report_type == "ai_tools", InsightReport.status == "published")
        .order_by(desc(InsightReport.report_date), desc(InsightReport.id))
        .first()
    )
    ai_tools_data = None
    if ai_tools:
        sd = ai_tools.source_data or {}
        items = sd.get("items") if isinstance(sd, dict) else None
        if not items and isinstance(sd, list):
            items = sd
        ai_tools_data = {
            "latest_date": ai_tools.report_date.isoformat(),
            "items": (items or [])[:3],
        }

    # 当前用户的待处理任务
    pending_q = db.query(InsightTask).filter(InsightTask.status.in_(["pending", "in_progress"]))
    if user_name:
        pending_q = pending_q.filter(InsightTask.assignee == user_name)
    pending_count = pending_q.count()
    overdue_count = pending_q.filter(InsightTask.status == "overdue").count()

    # 最近的案例
    recent_cases = (
        db.query(InsightCase)
        .filter(InsightCase.status == "published")
        .order_by(desc(InsightCase.created_at))
        .limit(3)
        .all()
    )

    return {
        "industry_daily": industry_data,
        "ai_tools": ai_tools_data,
        "pending_tasks": {"count": pending_count, "overdue_count": overdue_count},
        "recent_cases": {
            "count": len(recent_cases),
            "items": [{"id": c.id, "title": c.title, "share_person": c.share_person} for c in recent_cases],
        },
    }


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None
