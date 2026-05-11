"""方舟洞见 — Pydantic 请求/响应模型"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


# ── 报告 ────────────────────────────────────────────
class ReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: str
    report_date: date
    title: str
    status: str
    created_at: datetime
    report_metadata: Optional[dict] = None


class ReportDetail(ReportListItem):
    error_msg: Optional[str] = None
    file_path: Optional[str] = None
    source_data: Optional[Any] = None


class ReportImport(BaseModel):
    """ACCIO WORK 推送报告的请求体"""

    report_type: str = Field(..., description="industry_daily/ai_tools/shop_analysis 等")
    report_date: date
    title: str = ""
    html_content: str
    metadata: Optional[dict] = None
    source_data: Optional[Any] = None


# ── 信源 ────────────────────────────────────────────
class SourceBase(BaseModel):
    name: str
    source_type: str
    url: str
    keywords: Optional[list] = None
    css_selector: Optional[str] = None
    request_headers: Optional[dict] = None
    fetch_interval_hours: int = 24
    is_active: bool = True
    pipeline: str = "external"
    sort_order: int = 0


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    url: Optional[str] = None
    keywords: Optional[list] = None
    css_selector: Optional[str] = None
    request_headers: Optional[dict] = None
    fetch_interval_hours: Optional[int] = None
    is_active: Optional[bool] = None
    pipeline: Optional[str] = None
    sort_order: Optional[int] = None


class SourceDetail(SourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_fetched_at: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    created_at: datetime
    updated_at: datetime


# ── 案例库 ────────────────────────────────────────────
class CaseBase(BaseModel):
    title: Optional[str] = ""
    scenario: Optional[str] = None
    what_was_done: Optional[str] = None
    result: Optional[str] = None
    customer_name: Optional[str] = None
    tags: Optional[list[str]] = None
    attachments: Optional[list[dict]] = None
    customer_type: Optional[str] = None
    market: Optional[str] = None
    product_type: Optional[str] = None
    share_person: Optional[str] = ""
    share_date: Optional[date] = None


class CaseManualCreate(CaseBase):
    """业务员表单直接发布(不走 AI)"""

    title: str
    scenario: str
    what_was_done: str
    result: str


class CaseUploadResponse(BaseModel):
    case_id: int
    status: str  # processing / draft / published


class CasePublish(CaseBase):
    """从草稿确认发布,可附带修改字段"""

    pass


class CaseDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    scenario: Optional[str] = None
    what_was_done: Optional[str] = None
    result: Optional[str] = None
    customer_name: Optional[str] = None
    tags: Optional[list] = None
    attachments: Optional[list] = None
    highlights: Optional[list] = None
    customer_type: Optional[str] = None
    market: Optional[str] = None
    product_type: Optional[str] = None
    key_phrases: Optional[list] = None
    raw_summary: Optional[str] = None
    original_content: Optional[str] = None
    source_type: str
    image_path: Optional[str] = None
    share_person: str
    share_date: Optional[date] = None
    uploaded_by: int
    status: str
    error_msg: Optional[str] = None
    like_count: int
    view_count: int
    created_at: datetime
    updated_at: datetime
    # 客户端展示用辅助字段(运行时填充)
    author: Optional[str] = None
    liked: Optional[bool] = False


# ── 周会纪要 ────────────────────────────────────────────
class MinutesUpload(BaseModel):
    meeting_date: date
    title: str = ""
    duration: Optional[str] = None
    participants: Optional[str] = None
    original_text: str
    source_url: Optional[str] = None
    has_attachment: bool = False


class TaskItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    minutes_id: int
    assignee: str
    description: str
    deadline: Optional[date] = None
    priority: str
    status: str
    source_quote: Optional[str] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    deadline: Optional[date] = None
    priority: Optional[str] = None
    description: Optional[str] = None


class MinutesListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_date: date
    title: str
    duration: Optional[str] = None
    participants: Optional[str] = None
    structured_summary: Optional[dict] = None
    status: str
    has_attachment: bool
    source_url: Optional[str] = None
    pending_tasks: int = 0
    created_at: datetime


class MinutesDetail(MinutesListItem):
    original_text: Optional[str] = None
    summary_md: Optional[str] = None
    tasks: list[TaskItem] = []
