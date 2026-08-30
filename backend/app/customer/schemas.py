"""Validated HTTP inputs for the human Customer Hub."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "contacted", "replied", "quoted", "won", "lost", "dismissed"]
    reason: str = Field(..., min_length=1, max_length=1000)
    close_reason_code: str | None = Field(None, max_length=32)
    close_reason_text: str | None = Field(None, max_length=1000)
    linked_order_id: int | None = Field(None, gt=0)
    evidence_event_ids: list[int] = Field(default_factory=list, max_length=100)
    evidence_fact_ids: list[int] = Field(default_factory=list, max_length=100)


class ActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["complete", "dismiss", "snooze", "feedback"]
    outcome_code: str | None = Field(None, max_length=32)
    channel: str | None = Field(None, max_length=16)
    occurred_at: datetime | None = None
    summary: str | None = Field(None, max_length=1000)
    next_step: str | None = Field(None, max_length=1000)
    reason_code: str | None = Field(None, max_length=32)
    note: str | None = Field(None, max_length=1000)
    snoozed_until: datetime | None = None
    feedback: str | None = Field(None, max_length=32)


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(..., gt=0)
    target_customer_id: int | None = Field(None, gt=0)
    action_type: Literal[
        "merge", "split", "assign_primary", "transfer_primary",
        "set_dnc", "remove_dnc", "confirm_material_risk",
    ]
    payload_schema_version: str = Field(..., min_length=1, max_length=32)
    payload_json: dict[str, Any]
    profile_version_id: int = Field(..., gt=0)
    evidence_fact_ids: list[int] = Field(..., min_length=1, max_length=200)
    risk_level: Literal["high", "critical"]
    expires_at: datetime


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(None, max_length=1000)


class ProposalExecute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(..., min_length=16, max_length=64)

