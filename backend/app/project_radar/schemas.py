"""项目雷达 API 输入模型。"""

from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_input: str = Field(min_length=1, max_length=100000)


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: str = Field(min_length=1, max_length=100)


class SubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None
    watch_level: str | None = None
    tags: list[str] | None = None
    note: str | None = Field(default=None, max_length=20000)
    overrides: dict | None = None
    clear_override: str | None = None
    accept_suggestion: str | None = None
    mark_read: bool = False


class UserSettingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    send_empty: bool = False
    sleepy_reminder: bool = True


class GlobalSettingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    normal_push_cooldown_days: int = Field(default=7, ge=1, le=30)


class DingTalkInbound(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=191)
    dingtalk_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=100000)
