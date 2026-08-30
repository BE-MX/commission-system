"""HTTP and worker schemas for Agent runtime."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SessionCreate(BaseModel):
    profile_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    title: str = Field(..., min_length=1, max_length=255)
    context_type: str | None = Field(None, max_length=40, pattern=r"^[a-z0-9_-]+$")
    context_id: str | None = Field(None, max_length=128)

    @model_validator(mode="after")
    def require_complete_context(self):
        if bool(self.context_type) != bool(self.context_id):
            raise ValueError("context_type 与 context_id 必须同时提供")
        return self


class RunCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    input: dict[str, Any] = Field(default_factory=dict)
    trigger_type: Literal["user", "business_event", "schedule", "shadow"] = "user"
    business_ref_type: str | None = Field(None, max_length=40, pattern=r"^[a-z0-9_-]+$")
    business_ref_id: str | None = Field(None, max_length=128)

    @model_validator(mode="after")
    def require_complete_business_ref(self):
        if bool(self.business_ref_type) != bool(self.business_ref_id):
            raise ValueError("business_ref_type 与 business_ref_id 必须同时提供")
        return self


class FeedbackInput(BaseModel):
    rating: Literal["useful", "not_useful", "corrected"]
    note: str | None = Field(None, max_length=1000)


class CopilotEvaluationRunCreate(BaseModel):
    customer_id: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=8, max_length=128)


class ArtifactDecisionInput(BaseModel):
    note: str | None = Field(None, max_length=1000)


class WorkerClaimInput(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    runtimes: list[Literal["dsh", "openclaw", "native"]] = Field(default_factory=lambda: ["dsh"], min_length=1, max_length=3)


class WorkerLeaseInput(BaseModel):
    worker_id: str = Field(..., min_length=1, max_length=128)
    lease_token: str = Field(..., min_length=32, max_length=128)


class WorkerEventInput(BaseModel):
    sequence_no: int = Field(..., ge=1)
    event_id: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=64)
    schema_version: int = Field(1, ge=1, le=10)
    actor_type: Literal["runtime", "model", "tool"]
    visibility: Literal["user", "admin", "secret"] = "user"
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_payload_cipher: str | None = Field(None, max_length=4_000_000)
    source_event_ids: list[str] = Field(default_factory=list, max_length=100)
    created_at: datetime | None = None

    @field_validator("raw_payload_cipher")
    @classmethod
    def reject_unverified_raw_payload(cls, value: str | None):
        if value:
            raise ValueError("原始事件载荷尚未启用服务端认证加密，当前禁止提交")
        return None

    @model_validator(mode="after")
    def require_canonical_tool_success_output(self):
        if self.event_type != "tool.succeeded":
            return self
        output = self.payload.get("output")
        if (
            set(self.payload) != {"call_id", "output"}
            or not isinstance(self.payload.get("call_id"), str)
            or not self.payload["call_id"]
            or not isinstance(output, dict)
            or not isinstance(output.get("evidence_refs"), list)
            or any(not isinstance(item, dict) for item in output["evidence_refs"])
        ):
            raise ValueError(
                "tool.succeeded 必须使用 payload.output JSON object，且其中包含 evidence_refs"
            )
        return self


class WorkerEventBatch(WorkerLeaseInput):
    events: list[WorkerEventInput] = Field(..., min_length=1, max_length=200)

    @field_validator("events")
    @classmethod
    def require_ordered_events(cls, events: list[WorkerEventInput]):
        numbers = [item.sequence_no for item in events]
        if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
            raise ValueError("events 必须按 sequence_no 严格递增且不得重复")
        return events


class ArtifactInput(BaseModel):
    artifact_type: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_.-]+$")
    schema_version: int = Field(1, ge=1, le=10)
    title: str | None = Field(None, max_length=255)
    content: dict[str, Any]
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class WorkerCompleteInput(WorkerLeaseInput):
    runtime_run_id: str | None = Field(None, max_length=255)
    artifacts: list[ArtifactInput] = Field(default_factory=list, max_length=20)
    steps_used: int = Field(0, ge=0)
    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    cost_usd: Decimal = Field(Decimal("0"), ge=0)


class WorkerFailInput(WorkerLeaseInput):
    error_code: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    error_message: str = Field(..., min_length=1, max_length=1000)
    ambiguous: bool = False


class WorkerHeartbeatInput(WorkerLeaseInput):
    runtime_run_id: str | None = Field(None, max_length=255)
    steps_used: int | None = Field(None, ge=0)
