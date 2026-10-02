"""Bounded machine protocol. No worker endpoint creates or approves content."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HeartbeatRequest(WorkerPayload):
    sender_email: str = Field(max_length=255)
    auth_status: Literal["active", "expired", "unbound", "unknown"]


class FenceRequest(WorkerPayload):
    fencing_token: int = Field(ge=1)


class ResultRequest(FenceRequest):
    outcome: Literal["accepted", "failed_safe", "unknown"]
    provider_message_id: str | None = Field(default=None, max_length=128)
    error_kind: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")


class InboxEvent(WorkerPayload):
    provider_message_id: str = Field(min_length=1, max_length=191)
    from_address: str = Field(max_length=255)
    to_address: str = Field(max_length=255)
    subject: str = Field(default="", max_length=500)
    received_at_utc: datetime
    in_reply_to: str | None = Field(default=None, max_length=255)
    references_header: str | None = Field(default=None, max_length=2000)
    original_recipient_candidates: list[str] = Field(default_factory=list, max_length=10)


class EventsRequest(WorkerPayload):
    events: list[InboxEvent] = Field(max_length=50)


class ClassifyRequest(WorkerPayload):
    classification: Literal["human_reply", "auto_reply", "bounce", "opt_out", "other"]
    reason: str = Field(min_length=1, max_length=500)
