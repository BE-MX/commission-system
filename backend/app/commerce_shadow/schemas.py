from typing import Literal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(min_length=1, max_length=64)
    request_key: str = Field(min_length=1, max_length=128)
    invoice_ids: list[int] = Field(default_factory=list, max_length=200)
    payment_ids: list[int] = Field(default_factory=list, max_length=200)
    local_customer_ids: list[int] = Field(default_factory=list, max_length=200)
    through_observation_id: int = Field(ge=1)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Literal["explained", "fixed"]
    evidence: str = Field(min_length=5, max_length=4000)


class ExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: int = Field(gt=0)
    source_event_id: str = Field(min_length=1, max_length=128)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    execution_event_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    candidate_outcome: Literal["accepted", "rejected", "resolved_unknown"]
    actual: dict[str, Any]


class ExecutionReport(BaseModel):
    """Only candidate receipts; the server derives its own immutable bundle."""
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=64)
    dataset_id: str = Field(min_length=1, max_length=64)
    bundle_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    results: list[ExecutionReceipt] = Field(max_length=10000)
    missing_dependencies: list[str] = Field(max_length=10000)
