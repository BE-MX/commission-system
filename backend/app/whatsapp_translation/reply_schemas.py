"""Ephemeral, bounded reply assistant wire and model contracts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.whatsapp_translation.constants import SUPPORTED_TARGET_LANGUAGES
from app.whatsapp_translation.reply_memory_schemas import ReplyAction


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReplyMessage(StrictModel):
    role: Literal["customer", "salesperson"]
    text: str = Field(min_length=1, max_length=120000)
    timestamp: str = Field(default="", max_length=120)
    quoted_text: str = Field(default="", max_length=12000)
    kind: Literal["text", "media", "unknown"] = "text"


class ContextScope(StrictModel):
    requested_limit: int = Field(default=2000, ge=1, le=2000)
    history_status: str = Field(default="loaded_only", max_length=40)
    truncated: bool = False
    omitted_media: bool = False
    latest_visible: bool = False


class ReplyRequest(StrictModel):
    mode: Literal["draft", "auto"] = "draft"
    request_id: UUID
    conversation_epoch: UUID
    context_version: int = Field(ge=0)
    draft_version: int = Field(ge=0)
    messages: list[ReplyMessage] = Field(min_length=1, max_length=2000)
    context_scope: ContextScope
    draft_intent: str = Field(default="", max_length=2000)
    target_language: str = "auto"
    fallback_language: str = "en"
    style: Literal["default", "shorter", "softer", "alternative"] = "default"
    goal: str = Field(default="", max_length=500)
    memory_conversation_id: UUID | None = None
    memory_revision: int = Field(default=0, ge=0)
    # Extension-detected language of the current chat; "" means unknown.
    detected_language: str = ""

    @field_validator("target_language", "fallback_language", "detected_language")
    @classmethod
    def supported_language(cls, value, info):
        if value not in SUPPORTED_TARGET_LANGUAGES and not (info.field_name == "target_language" and value == "auto") and not (info.field_name == "detected_language" and value == ""):
            raise ValueError("unsupported language")
        return value

    @model_validator(mode="after")
    def bounded_context(self):
        if sum(len(message.text) + len(message.quoted_text) for message in self.messages) > 120000:
            raise ValueError("context too large")
        if len(self.messages) > self.context_scope.requested_limit:
            raise ValueError("message count exceeds selected scope")
        return self


class ReplySource(StrictModel):
    document_id: int
    revision_id: int
    version_no: int
    section: str
    title: str


class ReplyClaim(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    source_index: int = Field(ge=0, le=5)
    quote: str = Field(min_length=1, max_length=500)


class ReplyOutput(StrictModel):
    auto_action: Literal["reply", "wait", "handoff"] | None = None
    reply_segments: list[str] = Field(default_factory=list, max_length=3)
    status: Literal["ready", "needs_confirmation", "insufficient_context"]
    reply_language: str
    reply_text: str = Field(min_length=1, max_length=3000)
    meaning_zh: str = Field(min_length=1, max_length=1800)
    rationale_zh: str = Field(min_length=1, max_length=600)
    claims: list[ReplyClaim] = Field(default_factory=list, max_length=12)
    risk_flags: list[str] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("risk_flags", "missing_information")
    @classmethod
    def bounded_notes(cls, values):
        if any(len(value) > 300 for value in values):
            raise ValueError("note too long")
        return values




class ReplyResponse(ReplyOutput):
    request_id: UUID
    conversation_epoch: UUID
    context_version: int
    draft_version: int
    sources: list[ReplySource] = Field(default_factory=list, max_length=6)
    memory_error: str | None = None
    context_processing: str = "full"
    action: ReplyAction | None = None
    memory_conversation_id: UUID | None = None
    memory_instance_id: UUID | None = None
    memory_revision: int = 0
    memory_update: list[dict] = Field(default_factory=list, max_length=80)
    handoff: dict = Field(default_factory=dict)
    materials: list[dict] = Field(default_factory=list, max_length=6)
