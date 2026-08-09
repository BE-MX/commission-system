"""Validated request and public response schemas for Customer AI Chat."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=200)


class TurnStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    content: str = Field(default="", max_length=12_000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=5)

    @field_validator("attachment_ids")
    @classmethod
    def validate_attachment_ids(cls, value: list[int]) -> list[int]:
        if any(attachment_id <= 0 for attachment_id in value):
            raise ValueError("附件 ID 必须为正整数")
        if len(value) != len(set(value)):
            raise ValueError("附件不能重复")
        return value

    @model_validator(mode="after")
    def require_content_or_attachment(self):
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("消息或附件至少填写一项")
        return self


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    owner_user_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    session_id: int
    role: str
    request_id: str | None
    content: str
    status: str
    error_message: str | None = None
    retry_of_message_id: int | None = None
    ai_call_log_id: int | None = None
    created_at: datetime
    updated_at: datetime


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    session_id: int
    message_id: int | None
    original_name: str
    mime_type: str
    file_size: int
    attachment_type: str
    status: str
    created_by: int
    created_at: datetime
