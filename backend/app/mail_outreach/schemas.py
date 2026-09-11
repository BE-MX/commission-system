"""邮件触达域 Pydantic 入参契约。

只收人类 JWT 的业务员/管理员请求；响应为 dict（服务层组装），这里不定义出参模型。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: int = Field(gt=0)
    contact_id: int = Field(gt=0)
    contact_point_id: int = Field(gt=0)
    relationship_goal: Literal["first_intro", "follow_up", "reactivation"]
    request_key: str = Field(min_length=8, max_length=128)


class RevisionCreateRequest(BaseModel):
    """编辑字段留空表示沿用当前版本；regenerate=true 时忽略编辑字段重新调 AI。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    regenerate: bool = False
    subject: str | None = Field(default=None, max_length=255)
    body_text: str | None = None
    meaning_summary_zh: str | None = None
    angle: str | None = Field(default=None, max_length=255)
    cta: str | None = Field(default=None, max_length=255)
    claims: list[dict] | None = None


class SchedulePreviewRequest(BaseModel):
    """可选覆盖；缺省时从当前 revision 的语言/时区/国家组装。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    country: str | None = Field(default=None, max_length=8)
    timezone: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=35)
    office_start: str | None = Field(default=None, max_length=8)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    revision_id: int = Field(gt=0)
    mailbox_binding_id: int = Field(gt=0)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schedule_policy: dict = Field(default_factory=dict)
    scheduled_at_utc: datetime
    reason: str = Field(default="", max_length=500)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=500)


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=500)


class JobCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str = Field(default="", max_length=500)


class MailboxCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(default="agent_mail", max_length=32)
    sender_email: str = Field(min_length=3, max_length=255)
    display_name: str = Field(default="", max_length=128)
    owner_user_id: int | None = Field(default=None, gt=0)
    worker_identity: str = Field(min_length=1, max_length=64)
    cli_workspace: str = Field(min_length=1, max_length=64)
    auth_status: Literal["active", "expired", "unbound", "unknown"] = "unknown"
    daily_quota: int = Field(default=50, gt=0)
    quota_timezone: str = Field(default="Asia/Shanghai", max_length=64)
    pause_reason: str | None = Field(default=None, max_length=255)
    secret_ref: str = Field(default="", max_length=255)
    status: Literal["active", "disabled"] = "active"


class MailboxUpdateRequest(BaseModel):
    """管理员维护：暂停/恢复/配额/状态/授权状态； None 字段不变。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, max_length=128)
    owner_user_id: int | None = Field(default=None, gt=0)
    worker_identity: str | None = Field(default=None, min_length=1, max_length=64)
    cli_workspace: str | None = Field(default=None, min_length=1, max_length=64)
    auth_status: Literal["active", "expired", "unbound", "unknown"] | None = None
    daily_quota: int | None = Field(default=None, gt=0)
    quota_timezone: str | None = Field(default=None, max_length=64)
    pause_reason: str | None = Field(default=None, max_length=255)
    secret_ref: str | None = Field(default=None, max_length=255)
    status: Literal["active", "disabled"] | None = None


__all__ = [
    "ApproveRequest",
    "DraftCreateRequest",
    "JobCancelRequest",
    "MailboxCreateRequest",
    "MailboxUpdateRequest",
    "RejectRequest",
    "RevisionCreateRequest",
    "RevokeRequest",
    "SchedulePreviewRequest",
]
