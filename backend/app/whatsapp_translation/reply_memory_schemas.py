"""Bounded inquiry records; observations are not tool execution receipts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MemoryChange(MemoryModel):
    replaces: UUID | None = None
    kind: Literal["need", "question", "request", "commitment"]
    status: Literal["confirmed", "tentative", "open", "answered", "mentioned", "reported_done", "cancelled"]
    summary: str = Field(min_length=1, max_length=240)
    message_index: int = Field(ge=0, le=39)
    quote: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def valid_status(self):
        allowed = {"need": {"confirmed", "tentative", "cancelled"},
                   "question": {"open", "answered", "cancelled"},
                   "request": {"open", "answered", "cancelled"},
                   "commitment": {"mentioned", "reported_done", "cancelled"}}
        if self.status not in allowed[self.kind]:
            raise ValueError("invalid observation status")
        return self


class ReplyAction(MemoryModel):
    kind: Literal["answer", "clarify", "provide_asset", "request_quote", "handoff", "close"]
    focus: str = Field(min_length=1, max_length=240)
    question: str = Field(default="", max_length=240)
    owner: Literal["customer", "salesperson", "none"]
    completion_signal: str = Field(min_length=1, max_length=240)


class MemoryCommand(MemoryModel):
    operation: Literal["list", "create", "read", "commit", "correct", "delete"]
    conversation_id: UUID | None = None
    revision: int = Field(default=0, ge=0)
    request_id: UUID | None = None
    entry_id: UUID | None = None
    label: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=240)
    status: Literal["cancelled", "human_confirmed", "human_completed", "pending"] | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if self.operation != "list" and self.conversation_id is None:
            raise ValueError("missing conversation")
        if self.operation == "commit" and self.request_id is None:
            raise ValueError("missing request")
        if self.operation == "correct" and (not self.entry_id or not self.note or not self.status):
            raise ValueError("missing correction")
        return self
