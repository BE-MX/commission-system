import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class KnownFactIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    source_kind: str | None = Field(None, max_length=32)
    source_ref: str | None = Field(None, max_length=100)
    observed_at: dt.date | None = None
    carried_from_prep_id: int | None = Field(None, gt=0)


class PrepCreateIn(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64)
    customer_id: int = Field(..., gt=0)
    template_code: str = Field(..., min_length=1, max_length=8)
    goal: str = Field(..., min_length=1, max_length=200)
    source_task_id: int | None = Field(None, gt=0)
    contact_reason: str | None = Field(None, max_length=300)
    reason_source: Literal["last_followup", "customer_inquiry", "public_update", "other"] | None = None
    reason_date: dt.date | None = None
    known_facts: list[KnownFactIn] = Field(default_factory=list, max_length=8)
    to_confirm: list[str] = Field(default_factory=list, max_length=5)
    answers: dict = Field(default_factory=dict)


class PrepUpdateIn(BaseModel):
    version: int = Field(..., ge=1)
    template_code: str | None = Field(None, max_length=8)
    goal: str | None = Field(None, max_length=200)
    contact_reason: str | None = Field(None, max_length=300)
    reason_source: Literal["last_followup", "customer_inquiry", "public_update", "other"] | None = None
    reason_date: dt.date | None = None
    known_facts: list[KnownFactIn] | None = Field(None, max_length=8)
    to_confirm: list[str] | None = Field(None, max_length=5)
    answers: dict | None = None


class PrepCloneIn(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64)
    template_code: str | None = Field(None, max_length=8)


class PrepFeedbackIn(BaseModel):
    feedback: Literal["useful", "inaccurate"]
