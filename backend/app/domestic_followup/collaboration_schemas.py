"""Validated collaboration workflow inputs."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Action = Literal[
    "claim", "offer_handoff", "request_handoff", "accept_handoff", "reject_handoff", "withdraw_handoff",
    "add_collaborator", "remove_collaborator", "release", "open", "reassign", "stop", "reopen",
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Region = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
PositiveId = Annotated[int, Field(gt=0)]
IdList = Annotated[list[PositiveId], Field(max_length=250)]


class CollaborationActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    reason: ShortText | None = None
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)] | None = None
    obstacle: ShortText | None = None
    commitment: ShortText | None = None
    next_step: ShortText | None = None
    recipient_user_id: PositiveId | None = None
    collaborator_user_id: PositiveId | None = None
    handoff_id: PositiveId | None = None
    handoff_version: PositiveId | None = None
    transfer_task_ids: IdList = Field(default_factory=list)
    keep_task_ids: IdList = Field(default_factory=list)
    cancel_task_ids: IdList = Field(default_factory=list)
    selected_record_ids: IdList = Field(default_factory=list)
    allow_future_contact: bool | None = None


class ScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: PositiveId
    customer_id: PositiveId | None = None
    province: Region | None = None
    city: Region | None = None

    @model_validator(mode="after")
    def exactly_one_scope(self):
        if self.customer_id is not None:
            if self.province is not None or self.city is not None:
                raise ValueError("客户授权不能同时选择地区")
        elif not self.province:
            raise ValueError("请选择客户或省份")
        return self


class InitializationEntry(BaseModel):
    customer_id: PositiveId
    token: str = Field(min_length=64, max_length=64)


class InitializationIn(BaseModel):
    items: list[InitializationEntry] = Field(min_length=1, max_length=100)


class CoordinationSettingsIn(BaseModel):
    pending_handoff_days: int = Field(ge=1, le=30)
