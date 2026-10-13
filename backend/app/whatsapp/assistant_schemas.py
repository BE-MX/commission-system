"""Strict model output and public range requests."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_uid: str = Field(min_length=1, max_length=80)
    start_at: datetime
    end_at: datetime
    conversation_uid: str | None = Field(default=None, min_length=1, max_length=120)
    client_request_uid: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('start_at', 'end_at')
    @classmethod
    def require_offset(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('请提供带时区的北京时间范围')
        return value


class AssistantTaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    completed: bool


class Advice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=800)
    message_uids: list[str] = Field(min_length=1, max_length=8)
    knowledge_source_ids: list[str] = Field(default_factory=list, max_length=6)


class FollowUpTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(max_length=800)
    priority: Literal['P0', 'P1', 'P2', 'P3']
    due_date: date | None = None
    message_uids: list[str] = Field(min_length=1, max_length=8)
    knowledge_source_ids: list[str] = Field(default_factory=list, max_length=6)


class ConversationAnalysis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=1, max_length=2000)
    open_questions: list[str] = Field(default_factory=list, max_length=10)
    follow_up_suggestions: list[Advice] = Field(default_factory=list, max_length=8)
    tasks: list[FollowUpTask] = Field(default_factory=list, max_length=8)

    @field_validator('open_questions')
    @classmethod
    def bounded_questions(cls, values):
        if any(not value.strip() or len(value) > 400 for value in values):
            raise ValueError('invalid open question')
        return values
