"""Validated manual interaction payloads."""

from datetime import date as Date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatePatch(Payload):
    remark: str | None = Field(None, max_length=10000)
    next_followup_date: Date | None = None
    next_followup_remark: str | None = Field(None, max_length=2000)
    expected_version: int = Field(ge=0)


class GradePut(Payload):
    grade: Literal["S", "A", "B", "C", "D", "E"] | None
    expected_grade: Literal["S", "A", "B", "C", "D", "E"] | None
    suggestion_id: str | None = None


class FollowupPost(Payload):
    channel: Literal["phone", "whatsapp", "email", "tm", "meeting", "sample", "other"]
    content: str = Field(min_length=1, max_length=10000)
    happened_at: datetime
    next_followup_date: Date | None = None
    suggestion_id: str | None = None
    client_request_id: str = Field(min_length=8, max_length=80)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


class ReanalyzePost(Payload):
    client_request_id: str = Field(min_length=8, max_length=80)


class FeedbackPost(Payload):
    value: Literal["useful", "useless", "done", "snoozed"]
    date: Date | None = None


class LinkPost(Payload):
    account_uid: str = Field(max_length=80)
    conversation_uid: str = Field(max_length=120)
    link_type: Literal["linked", "ignored"]
    company_id: str | None = None
    expected_link_id: str | None = None


class WaOpenPost(Payload):
    account_uid: str = Field(max_length=80)
    conversation_uid: str = Field(max_length=120)
    suggestion_id: str | None = None
