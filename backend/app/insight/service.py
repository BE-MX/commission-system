"""方舟洞见 — 业务逻辑层"""

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


# ──────────────────────────────────────────────────────
# 报告(Reports)
# ──────────────────────────────────────────────────────

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
    """手动触发重新生成 — 当前不实现实际信源抓取,仅返回报告条目重置状态。"""
    r = get_report(db, report_id)
    r.status = "pending"
    r.error_msg = None
    db.commit()
    db.refresh(r)
    # TODO: 接入定时任务/异步队列后,这里应触发 generate_industry_daily_report() 等
    logger.info(f"Report {report_id} marked for regeneration (TODO: actual fetch+generate not implemented)")
    return r


# ──────────────────────────────────────────────────────
# 信源(Sources)
# ──────────────────────────────────────────────────────

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


_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_AIHOT_BASE_URL = "https://aihot.virxact.com"


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


# ──────────────────────────────────────────────────────
# 信源连通性测试
# ──────────────────────────────────────────────────────


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


# ──────────────────────────────────────────────────────
# 案例库(Cases)
# ──────────────────────────────────────────────────────

ALLOWED_IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_IMG_SIZE = 5 * 1024 * 1024  # 5 MB


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


_CASE_FIELD_MAP = {
    "title", "scenario", "what_was_done", "result", "customer_name", "tags",
    "customer_type", "market", "product_type", "key_phrases", "raw_summary",
    "customer_country", "communication_channel", "communication_period",
    "total_rounds", "final_result", "background_check_status",
    "rounds_analysis", "dimension_scores", "golden_phrases", "red_flags",
    "core_strengths", "result_analysis", "improvements", "next_actions",
}


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


# ──────────────────────────────────────────────────────
# 周会纪要(Minutes)
# ──────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────
# 工作台首页摘要
# ──────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────
# AI 调用包装
# ──────────────────────────────────────────────────────

def _try_invoke_ai(db: Session, preset_name: str, user_text: str, user_id: Optional[int] = None) -> Optional[str]:
    """统一 AI 调用入口 — preset 缺失时返回 None,由调用方降级。"""
    try:
        from app.ai import service as ai_service
        from app.ai.models import AiPreset

        preset = (
            db.query(AiPreset)
            .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
            .first()
        )
        if not preset or not preset.is_enabled:
            logger.warning(f"AI preset '{preset_name}' missing or disabled, falling back to mock")
            return None

        result = ai_service.chat(
            db=db,
            preset_name=preset_name,
            messages=[{"role": "user", "content": user_text}],
            caller_module="insight",
            caller_user_id=user_id,
        )
        return result.get("content") or ""
    except Exception as e:
        logger.exception(f"AI invoke failed (preset={preset_name})")
        return None


def _safe_json_parse(text: str) -> Optional[Any]:
    """从 AI 返回文本中提取 JSON(支持 ```json fenced 块)。"""
    if not text:
        return None
    candidates = [text]
    # 提取 fenced code block
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        candidates.insert(0, m.group(1))
    # 提取首个 { 到末尾 } 的子串
    if "{" in text and "}" in text:
        start = text.index("{")
        end = text.rindex("}")
        if end > start:
            candidates.insert(0, text[start : end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None


def _invoke_ocr(db: Session, image_path: str, user_id: Optional[int]) -> str:
    """图片 OCR — 通过 ark_ai_presets 中的 ocr_extract preset。"""
    # 注意:当前 ai.service.chat 仅支持纯文本 messages。多模态 OCR 需要扩展为 image_url 消息体。
    # 当 preset 不存在或调用失败时,返回友好提示文本,案例字段由用户手动补充。
    text = _try_invoke_ai(
        db,
        "ocr_extract",
        f"请从以下图片(image path: {image_path})中提取所有文字,保持原有格式输出。",
        user_id,
    )
    if text:
        return text.strip()
    return "[OCR 暂未配置:请在 AI 接入管理中创建多模态 preset 'ocr_extract',或改用文本粘贴方式上传案例]"


def _load_chat_skill() -> str:
    """读取 chat-analysis SKILL 文件内容。"""
    skill_path = Path(__file__).parent / "skills" / "chat-analysis.md"
    if skill_path.exists():
        return skill_path.read_text(encoding="utf-8")
    return ""


# 精简版 chat-analysis SKILL 核心指令（避免完整 452 行文件导致 token 爆炸和超时）
_CASE_SKILL_CORE = """你是莱莎发制品客户聊天记录复盘分析专家。对业务员与客户的聊天记录进行结构化复盘。

## 分析框架

### 1. 基本信息提取
- 客户名称、国家、类型（沙龙/品牌/电商/批发/影视）
- 沟通渠道（WhatsApp/阿里TM/Email/Instagram）
- 沟通时段、总回合数
- 最终结果（成交/未成交/谈判中/流失）

### 2. 回合拆解（R1, R2...）
每个回合标注：
- time: 时间/间隔
- customer_action: 客户动作（兴趣表达/异议提出/沉默/决策信号/流失信号）
- salesperson_action: 业务员动作标签（开场破冰/需求探询/产品展示/证据背书/报价策略/异议处理/推进闭环/情感共鸣/信息确认/节奏把控/防流失锚定/合规守线）
- summary: 回合摘要
- score: 1-5 分
- comment: 一句话评价
超过15回合改为阶段式汇总（破冰需求/产品异议/报价推进/决策闭环）。

### 3. 六维度评分（1-5分整数）
- response_speed: 响应时效（24h内全覆盖=5分）
- talk_track_quality: 话术专业度（USP引用/FABE结构=5分）
- needs_alignment: 需求匹配度（精准判断客户类型=5分）
- deal_momentum: 谈判推进力（每回合有推进方向=5分）
- emotional_engagement: 情感连接度（建立个人连接=5分）
- compliance_risk: 合规与风控（全程合规=5分）
- overall: 加权均分

### 4. 关键话术提取
- golden_phrases: 亮点话术（适用场景、原话、为什么好）
- red_flags: 问题话术（问题类型、原话、问题在哪、修正建议）

### 5. 结果归因
- 成交：分析核心驱动因素（产品差异化/价格策略/供应链速度/情感连接/样品策略）
- 未成交：分析流失根因（价格鸿沟/需求错配/节奏失控/推进力不足/信任缺失/竞品截胡/合规障碍）

### 6. 优化建议
improvements 按优先级 🔴紧急/🟡重要/🟢建议 分层，每条包含问题描述、影响评估、修正方案、预期收益。

### 7. 行动清单
next_actions 按优先级分层，包含具体动作、负责人、截止日期。

## 输出规则
1. 只输出 JSON，不要任何其他文字
2. 所有评分必须是 1-5 的整数
3. 信息不足时字段留空或置 null，不要编造
4. 超过15回合的对话，回合分析改为阶段式汇总
"""


def _invoke_case_format(db: Session, raw_text: str, user_id: Optional[int]) -> dict:
    """案例库整理 — 使用精简版 SKILL 核心指令进行 AI 整理，避免完整文件导致超时。"""
    system_text = (
        _CASE_SKILL_CORE
        + "\n\n## 输出 JSON 格式\n"
        + '{\n'
        '  "title": "案例标题(25字以内)",\n'
        '  "customer_name": "客户名称",\n'
        '  "customer_country": "客户国家",\n'
        '  "customer_type": "客户类型(沙龙/品牌/电商/批发/影视)",\n'
        '  "communication_channel": "沟通渠道(WhatsApp/阿里TM/Email/Instagram)",\n'
        '  "communication_period": "沟通时段",\n'
        '  "total_rounds": 总回合数(整数),\n'
        '  "final_result": "最终结果(成交/未成交/谈判中/流失)",\n'
        '  "background_check_status": "背调状态(有wiki记录/无历史背调)",\n'
        '  "scenario": "场景背景(2-3句话概述)",\n'
        '  "rounds_analysis": [\n'
        '    {"round_no": "R1", "time": "时间/间隔", "customer_action": "客户动作", "salesperson_action": "业务员动作标签", "summary": "回合摘要", "score": 1-5, "comment": "一句话评价"}\n'
        '  ],\n'
        '  "dimension_scores": {\n'
        '    "response_speed": {"score": 1-5, "comment": "简评"},\n'
        '    "talk_track_quality": {"score": 1-5, "comment": "简评"},\n'
        '    "needs_alignment": {"score": 1-5, "comment": "简评"},\n'
        '    "deal_momentum": {"score": 1-5, "comment": "简评"},\n'
        '    "emotional_engagement": {"score": 1-5, "comment": "简评"},\n'
        '    "compliance_risk": {"score": 1-5, "comment": "简评"},\n'
        '    "overall": 加权均分\n'
        '  },\n'
        '  "golden_phrases": [\n'
        '    {"scene": "适用场景", "phrase": "原话", "why": "为什么好(一句话)"}\n'
        '  ],\n'
        '  "red_flags": [\n'
        '    {"issue_type": "问题类型", "phrase": "原话", "problem": "问题在哪(一句话)", "suggestion": "修正建议"}\n'
        '  ],\n'
        '  "core_strengths": ["核心亮点1", "核心亮点2", "核心亮点3"],\n'
        '  "result_analysis": [\n'
        '    {"factor": "驱动因素/流失根因", "evidence": "一句话证据"}\n'
        '  ],\n'
        '  "improvements": [\n'
        '    {"priority": "🔴/🟡/🟢", "problem": "问题描述", "impact": "影响评估", "fix": "修正方案", "benefit": "预期收益"}\n'
        '  ],\n'
        '  "next_actions": [\n'
        '    {"priority": "🔴/🟡/🟢", "action": "具体动作", "owner": "负责人", "deadline": "截止日期或null"}\n'
        '  ],\n'
        '  "tags": ["标签1", "标签2"],\n'
        '  "raw_summary": "100字摘要"\n'
        '}\n'
    )

    user_text = f"请对以下聊天记录进行复盘分析:\n\n{raw_text}"

    try:
        from app.ai import service as ai_service
        from app.ai.models import AiPreset

        preset = (
            db.query(AiPreset)
            .filter(AiPreset.preset_name == "case_library_format", AiPreset.deleted_at.is_(None))
            .first()
        )
        if not preset or not preset.is_enabled:
            logger.warning("AI preset 'case_library_format' missing or disabled, falling back")
            raise ValueError("preset missing")

        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
        result = ai_service.chat(
            db=db,
            preset_name="case_library_format",
            messages=messages,
            caller_module="insight",
            caller_user_id=user_id,
        )
        text = result.get("content") or ""
    except Exception:
        # 降级:用 _try_invoke_ai 走传统方式(无 SKILL)
        text = _try_invoke_ai(db, "case_library_format", user_text, user_id)

    parsed = _safe_json_parse(text or "")
    if not parsed:
        # 最终降级
        first_line = (raw_text or "").strip().split("\n", 1)[0][:25]
        return {
            "title": first_line or "(待补充)",
            "scenario": (raw_text or "")[:200],
            "what_was_done": "",
            "result": "",
            "customer_name": "",
            "tags": [],
            "core_strengths": [],
            "raw_summary": (raw_text or "")[:100],
        }
    return parsed if isinstance(parsed, dict) else {}


def _invoke_meeting_summary(db: Session, original_text: str, user_id: Optional[int]) -> str:
    """精要 Markdown — meeting_summary preset。"""
    prompt = (
        "请将以下钉钉 AI 转录文本整理为精要版会议记录,要求:\n"
        "1. 保留关键决策、关键数据、分歧点;\n"
        "2. 压缩到原文长度的约 20%;\n"
        "3. 格式: ## 核心决策 / ## 主要讨论点 / ## 待跟进事项;\n"
        "4. 不要使用'综上所述'。\n"
        "输出 Markdown 纯文本。\n\n"
        f"原文:\n{original_text}"
    )
    text = _try_invoke_ai(db, "meeting_summary", prompt, user_id)
    if text:
        return text.strip()
    # 降级:截取原文前 500 字 + 提示
    head = (original_text or "")[:500]
    return f"## 主要讨论点\n\n{head}\n\n_AI preset 'meeting_summary' 未配置,以上为原文截断。请在 AI 管理中配置后重新上传。_"


def _invoke_meeting_tasks(db: Session, original_text: str, user_id: Optional[int]) -> list:
    """任务清单 JSON 数组 — meeting_tasks preset。"""
    prompt = (
        "从以下会议转录中提取所有明确的任务指派,输出 JSON 数组,每条任务包含:\n"
        "{\n"
        '  "assignee": "责任人姓名",\n'
        '  "description": "任务描述(50 字以内, 动词开头)",\n'
        '  "deadline": "YYYY-MM-DD 或 null",\n'
        '  "priority": "high/medium/low",\n'
        '  "source_quote": "原文中的相关原句(100 字以内)"\n'
        "}\n"
        "只输出 JSON 数组,不要其他文字。\n\n"
        f"原文:\n{original_text}"
    )
    text = _try_invoke_ai(db, "meeting_tasks", prompt, user_id)
    parsed = _safe_json_parse(text or "")
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "tasks" in parsed and isinstance(parsed["tasks"], list):
        return parsed["tasks"]
    # 降级:从原文用正则匹配中文人名+动词
    return _fallback_extract_tasks(original_text)


def _fallback_extract_tasks(text: str) -> list:
    """从原文简单提取「XXX:动作」式任务,作为 AI preset 缺失时的兜底。"""
    if not text:
        return []
    tasks = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^([一-龥]{2,4})[::](.+)$", line)
        if m and len(m.group(2).strip()) > 4:
            tasks.append({
                "assignee": m.group(1),
                "description": m.group(2).strip()[:200],
                "priority": "medium",
                "source_quote": line[:300],
            })
        if len(tasks) >= 10:
            break
    return tasks


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


# ──────────────────────────────────────────────────────
# Jinja2 渲染(行业日报 / AI 工具速递)
# ──────────────────────────────────────────────────────

def render_industry_daily_html(report_date: date, data: dict) -> str:
    template = _jinja_env.get_template("industry_daily.html")
    return template.render(report_date=report_date, **data)


def render_ai_tools_html(report_date: date, grouped: dict) -> str:
    template = _jinja_env.get_template("ai_tools.html")
    return template.render(report_date=report_date, grouped=grouped)


# ──────────────────────────────────────────────────────
# 报告生成管线
# ──────────────────────────────────────────────────────

_AIHOT_SECTION_MAP = {
    "模型发布/更新": "model",
    "产品发布/更新": "product",
    "行业动态": "industry",
    "论文研究": "paper",
    "技巧与观点": "tips",
}


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


# ──────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────

def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None
