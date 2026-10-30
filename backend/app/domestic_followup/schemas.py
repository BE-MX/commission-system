"""跟进请求体与 AI 输出校验模型。

AiNext 有字段叫 date，与类型名重名会触发 pydantic v2 的 field name clash，
所以本文件统一 import datetime as dt、注解写 dt.date。
"""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ItemIn(BaseModel):
    kind: Literal["content", "issue", "suggestion"]
    text: str = Field(..., min_length=1, max_length=1000)
    category: str | None = Field(None, max_length=32)
    severity: Literal["一般", "紧急"] | None = None
    origin: Literal["user", "ai_inferred"] = "user"
    record_only: bool = False
    handler_user_id: int | None = Field(None, gt=0)


class ResolveIn(BaseModel):
    item_id: int = Field(..., gt=0)
    status: Literal["resolved", "closed_no_action"] = "resolved"
    resolution: str | None = Field(None, max_length=500)


class FollowupFields(BaseModel):
    customer_id: int | None = Field(None, gt=0)
    followup_date: dt.date | None = None
    channel: str | None = Field(None, max_length=16)
    summary: str | None = Field(None, max_length=500)
    state_changes: list[str] = Field(default_factory=list, max_length=10)
    next_date: dt.date | None = None
    next_plan: str | None = Field(None, max_length=500)
    next_method: str | None = Field(None, max_length=16)
    chat_title: str | None = Field(None, max_length=120)
    items: list[ItemIn] = Field(default_factory=list, max_length=30)
    resolved_items: list[ResolveIn] = Field(default_factory=list, max_length=20)
    close_task_ids: list[int] = Field(default_factory=list, max_length=50)


class DirectSaveIn(FollowupFields):
    request_id: str = Field(..., min_length=8, max_length=64)
    raw_text: str | None = Field(None, max_length=20000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=9)
    source: Literal["web", "mobile"] = "web"
    source_task_id: int | None = Field(None, gt=0)


class DraftCreateIn(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64)
    raw_text: str | None = Field(None, max_length=20000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=9)
    customer_id: int | None = Field(None, gt=0)
    followup_date: dt.date | None = None
    channel: str | None = Field(None, max_length=16)
    source: Literal["web", "mobile"] = "web"
    source_task_id: int | None = Field(None, gt=0)


class ConfirmIn(FollowupFields):
    version: int = Field(..., ge=1)


class ReceiptOkIn(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64)


class SnoozeIn(BaseModel):
    days: int = Field(1, ge=1, le=7)


class TransferIn(BaseModel):
    to_user_id: int = Field(..., gt=0)
    note: str | None = Field(None, max_length=200)


class ItemResolveIn(BaseModel):
    status: Literal["resolved", "closed_no_action"] = "resolved"
    resolution: str | None = Field(None, max_length=500)


class ProspectIn(BaseModel):
    shop_name: str = Field(..., min_length=1, max_length=120)


# ── AI 输出：宽进，字段缺省给默认值；值域在 ai_parse_service.normalize 里收口 ──

class _Lenient(BaseModel):
    """模型常把缺省写成 "" 或 null：直接丢掉这些键，让字段默认值生效，避免整份草稿校验失败。"""

    @model_validator(mode="before")
    @classmethod
    def _drop_blank(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None and v != ""}
        return data


class AiContent(_Lenient):
    text: str = ""
    origin: str = "user"


class AiItem(_Lenient):
    text: str = ""
    category: str | None = None
    severity: str | None = None
    origin: str = "user"


class AiNext(_Lenient):
    date_expression: str | None = None
    date: dt.date | None = None
    method: str | None = None
    plan: str | None = None

    @field_validator("date", mode="before")
    @classmethod
    def _iso_or_none(cls, value):
        try:
            return dt.date.fromisoformat(str(value)[:10])
        except ValueError:
            return None  # "YYYY-MM-DD"、"下周一" 之类的非日期交给 date_parser 按原话重算


class AiCustomerHint(_Lenient):
    chat_title: str | None = None
    matched_customer_id: int | None = None
    confidence: float = 0.0


class AiReceiptFeedback(_Lenient):
    is_receipt_feedback: bool = False
    has_problem: bool | None = None


class AiOcr(_Lenient):
    attachment_index: int = -1
    text: str = ""


class AiParseOut(_Lenient):
    customer_hint: AiCustomerHint | None = None
    summary: str = ""
    channel: str | None = None
    contents: list[AiContent] = Field(default_factory=list)
    issues: list[AiItem] = Field(default_factory=list)
    suggestions: list[AiItem] = Field(default_factory=list)
    state_changes: list[str] = Field(default_factory=list)
    next: AiNext | None = None
    receipt_feedback: AiReceiptFeedback | None = None
    unreadable: list[str] = Field(default_factory=list)
    ocr: list[AiOcr] = Field(default_factory=list)
