"""方舟洞见 — 周会纪要"""

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

from app.insight.ai_helpers import _invoke_meeting_summary, _invoke_meeting_tasks, _fallback_extract_tasks


def upload_minutes(db: Session, user_id: int, data: MinutesUpload) -> MeetingMinutes:
    """上传纪要原文,触发 AI 处理(同步执行简化版)。"""
    if not data.original_text or len(data.original_text.strip()) < 10:
        raise ValueError("会议原文不能为空(至少 10 字符)")

    m = MeetingMinutes(
        meeting_date=data.meeting_date,
        title=data.title or f"{data.meeting_date} 会议",
        duration=data.duration,
        participants=data.participants,
        original_text=data.original_text,
        source_url=data.source_url,
        has_attachment=data.has_attachment,
        word_count_original=len(data.original_text),
        status="processing",
        uploaded_by=user_id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)

    # 同步处理(AI 双 preset)
    try:
        # 1. 精要(Markdown)
        summary_md = _invoke_meeting_summary(db, data.original_text, user_id)
        m.summary_md = summary_md
        m.word_count_summary = len(summary_md or "")

        # 2. 任务清单(JSON 数组)
        tasks_payload = _invoke_meeting_tasks(db, data.original_text, user_id)
        m.tasks_json = tasks_payload

        # 3. 结构化精要(从原文提取 topics / decisions / action_items / outcome)
        structured = _build_structured_summary(summary_md or "", tasks_payload, data)
        m.structured_summary = structured

        # 4. 任务写入 ark_insight_tasks
        for t in (tasks_payload or []):
            task = InsightTask(
                minutes_id=m.id,
                assignee=(t.get("assignee") or "待定")[:50],
                description=(t.get("description") or "(无描述)")[:500],
                deadline=_parse_date(t.get("deadline")),
                priority=t.get("priority") if t.get("priority") in ("high", "medium", "low") else "medium",
                source_quote=(t.get("source_quote") or "")[:500] or None,
                status="pending",
            )
            db.add(task)

        m.status = "published"
    except Exception as e:
        logger.exception("纪要 AI 处理失败")
        m.error_msg = str(e)[:500]
        m.status = "failed"

    db.commit()
    db.refresh(m)
    return m


def get_minutes_status(db: Session, minutes_id: int) -> dict:
    m = db.query(MeetingMinutes).filter(MeetingMinutes.id == minutes_id).first()
    if not m:
        raise ValueError("纪要不存在")
    return {"id": m.id, "status": m.status, "error_msg": m.error_msg}


def list_minutes(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 30,
) -> dict:
    query = db.query(MeetingMinutes)
    if start_date:
        query = query.filter(MeetingMinutes.meeting_date >= start_date)
    if end_date:
        query = query.filter(MeetingMinutes.meeting_date <= end_date)

    total = query.count()
    rows = (
        query.order_by(desc(MeetingMinutes.meeting_date), desc(MeetingMinutes.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 计算每条 pending 任务数
    items = []
    for m in rows:
        pending = (
            db.query(InsightTask)
            .filter(InsightTask.minutes_id == m.id, InsightTask.status.in_(["pending", "in_progress"]))
            .count()
        )
        items.append({
            "id": m.id,
            "meeting_date": m.meeting_date.isoformat() if m.meeting_date else None,
            "title": m.title,
            "duration": m.duration,
            "participants": m.participants,
            "structured_summary": m.structured_summary,
            "status": m.status,
            "has_attachment": m.has_attachment,
            "source_url": m.source_url,
            "pending_tasks": pending,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return {"total": total, "items": items}


def get_minutes_detail(db: Session, minutes_id: int) -> dict:
    m = db.query(MeetingMinutes).filter(MeetingMinutes.id == minutes_id).first()
    if not m:
        raise ValueError("纪要不存在")
    tasks = (
        db.query(InsightTask)
        .filter(InsightTask.minutes_id == minutes_id)
        .order_by(InsightTask.priority.desc(), InsightTask.id)
        .all()
    )
    pending = sum(1 for t in tasks if t.status in ("pending", "in_progress"))
    return {
        "id": m.id,
        "meeting_date": m.meeting_date.isoformat() if m.meeting_date else None,
        "title": m.title,
        "duration": m.duration,
        "participants": m.participants,
        "original_text": m.original_text,
        "summary_md": m.summary_md,
        "structured_summary": m.structured_summary,
        "status": m.status,
        "has_attachment": m.has_attachment,
        "source_url": m.source_url,
        "pending_tasks": pending,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "tasks": [
            {
                "id": t.id,
                "minutes_id": t.minutes_id,
                "assignee": t.assignee,
                "description": t.description,
                "deadline": t.deadline.isoformat() if t.deadline else None,
                "priority": t.priority,
                "status": t.status,
                "source_quote": t.source_quote,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "completed_by": t.completed_by,
                "notes": t.notes,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
    }


def update_task(db: Session, task_id: int, user_id: int, data: TaskUpdate) -> InsightTask:
    t = db.query(InsightTask).filter(InsightTask.id == task_id).first()
    if not t:
        raise ValueError("任务不存在")
    payload = data.model_dump(exclude_unset=True)
    if "status" in payload:
        if payload["status"] not in ("pending", "in_progress", "completed", "overdue"):
            raise ValueError("非法的任务状态")
        if payload["status"] == "completed" and t.status != "completed":
            t.completed_at = datetime.utcnow()
            t.completed_by = user_id
        elif payload["status"] != "completed":
            t.completed_at = None
            t.completed_by = None
        t.status = payload["status"]
    for k in ("notes", "deadline", "priority", "description"):
        if k in payload and payload[k] is not None:
            setattr(t, k, payload[k])
    db.commit()
    db.refresh(t)
    return t


def export_tasks_csv(db: Session, minutes_id: int) -> tuple[str, str]:
    """返回 (filename, csv_text)"""
    m = db.query(MeetingMinutes).filter(MeetingMinutes.id == minutes_id).first()
    if not m:
        raise ValueError("纪要不存在")
    tasks = db.query(InsightTask).filter(InsightTask.minutes_id == minutes_id).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["责任人", "任务描述", "截止日期", "优先级", "状态", "原文依据", "备注"])
    for t in tasks:
        writer.writerow([
            t.assignee,
            t.description,
            t.deadline.isoformat() if t.deadline else "",
            t.priority,
            t.status,
            t.source_quote or "",
            t.notes or "",
        ])
    filename = f"tasks_{m.meeting_date.isoformat() if m.meeting_date else minutes_id}.csv"
    return filename, buf.getvalue()


def _build_structured_summary(summary_md: str, tasks: list, data: MinutesUpload) -> dict:
    """从精要 Markdown + 任务列表组装结构化精要(冗余存储,前端直接展示)。"""
    topics = []
    decisions = []
    pending_followups = []
    current_section = None
    for line in (summary_md or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("##"):
            heading = s.lstrip("#").strip()
            if "决策" in heading or "确认" in heading:
                current_section = "decisions"
            elif "讨论" in heading or "议题" in heading or "重点" in heading:
                current_section = "topics"
            elif "待" in heading or "跟进" in heading or "Action" in heading:
                current_section = "pending"
            else:
                current_section = None
            continue
        if s.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")):
            text = re.sub(r"^[\-\*\•\d\.\s]+", "", s).strip()
            if not text:
                continue
            if current_section == "decisions":
                decisions.append(text[:200])
            elif current_section == "topics":
                topics.append(text[:200])
            elif current_section == "pending":
                pending_followups.append(text[:200])

    action_items = [
        f"{t.get('assignee') or '待定'}:{t.get('description') or ''}{('(' + t.get('deadline') + '前)') if t.get('deadline') else ''}"
        for t in (tasks or [])
    ]

    outcome = ""
    if decisions:
        outcome = "本次会议确认 " + str(len(decisions)) + " 项决策" + ("。" + decisions[0] if decisions else "")
    elif data.title:
        outcome = data.title

    return {
        "topics": topics[:8],
        "decisions": decisions[:8],
        "action_items": action_items[:20],
        "pending_followups": pending_followups[:8],
        "outcome": outcome[:200],
    }
