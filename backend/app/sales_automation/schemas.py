"""智能获客 HTTP 输入模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProfileUpsert(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    company_website: str | None = Field(None, max_length=512)
    products: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    target_countries: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    default_language: str = Field("en", min_length=2, max_length=16)


class SearchJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    target_count: int = Field(20, ge=1, le=500)
    keywords: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    adapter: str = Field("agent", min_length=1, max_length=64)
    idempotency_key: str | None = Field(None, max_length=64)


class AgentClaim(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=96)


class AgentLease(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=96)
    lease_token: str = Field(..., min_length=32, max_length=128)


class AgentFailure(AgentLease):
    error_message: str = Field(..., min_length=1, max_length=2000)


class CandidateInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    website: str = Field(..., min_length=4, max_length=512)
    country: str | None = Field(None, max_length=128)
    industry: str | None = Field(None, max_length=255)
    description: str | None = None
    source_url: str = Field(..., min_length=4, max_length=1024)
    source_provider: str = Field("agent", max_length=64)
    captured_at: datetime


class CandidateBatch(AgentLease):
    request_key: str = Field(..., min_length=1, max_length=64)
    candidates: list[CandidateInput] = Field(..., min_length=1, max_length=500)


class ContactInput(BaseModel):
    name: str | None = Field(None, max_length=255)
    role: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=320)
    email_status: Literal["unknown", "valid", "risky", "invalid"] | None = None
    verified_at: datetime | None = None
    source_provider: str = Field("agent", max_length=64)
    source_url: str = Field(..., min_length=4, max_length=1024)
    captured_at: datetime
    confidence: float | None = Field(None, ge=0, le=1)

    @field_validator("email")
    @classmethod
    def _email_or_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if "@" not in normalized:
            raise ValueError("email 格式无效")
        return normalized


class ContactBatch(BaseModel):
    contacts: list[ContactInput] = Field(..., min_length=1, max_length=200)


class ResearchFactInput(BaseModel):
    fact_type: str = Field("general", max_length=64)
    claim: str = Field(..., min_length=1)
    source_url: str = Field(..., min_length=4, max_length=1024)
    captured_at: datetime
    confidence: float = Field(..., ge=0, le=1)


class ResearchUpsert(BaseModel):
    summary: str = Field(..., min_length=1)
    facts: list[ResearchFactInput] = Field(..., min_length=1, max_length=100)
    outreach_angles: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    provider: str = Field("agent", max_length=64)
    model: str | None = Field(None, max_length=128)
    idempotency_key: str | None = Field(None, max_length=64)
