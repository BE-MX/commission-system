"""方舟洞见 — 业务员案例库"""

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

from app.insight.ai_helpers import _invoke_ocr, _invoke_case_format


def _save_uploaded_image(file_obj, original_filename: str) -> str:
    """保存上传图片,返回相对路径 uploads/insight/xxx.png"""
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_IMG_EXTS:
        raise ValueError(f"不支持的图片格式: {ext}")
    safe_name = f"case_{uuid.uuid4().hex}{ext}"
    dest = INSIGHT_UPLOAD_DIR / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file_obj, out)
    if dest.stat().st_size > MAX_IMG_SIZE:
        dest.unlink(missing_ok=True)
        raise ValueError("图片超过 5MB 限制")
    return f"/uploads/insight/{safe_name}"


def _apply_case_fields(case: InsightCase, payload: dict) -> None:
    """将 AI 输出或用户表单数据映射到案例模型字段。"""
    for k in _CASE_FIELD_MAP:
        if k in payload:
            v = payload[k]
            if k == "total_rounds" and v is not None:
                try:
                    v = int(v)
                except (ValueError, TypeError):
                    v = None
            setattr(case, k, v)


def _process_case_async(
    case_id: int,
    source_type: str,
    text: Optional[str],
    file_path: Optional[str],
    user_id: Optional[int],
) -> None:
    """后台线程：完成 OCR + AI 整理，更新案例状态。"""
    import threading

    thread_name = threading.current_thread().name
    logger.info("[%s] 开始处理案例 case_id=%s", thread_name, case_id)

    # 后台线程需要独立的 db session
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
        if not case:
            logger.warning("[%s] 案例 case_id=%s 不存在，跳过处理", thread_name, case_id)
            return

        # 1. OCR（截图模式）
        if source_type == "screenshot":
            try:
                ocr_text = _invoke_ocr(db, file_path or "", user_id)
                case.original_content = ocr_text
                db.commit()
            except Exception as e:
                logger.exception("[%s] OCR 失败 case_id=%s", thread_name, case_id)
                case.error_msg = f"OCR失败: {str(e)[:200]}"
                case.status = "failed"
                db.commit()
                return
            raw_text = ocr_text
        else:
            raw_text = text or ""

        # 2. AI 整理
        try:
            ai_payload = _invoke_case_format(db, raw_text, user_id)
            _apply_case_fields(case, ai_payload)
            case.ai_draft = ai_payload
            case.status = "draft"
            logger.info("[%s] 案例 case_id=%s AI 整理完成", thread_name, case_id)
        except Exception as e:
            logger.exception("[%s] AI 整理失败 case_id=%s", thread_name, case_id)
            case.error_msg = str(e)[:500]
            case.status = "failed"

        db.commit()
    finally:
        db.close()


def upload_case(
    db: Session,
    user_id: int,
    user_name: str,
    *,
    source_type: str,
    text: Optional[str],
    file_path: Optional[str],
    share_person: Optional[str],
    share_date: Optional[date],
) -> InsightCase:
    """案例上传(截图 OCR / 文本粘贴) — 创建 processing 记录后立即返回，后台线程完成 AI 整理。"""
    if source_type not in ("screenshot", "text_paste"):
        raise ValueError("source_type 必须为 screenshot 或 text_paste")

    case = InsightCase(
        title="(AI 处理中…)",
        share_person=(share_person or user_name or "")[:50],
        share_date=share_date,
        source_type=source_type,
        image_path=file_path if source_type == "screenshot" else None,
        original_content=text if source_type == "text_paste" else None,
        uploaded_by=user_id,
        status="processing",
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    # 启动后台线程完成 AI 整理，避免阻塞 HTTP 响应
    import threading

    t = threading.Thread(
        target=_process_case_async,
        args=(case.id, source_type, text, file_path, user_id),
        name=f"case-proc-{case.id}",
        daemon=True,
    )
    t.start()

    return case


def manual_create_case(db: Session, user_id: int, user_name: str, data: CaseManualCreate) -> InsightCase:
    """业务员表单直接发布(不走 AI),直接进入 published 状态。"""
    case = InsightCase(
        title=data.title,
        share_person=(data.share_person or user_name or "")[:50],
        share_date=data.share_date or date.today(),
        source_type="manual",
        uploaded_by=user_id,
        status="published",
    )
    _apply_case_fields(case, data.model_dump(exclude_unset=True))
    case.tags = data.tags or []
    case.attachments = data.attachments or []
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def get_case_status(db: Session, case_id: int) -> dict:
    case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
    if not case:
        raise ValueError("案例不存在")
    return {"id": case.id, "status": case.status, "error_msg": case.error_msg}


def publish_case(db: Session, case_id: int, user_id: int, data: CasePublish) -> InsightCase:
    """发布草稿(可附带修改字段和评价修正)。"""
    case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
    if not case:
        raise ValueError("案例不存在")
    if case.uploaded_by != user_id:
        raise ValueError("无权操作此案例")
    if case.status not in ("draft", "failed"):
        raise ValueError(f"案例当前状态({case.status})不允许发布")

    payload = data.model_dump(exclude_unset=True)
    corrections = payload.pop("user_corrections", None)
    for k, v in payload.items():
        if v is not None:
            setattr(case, k, v)
    if corrections is not None:
        case.user_corrections = corrections
    case.status = "published"
    db.commit()
    db.refresh(case)
    return case


def update_case(db: Session, case_id: int, user_id: int, is_admin: bool, data: CaseUpdate) -> InsightCase:
    """编辑已发布的案例 — 作者或 admin 可修改。"""
    case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
    if not case:
        raise ValueError("案例不存在")
    if not is_admin and case.uploaded_by != user_id:
        raise ValueError("无权编辑此案例")

    payload = data.model_dump(exclude_unset=True)
    corrections = payload.pop("user_corrections", None)
    for k, v in payload.items():
        if v is not None:
            setattr(case, k, v)
    if corrections is not None:
        case.user_corrections = corrections
    db.commit()
    db.refresh(case)
    return case


def list_cases(
    db: Session,
    *,
    share_person: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    product_type: Optional[str] = None,
    market: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
    sort: str = "date",
) -> dict:
    query = db.query(InsightCase).filter(InsightCase.status == "published")
    if share_person:
        query = query.filter(InsightCase.share_person == share_person)
    if start_date:
        query = query.filter(InsightCase.share_date >= start_date)
    if end_date:
        query = query.filter(InsightCase.share_date <= end_date)
    if product_type:
        query = query.filter(InsightCase.product_type == product_type)
    if market:
        query = query.filter(InsightCase.market == market)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                InsightCase.title.like(like),
                InsightCase.scenario.like(like),
                InsightCase.what_was_done.like(like),
                InsightCase.result.like(like),
                InsightCase.customer_name.like(like),
                InsightCase.share_person.like(like),
            )
        )
    if tag:
        # JSON 包含搜索 — MySQL JSON_CONTAINS
        query = query.filter(
            func.json_search(InsightCase.tags, "one", tag).isnot(None)
        )

    total = query.count()
    if sort == "likes":
        query = query.order_by(desc(InsightCase.like_count), desc(InsightCase.id))
    else:
        query = query.order_by(desc(InsightCase.share_date), desc(InsightCase.id))

    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "items": items}


def get_case_detail(db: Session, case_id: int, user_id: Optional[int] = None) -> InsightCase:
    case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
    if not case:
        raise ValueError("案例不存在")
    case.view_count = (case.view_count or 0) + 1
    db.commit()
    db.refresh(case)
    return case


def delete_case(db: Session, case_id: int, user_id: int, is_admin: bool = False) -> None:
    case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
    if not case:
        raise ValueError("案例不存在")
    if not is_admin and case.uploaded_by != user_id:
        raise ValueError("无权删除此案例")
    case.status = "archived"
    db.commit()


def toggle_case_like(db: Session, case_id: int, delta: int) -> int:
    """delta = +1 或 -1。返回最新 like_count。"""
    case = db.query(InsightCase).filter(InsightCase.id == case_id).first()
    if not case:
        raise ValueError("案例不存在")
    case.like_count = max(0, (case.like_count or 0) + delta)
    db.commit()
    db.refresh(case)
    return case.like_count
