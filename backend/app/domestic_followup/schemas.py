"""跟进请求体与 AI 输出校验模型。

AiNext 有字段叫 date，与类型名重名会触发 pydantic v2 的 field name clash，
所以本文件统一 import datetime as dt、注解写 dt.date。
"""
import datetime as dt
import types
import typing
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator, model_validator


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


class FollowupOutcomeFields(BaseModel):
    result_code: str | None = Field(None, max_length=32)
    obstacles: list[typing.Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=10)
    evidence_kind: Literal["customer", "assessment"] | None = None
    shared_summary: str | None = Field(None, max_length=500)
    effective_progress: bool = False


class FollowupFields(FollowupOutcomeFields):
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
    development_stage: Literal["new", "contacted", "quoted", "paused"] | None = None
    responsibility_version: int | None = Field(None, ge=1)
    plan_purpose: Literal["development", "maintenance", "other"] | None = None
    plan_assignee_user_id: int | None = Field(None, ge=1)
    historical_only: bool = False


class DirectSaveIn(FollowupFields):
    request_id: str = Field(..., min_length=8, max_length=64)
    raw_text: str | None = Field(None, max_length=20000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=9)
    source: Literal["web", "mobile"] = "web"
    source_task_id: int | None = Field(None, gt=0)


class DraftCreateIn(FollowupOutcomeFields):
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


class EditItemIn(ItemIn):
    id: int | None = Field(None, gt=0)


class EditFollowupIn(FollowupOutcomeFields):
    model_config = {"extra": "forbid"}
    version: int = Field(..., ge=1)
    request_id: str = Field(..., min_length=8, max_length=64)
    reason: str = Field(..., min_length=1, max_length=500)
    raw_text: str | None = Field(None, max_length=20000)
    followup_date: dt.date
    channel: str | None = Field(None, max_length=16)
    summary: str | None = Field(None, max_length=500)
    state_changes: list[str] = Field(default_factory=list, max_length=10)
    next_date: dt.date | None = None
    next_plan: str | None = Field(None, max_length=500)
    next_method: str | None = Field(None, max_length=16)
    items: list[EditItemIn] = Field(default_factory=list, max_length=30)
    attachment_ids: list[int] = Field(default_factory=list, max_length=9)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value):
        if not value.strip():
            raise ValueError("请填写修改原因")
        return value.strip()


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
    contact: str | None = Field(None, max_length=60)
    phone: str | None = Field(None, max_length=40)
    wechat: str | None = Field(None, max_length=80)
    province: str | None = Field(None, max_length=64)
    city: str | None = Field(None, max_length=64)
    duplicate_confirmed: bool = False
    unwon_confirmed: bool = False


# ── AI 输出：宽进，字段缺省给默认值；值域在 ai_parse_service.normalize 里收口 ──

_DROP = object()
_SCALARS = {tp: TypeAdapter(tp) for tp in (int, float, bool)}


def _unwrap_optional(annotation):
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _coerce_one(annotation, value):
    """单个值按期望类型宽进；实在转不了返回 _DROP，由调用方丢弃（落到字段默认值）。"""
    if value is None or value == "":
        return _DROP
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and "text" in annotation.model_fields:
            return {"text": value}  # issues: ["退货率高"] → [{"text": "退货率高"}]
        return _DROP
    if annotation is str:
        if isinstance(value, dict):  # unreadable: [{"text": ...}] 取 text，取不到就丢
            text = value.get("text")
            return str(text) if isinstance(text, (str, int, float)) and str(text) else _DROP
        if isinstance(value, (list, tuple)):
            return _DROP
        return str(value)
    if annotation in _SCALARS:
        try:
            return _SCALARS[annotation].validate_python(value)  # "高" / "否" / "店A" 转不了就用默认值
        except ValidationError:
            return _DROP
    return value


def _coerce(annotation, value):
    annotation = _unwrap_optional(annotation)
    if typing.get_origin(annotation) is list:
        (element,) = typing.get_args(annotation)
        values = value if isinstance(value, list) else [value]  # "订单减少" → ["订单减少"]
        return [v for v in (_coerce_one(element, item) for item in values) if v is not _DROP]
    return _coerce_one(annotation, value)


class _Lenient(BaseModel):
    """模型输出宽进：空值丢掉让默认值生效；类型不对的按期望类型尽量转，转不了就丢弃该字段/元素。

    目标是任何一个字段写歪都不让整份草稿作废（AI 失败会退化成只 OCR，代价太大）。
    值域在 ai_parse_service.normalize 里收口，这里只管形状。
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_shape(cls, data):
        if not isinstance(data, dict):
            return data
        result = {}
        for key, value in data.items():
            field = cls.model_fields.get(key)
            if field is None:
                continue
            coerced = _coerce(field.annotation, value)
            if coerced is not _DROP:
                result[key] = coerced
        return result


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
